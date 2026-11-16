from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from types import SimpleNamespace

from core.commit.transaction import CommitError, recover_transaction
from core.logging_system import (
    ContextAdapter,
    configure_logging,
    install_uncaught_exception_logging,
    log_event,
)
from core.queue import QueueRunner, QueueState, QueueStore, compute_snapshot_hash
from core.media.process import CancellationToken
from core.media.probe import probe_media
from core.media.source_identity import capture_identity, identities_match
from core.media.toolchain import Toolchain, probe_gpu_encoder

from .adapter_contract import (
    AdapterContractError,
    error_payload,
    frame as contract_frame,
    media_info,
    project as contract_project,
    source_identity,
    _timeline,
)
from .export_pipeline import export_queue_job
from .models import M3ProjectError, AudioConflictError
from .service import M3ProjectService
from .storage import default_storage_root


class JsonlIpcServer:
    """Versioned JSONL bridge for Electron main/preload.

    One request per line and one response per line keeps the bridge usable in
    a frozen Python worker and easy to diagnose from a Windows log file.
    """

    PROTOCOL = "m3.ipc.v1"

    _IDEMPOTENT_METHODS = {
        "import",
        "open",
        "analysis.start",
        "analysis.cancel",
        "analysis.reanalyze",
        "projects.rename",
        "projects.removeRecent",
        "projects.save",
        "projects.relocateSource",
        "timeline.apply",
        "timeline.undo",
        "timeline.redo",
        "export.createBatch",
        "tasks.pauseQueue",
        "tasks.resumeQueue",
        "tasks.cancelJob",
        "tasks.stopBatch",
        "tasks.retryFailed",
        "recovery.continueRemaining",
        "recovery.dismiss",
        "settings.update",
    }

    def __init__(self, logger: ContextAdapter | None = None) -> None:
        self.service: M3ProjectService | None = None
        self.project_path: Path | None = None
        self.queue_store: QueueStore | None = None
        self.runner: QueueRunner | None = None
        self.logger = logger
        self._state_lock = threading.RLock()
        self._output_lock = threading.RLock()
        self._output_writer = None
        self._request_results: dict[str, dict[str, Any]] = {}
        self._request_order: list[str] = []
        self._request_cache_limit = 512
        self._project_registry: dict[str, str] = {}
        self._recent_projects: list[str] = []
        self._analysis_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="v2lp-analysis")
        self._analysis_tasks: dict[str, dict[str, Any]] = {}
        self._analysis_by_request: dict[str, str] = {}
        self._analysis_epoch = 0
        # Preview decoding is deliberately isolated from the synchronous JSONL
        # request path.  The renderer also limits its own queue, but keeping a
        # hard backend cap prevents direct/legacy callers from starting an
        # unbounded number of ffmpeg processes.
        self._preview_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="v2lp-preview")
        self._preview_tasks: dict[str, dict[str, Any]] = {}
        self._preview_lock = threading.RLock()
        self._preview_generation = 0
        self._subscriptions: set[str] = set()
        self._batch_meta: dict[str, dict[str, Any]] = {}
        self._task_snapshots: dict[str, dict[str, Any]] = {}
        self._gpu_capability: dict[str, Any] | None = None
        self._watcher_stop = threading.Event()
        self._watcher: threading.Thread | None = None
        self._settings_path = Path(
            os.environ.get("VIDEO2LIVEPHOTO_APP_DATA_DIR", str(Path.home() / ".video2livephoto"))
        ) / "settings.json"
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._recent_projects_path = self._settings_path.parent / "recent-projects.json"
        self._load_recent_projects()

    def _load_recent_projects(self) -> None:
        try:
            payload = json.loads(self._recent_projects_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        entries = payload.get("projects") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            return
        for entry in entries[:50]:
            if isinstance(entry, dict):
                project_id = str(entry.get("project_id") or "").strip()
                project_path = str(entry.get("path") or "").strip()
            else:
                project_id, project_path = "", str(entry).strip()
            if not project_path:
                continue
            if project_id:
                self._project_registry[project_id] = project_path
                self._recent_projects.append(project_id)

    def _persist_recent_projects(self) -> None:
        entries = [
            {"project_id": project_id, "path": self._project_registry.get(project_id)}
            for project_id in self._recent_projects[:50]
            if self._project_registry.get(project_id)
        ]
        partial = self._recent_projects_path.with_suffix(".json.partial")
        try:
            partial.write_text(
                json.dumps({"version": 1, "projects": entries}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(partial, self._recent_projects_path)
        except OSError:
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass

    def _remember_project(self, project_id: str, project_path: str | Path) -> None:
        project_id = str(project_id)
        self._project_registry[project_id] = str(Path(project_path).resolve())
        self._recent_projects = [project_id] + [item for item in self._recent_projects if item != project_id]
        self._persist_recent_projects()

    def _close_project(self) -> None:
        with self._preview_lock:
            self._preview_generation += 1
            for task in self._preview_tasks.values():
                task["token"].cancel()
        if self.service is not None:
            log_event(self.logger, "project.close", project_path=str(self.project_path) if self.project_path else None) if self.logger else None
        self._stop_task_watcher()
        if self.runner is not None:
            self.runner.close(cancel_running=True)
            self.runner = None
        self.queue_store = None
        if self.service is not None:
            self.service.close()
            self.service = None
        self._subscriptions.clear()
        self._batch_meta.clear()
        self._task_snapshots.clear()

    def _configure_queue(self, project_path: str | Path) -> None:
        self.project_path = Path(project_path).resolve()
        self.queue_store = QueueStore(self.project_path.with_suffix(".queue.sqlite3"))
        self.queue_store.mark_interrupted_for_restart()
        assert self.service is not None
        self._rebuild_batch_meta_from_queue()

        def promote_after_success(_job, _result) -> int:
            # Start conservatively with one encoder.  A second worker is only
            # admitted after a completed job and a capacity check showing at
            # least four logical CPUs and 8 GiB free on the export volume.
            # This keeps the hard limit at two while avoiding an unmeasured
            # burst on small Windows machines.
            try:
                free_bytes = shutil.disk_usage(self.project_path.parent).free
            except OSError:
                return 1
            return 2 if (os.cpu_count() or 1) >= 4 and free_bytes >= 8 * 1024**3 else 1

        self.runner = QueueRunner(
            self.queue_store,
            lambda job, cancel, report: export_queue_job(
                job,
                cancel,
                report,
                toolchain=self.service.toolchain,
            ),
            max_workers=2,
            initial_workers=1,
            on_job_succeeded=promote_after_success,
            logger=self.logger,
        )
        if self.logger:
            log_event(self.logger, "queue.configure", project_path=str(self.project_path), worker_limit=self.runner.worker_limit)
        self._start_task_watcher()

    def _rebuild_batch_meta_from_queue(self) -> None:
        """Reconstruct batch identities from durable job snapshots after restart."""
        if self.queue_store is None or self.service is None:
            return
        project_id = self.service.snapshot.project_id
        grouped: dict[str, list[Any]] = {}
        for job in self.queue_store.list():
            snapshot = job.snapshot or {}
            if snapshot.get("project_id") != project_id:
                continue
            batch_id = str(snapshot.get("batch_id") or f"legacy:{project_id}")
            grouped.setdefault(batch_id, []).append(job)
        for batch_id, jobs in grouped.items():
            existing = self._batch_meta.get(batch_id, {})
            self._batch_meta[batch_id] = {
                **existing,
                "project_id": project_id,
                "job_ids": [job.job_id for job in jobs],
                "created_at": existing.get("created_at") or min(job.created_at for job in jobs),
                "seq": int(existing.get("seq", 0)),
            }

    def _start_task_watcher(self) -> None:
        if self._watcher is not None and self._watcher.is_alive():
            return
        self._watcher_stop.clear()

        def watch() -> None:
            while not self._watcher_stop.wait(0.15):
                try:
                    self._emit_task_changes()
                except Exception as exc:
                    if self.logger:
                        log_event(self.logger, "queue.watcher.error", level=30, error_message=str(exc))

        self._watcher = threading.Thread(target=watch, name="v2lp-task-watcher", daemon=True)
        self._watcher.start()

    def _stop_task_watcher(self) -> None:
        self._watcher_stop.set()
        watcher = self._watcher
        if watcher is not None and watcher.is_alive() and watcher is not threading.current_thread():
            watcher.join(timeout=1.0)
        self._watcher = None

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        writer = self._output_writer
        if writer is None:
            return
        with self._output_lock:
            writer.write(json.dumps({"event": event, "payload": payload}, ensure_ascii=False) + "\n")
            writer.flush()

    def _remember_result(self, key: str, response: dict[str, Any]) -> None:
        self._request_results[key] = deepcopy(response)
        self._request_order.append(key)
        while len(self._request_order) > self._request_cache_limit:
            old = self._request_order.pop(0)
            self._request_results.pop(old, None)

    def _request_key(self, request: dict[str, Any], method: str, params: dict[str, Any]) -> str | None:
        request_id = params.get("request_id") or request.get("request_id") or request.get("id")
        if not request_id or method not in self._IDEMPOTENT_METHODS:
            return None
        # ``analysis.start`` is a two-phase operation: the initial request is
        # deduplicated by ``_analysis_by_request`` while await_result must be
        # allowed to observe the same task's eventual completion.
        if method == "analysis.start" and not params.get("await_result"):
            return None
        return f"{method}:{request_id}"

    @staticmethod
    def _job_dict(job) -> dict[str, Any]:
        payload = dict(job.__dict__)
        payload["state"] = job.state.value
        return payload

    @staticmethod
    def _stage_for_job(job) -> str:
        return {
            QueueState.PENDING: "queued",
            QueueState.PROCESSING: "encoding",
            QueueState.VALIDATING: "verifying",
            QueueState.COMMITTING: "committing",
            QueueState.SUCCEEDED: "succeeded",
            QueueState.FAILED: "failed",
            QueueState.SKIPPED: "skipped",
            QueueState.INTERRUPTED: "interrupted",
            QueueState.STALE: "failed",
        }.get(job.state, "failed")

    def _contract_job(self, job, batch_id: str) -> dict[str, Any]:
        snapshot = job.snapshot or {}
        segment = snapshot.get("segment") or {}
        result = job.result or {}
        committed_paths = [str(item) for item in (result.get("target_paths") or [])]
        committed_paths.extend([str(result.get("manifest_path"))] if result.get("manifest_path") else [])
        artifacts = []
        has_legacy_pair = any(
            Path(path).suffix.lower() in {".jpg", ".jpeg", ".mov"}
            for path in committed_paths
        ) and not any(Path(path).suffix.lower() == ".livp" for path in committed_paths)
        livephoto_specs = (
            (("jpg", (".jpg", ".jpeg")), ("mov", (".mov",)))
            if has_legacy_pair
            else (("livp", (".livp",)),)
        )
        for kind, suffixes in (("mp4", (".mp4",)), *livephoto_specs):
            value = next((path for path in committed_paths if Path(path).suffix.lower() in suffixes), None)
            name = Path(str(value)).name if value else f"{job.clip_id}.{kind}"
            artifacts.append(
                {
                    "kind": kind,
                    "file_name": name,
                    "rel_dir": "LivePhoto" if kind == "livp" else "视频片段",
                    "status": "committed" if job.state == QueueState.SUCCEEDED else ("failed" if job.state == QueueState.FAILED else "pending"),
                    "size_bytes": str(Path(str(value)).stat().st_size) if value and Path(str(value)).is_file() else None,
                }
            )
        attempt_id = f"{job.job_id}:{job.attempt_count}" if job.attempt_count else None
        attempts = [dict(item) for item in (getattr(job, "attempts", None) or [])]
        if job.attempt_count and not attempts:
            result_encoder = str(result.get("encoder") or "").lower()
            encoder = (
                "gpu"
                if result_encoder in {"h264_nvenc", "h264_qsv", "h264_amf"}
                else "cpu"
            )
            if not result_encoder and job.state in {
                QueueState.PROCESSING,
                QueueState.VALIDATING,
                QueueState.COMMITTING,
            }:
                # The queue always tries the GPU candidates before the CPU
                # fallback.  Keep the live attempt honest until the result
                # records the concrete encoder name.
                encoder = "gpu"
            attempts.append(
                {
                    "attempt_id": attempt_id,
                    "n": job.attempt_count,
                    "encoder": encoder,
                    "started_at": job.created_at,
                    "ended_at": job.updated_at if job.state in {QueueState.SUCCEEDED, QueueState.FAILED, QueueState.INTERRUPTED, QueueState.SKIPPED} else None,
                    "result": "succeeded" if job.state == QueueState.SUCCEEDED else ("failed" if job.state == QueueState.FAILED else ("cancelled" if job.error_code == "CANCELLED" else "running")),
                    "error": error_payload(M3ProjectError(job.error_code or "WORKER_FAILED", job.error_message or "任务失败")) if job.state == QueueState.FAILED else None,
                }
            )
        if attempts:
            attempt_id = str(attempts[-1].get("attempt_id") or attempt_id)
            for attempt in attempts:
                if isinstance(attempt.get("error"), dict) and attempt.get("error", {}).get("code"):
                    attempt["error"] = error_payload(
                        M3ProjectError(
                            str(attempt["error"]["code"]),
                            str(attempt["error"].get("message") or attempt["error"]["code"]),
                        )
                    )
        error = None
        if job.error_code:
            error = error_payload(M3ProjectError(job.error_code, job.error_message or job.error_code))
        progress = None
        if job.state in {QueueState.PROCESSING, QueueState.VALIDATING, QueueState.COMMITTING, QueueState.SUCCEEDED}:
            total_frames = max(
                int(segment.get("end_index", 0)) - int(segment.get("start_index", 0)),
                1,
            )
            if job.phase == "encoding-starting":
                progress = {"kind": "unknown", "note": "正在启动编码器；无响应将自动回退 CPU"}
            elif job.phase == "encoding":
                encoding_ratio = min(max((job.progress - 0.05) / 0.60, 0.0), 1.0)
                done_frames = int(round(encoding_ratio * total_frames))
                progress = {"kind": "frames", "done": done_frames, "total": total_frames}
            else:
                done_frames = total_frames
                progress = {"kind": "frames", "done": done_frames, "total": total_frames}
        return {
            "job_id": job.job_id,
            "batch_id": batch_id,
            "clip_id": job.clip_id,
            "display_index": int(segment.get("output_number", 0)),
            "file_stem": str(segment.get("file_stem") or job.clip_id),
            "stage": self._stage_for_job(job),
            "progress": progress,
            "attempts": attempts,
            "current_attempt_id": attempt_id if job.state in {QueueState.PROCESSING, QueueState.VALIDATING, QueueState.COMMITTING} else None,
            "artifacts": artifacts,
            "error": error,
            "cancellable": job.state in {QueueState.PENDING, QueueState.PROCESSING, QueueState.VALIDATING},
            "cancel_wait_reason": "当前阶段完成后取消" if job.state in {QueueState.VALIDATING, QueueState.COMMITTING} else None,
            "cancel_requested": bool(job.error_code == "CANCEL_REQUESTED"),
            "verification": {
                "local": "passed" if job.state == QueueState.SUCCEEDED else ("failed" if job.state == QueueState.FAILED else "pending"),
                "local_report_id": (
                    str(Path(getattr(job, "output_dir", "") or "") / "导出报告.json")
                    if job.state in {
                        QueueState.SUCCEEDED,
                        QueueState.FAILED,
                        QueueState.SKIPPED,
                        QueueState.INTERRUPTED,
                    }
                    and getattr(job, "output_dir", None)
                    else None
                ),
                "devices": {"iphone": "unverified", "wechat_moments": "unverified", "xiaohongshu": "unverified", "douyin": "unverified"},
            },
            "replaces_previous": False,
            "previous_protected": job.state not in {QueueState.SUCCEEDED, QueueState.FAILED, QueueState.SKIPPED},
        }

    def _contract_batch(self, batch_id: str, project_id: str | None = None) -> dict[str, Any]:
        if self.queue_store is None:
            raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
        meta = self._batch_meta.get(batch_id, {})
        ids = set(meta.get("job_ids") or [])
        jobs = self.queue_store.list()
        selected = [job for job in jobs if (not ids or job.job_id in ids)]
        if project_id is not None:
            selected = [job for job in selected if (job.snapshot or {}).get("project_id") == project_id]
        if not selected:
            raise M3ProjectError("BATCH_NOT_FOUND", f"找不到任务批次：{batch_id}")
        pid = project_id or meta.get("project_id") or (selected[0].snapshot or {}).get("project_id")
        snapshot = meta.get("snapshot") or {
            "snapshot_id": f"snapshot:{batch_id}",
            "project_id": pid,
            "edit_version": int(getattr(self.service.snapshot, "saved_revision", 0)) if self.service else 0,
            "created_at": selected[0].created_at,
            "settings": {"output_dir": selected[0].output_dir or "", "quality": "source", "color": "sdr_rec709", "name_base": Path(self.project_path or "project").stem},
            "clips": [
                {
                    "clip_id": job.clip_id,
                    "display_index": int((job.snapshot.get("segment") or {}).get("output_number", 0)),
                    "start_frame": int((job.snapshot.get("segment") or {}).get("start_index", 0)),
                    "end_frame": int((job.snapshot.get("segment") or {}).get("end_index", 0)),
                    "audio": "source" if (job.snapshot.get("segment") or {}).get("audio_enabled", True) else "muted",
                    "cover_frame": int((job.snapshot.get("segment") or {}).get("cover_frame_index") or (job.snapshot.get("segment") or {}).get("start_index", 0)),
                    "file_stem": str((job.snapshot.get("segment") or {}).get("file_stem") or job.clip_id),
                    "pair_id": job.clip_id,
                }
                for job in selected
            ],
        }
        states = {job.state for job in selected}
        if states <= {QueueState.SUCCEEDED}:
            state = "completed"
        elif QueueState.INTERRUPTED in states:
            state = "interrupted"
        elif states & {QueueState.PROCESSING, QueueState.VALIDATING, QueueState.COMMITTING}:
            state = "running"
        elif states <= {QueueState.PENDING, QueueState.SKIPPED}:
            state = "paused" if self.runner and getattr(self.runner, "_paused", False) else "running"
        elif QueueState.FAILED in states:
            state = "completed"
        else:
            state = str(meta.get("state") or "running")
        seq = int(meta.get("seq", 0))
        return {
            "batch_id": batch_id,
            "project_id": pid,
            "snapshot": snapshot,
            "state": state,
            "created_at": meta.get("created_at", selected[0].created_at),
            "seq": seq,
            "jobs": [self._contract_job(job, batch_id) for job in selected],
            "active_slots": len(self.runner.running_job_ids) if self.runner else 0,
        }

    def _emit_task_changes(self) -> None:
        if not self.queue_store or not self._subscriptions:
            return
        jobs = self.queue_store.list()
        by_batch: dict[str, list[Any]] = {}
        for job in jobs:
            batch_id = next((bid for bid, meta in self._batch_meta.items() if job.job_id in set(meta.get("job_ids") or [])), None)
            if batch_id is None:
                batch_id = f"legacy:{(job.snapshot or {}).get('project_id', '')}"
            by_batch.setdefault(batch_id, []).append(job)
        for batch_id, selected in by_batch.items():
            project_id = (selected[0].snapshot or {}).get("project_id")
            if project_id not in self._subscriptions:
                continue
            batch = self._contract_batch(batch_id, project_id)
            previous = self._task_snapshots.get(batch_id)
            if previous is None:
                self._task_snapshots[batch_id] = deepcopy(batch)
                self._emit("v2lp:tasks:event", {"type": "batch_snapshot", "project_id": project_id, "batch": batch})
                if batch.get("state") == "completed":
                    self._write_export_report(batch_id)
                continue
            old_jobs = {item["job_id"]: item for item in previous.get("jobs", [])}
            meta = self._batch_meta.setdefault(batch_id, {})
            if (
                previous.get("state") != batch.get("state")
                or previous.get("active_slots") != batch.get("active_slots")
            ):
                meta["seq"] = int(meta.get("seq", 0)) + 1
                batch["seq"] = meta["seq"]
                self._emit(
                    "v2lp:tasks:event",
                    {
                        "type": "batch_patch",
                        "project_id": project_id,
                        "batch_id": batch_id,
                        "seq": batch["seq"],
                        "patch": {
                            "state": batch.get("state"),
                            "active_slots": batch.get("active_slots", 0),
                        },
                    },
                )
            for job in batch["jobs"]:
                old = old_jobs.get(job["job_id"])
                if old == job:
                    continue
                meta["seq"] = int(meta.get("seq", 0)) + 1
                batch["seq"] = meta["seq"]
                self._emit("v2lp:tasks:event", {"type": "job_patch", "project_id": project_id, "batch_id": batch_id, "seq": batch["seq"], "job_id": job["job_id"], "attempt_id": job.get("current_attempt_id"), "patch": job})
            if batch.get("state") == "completed":
                self._write_export_report(batch_id)
            self._task_snapshots[batch_id] = deepcopy(batch)

    def _write_export_report(self, batch_id: str | None = None) -> str | None:
        """Write a batch report only after every queued job reaches a terminal state."""
        if self.queue_store is None:
            return None
        jobs = self.queue_store.list()
        if batch_id:
            meta = self._batch_meta.get(batch_id, {})
            ids = set(meta.get("job_ids") or [])
            if ids:
                jobs = [job for job in jobs if job.job_id in ids]
            else:
                project_id = str(meta.get("project_id") or "")
                jobs = [
                    job
                    for job in jobs
                    if (job.snapshot or {}).get("project_id") == project_id
                    and str((job.snapshot or {}).get("batch_id") or f"legacy:{project_id}") == batch_id
                ]
        if not jobs or any(
            job.state
            in {
                QueueState.PENDING,
                QueueState.PROCESSING,
                QueueState.VALIDATING,
                QueueState.COMMITTING,
            }
            for job in jobs
        ):
            return None
        output_dirs = {job.output_dir for job in jobs if job.output_dir}
        if len(output_dirs) != 1:
            return None
        output_dir = Path(next(iter(output_dirs))).resolve()
        report_path = output_dir / "导出报告.json"
        payload = {
            "schema_version": "m6.export-report.v1",
            "status": (
                "complete"
                if all(job.state == QueueState.SUCCEEDED for job in jobs)
                else "complete_with_errors"
            ),
            "project_id": jobs[0].snapshot.get("project_id"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "jobs": [self._job_dict(job) for job in jobs],
        }
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            partial = output_dir / ".导出报告.json.partial"
            partial.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(partial, report_path)
        except OSError:
            return None
        return str(report_path)

    def _mark_export_report_in_progress(
        self, output_dir: Path, project_id: str | None
    ) -> None:
        """Replace a prior final report so a new batch cannot expose stale data."""
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            report_path = output_dir / "导出报告.json"
            partial = output_dir / ".导出报告.json.partial"
            partial.write_text(
                json.dumps(
                    {
                        "schema_version": "m6.export-report.v1",
                        "status": "in_progress",
                        "project_id": project_id,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "jobs": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(partial, report_path)
        except OSError:
            # The export itself remains governed by its own transaction; a
            # report write failure is surfaced by report_path=None on status.
            return

    def _resolve_project_path(self, project_id: str) -> Path:
        value = str(project_id or "")
        registered = self._project_registry.get(value)
        if registered:
            return Path(registered).resolve()
        candidate = Path(value)
        if candidate.is_file():
            return candidate.resolve()
        raise M3ProjectError("PROJECT_NOT_FOUND", f"找不到项目：{value}")

    @staticmethod
    def _resolve_media_path(params: dict[str, Any]) -> Path:
        file_ref = params.get("file") if isinstance(params.get("file"), dict) else {}
        candidate = str(params.get("source_path") or file_ref.get("display_path") or "")
        if not candidate:
            raise M3ProjectError("MEDIA_READ_DENIED", "没有可读取的媒体引用。")
        path = Path(candidate).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in {".mp4", ".mov", ".m4v"}:
            raise M3ProjectError("MEDIA_READ_DENIED", "媒体引用无效或扩展名不受支持。")
        return path

    def _ensure_project(self, project_id: str | None = None) -> M3ProjectService:
        if project_id and (self.service is None or self.service.snapshot.project_id != project_id):
            path = self._resolve_project_path(project_id)
            self._close_project()
            self.service = M3ProjectService.open_project(path)
            self._remember_project(self.service.snapshot.project_id, path)
            self._configure_queue(path)
        if self.service is None:
            raise M3ProjectError("PROJECT_NOT_OPEN", "请先导入或打开项目。")
        if project_id and self.service.snapshot.project_id != project_id:
            raise M3ProjectError("PROJECT_NOT_FOUND", f"当前项目不是 {project_id}。")
        return self.service

    def _contract_connection(self) -> dict[str, Any]:
        gpu = self._gpu_capability_info()
        return {
            "mode": "desktop",
            "app_version": os.environ.get("VIDEO2LIVEPHOTO_APP_VERSION", "1.0.0-candidate"),
            "backend_version": "m3-python+queue.v1",
            "capabilities": {
                "backend_version": "m3-python+queue.v1",
                "frame_accurate_preview": True,
                "gpu": gpu,
                "hdr_output": {"supported": False, "note": "当前导出链路仅能证明 SDR/源色彩路径。"},
                "declick_audio": False,
                "max_parallel_jobs": self.runner.worker_limit if self.runner else 1,
                "livephoto_hint": {"short_below_ms": 1000, "long_above_ms": 3000},
            },
        }

    def _gpu_capability_info(self) -> dict[str, Any]:
        if self._gpu_capability is not None:
            return dict(self._gpu_capability)
        try:
            toolchain = self.service.toolchain if self.service is not None else Toolchain.discover()
            encoder, note = probe_gpu_encoder(toolchain)
        except Exception as exc:
            encoder = None
            note = f"GPU 编码器自检失败，将使用 CPU 回退路径：{exc}"
        self._gpu_capability = {
            "available": encoder is not None,
            "verified_encoder": encoder,
            "note": None if encoder is not None else note,
        }
        return dict(self._gpu_capability)

    def _settings_defaults(self) -> dict[str, Any]:
        storage_root = default_storage_root()
        defaults = {
            "default_output_dir": str(storage_root / "Exports"),
            "default_quality": "source",
            "default_color": "sdr_rec709",
            "cache_limit_gb": 20,
            "proxy_resolution": "720p",
        }
        try:
            persisted = json.loads(self._settings_path.read_text(encoding="utf-8"))
            if isinstance(persisted, dict):
                legacy_default = (Path.home() / "Videos" / "Video2LivePhoto").resolve()
                stored_output = persisted.get("default_output_dir")
                if isinstance(stored_output, str) and stored_output.strip():
                    try:
                        is_legacy_default = Path(stored_output).resolve() == legacy_default
                    except OSError:
                        is_legacy_default = False
                    if not is_legacy_default:
                        defaults["default_output_dir"] = stored_output
                defaults.update(
                    {
                        key: value
                        for key, value in persisted.items()
                        if key != "default_output_dir"
                    }
                )
        except (OSError, json.JSONDecodeError):
            pass
        return defaults

    def _get_queue_job(self, job_id: str):
        if self.queue_store is None:
            raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
        try:
            return self.queue_store.get(str(job_id))
        except KeyError as exc:
            raise M3ProjectError("JOB_NOT_FOUND", f"找不到导出任务：{job_id}") from exc

    @staticmethod
    def _committed_artifact_path(job: Any, kind: str) -> Path:
        suffixes = {
            "mp4": {".mp4"},
            "livp": {".livp"},
            # Read-only compatibility for exports created before the single
            # file LIVP contract. New exports never publish these artifacts.
            "jpg": {".jpg", ".jpeg"},
            "mov": {".mov"},
        }.get(kind)
        if suffixes is None:
            raise M3ProjectError("ARTIFACT_KIND_INVALID", "不支持的产物类型。", details={"kind": kind})
        if job.state != QueueState.SUCCEEDED:
            raise M3ProjectError("ARTIFACT_NOT_COMMITTED", "该片段尚未提交成功，暂时不能打开。")
        output_root = Path(job.output_dir or "").resolve()
        result = job.result or {}
        candidates = [str(item) for item in (result.get("target_paths") or [])]
        if result.get("manifest_path"):
            candidates.append(str(result["manifest_path"]))
        for value in candidates:
            candidate = Path(value)
            if not candidate.is_absolute():
                continue
            candidate = candidate.resolve()
            try:
                candidate.relative_to(output_root)
            except ValueError:
                continue
            if candidate.suffix.lower() in suffixes and candidate.is_file():
                return candidate
        raise M3ProjectError("ARTIFACT_NOT_FOUND", "已提交记录中找不到对应产物文件。", details={"kind": kind})

    def _output_directory_for_request(self, params: dict[str, Any]) -> Path:
        project_id = str(params.get("project_id") or "")
        job_id = str(params.get("job_id") or "")
        if job_id:
            job = self._get_queue_job(job_id)
            if project_id and (job.snapshot or {}).get("project_id") != project_id:
                raise M3ProjectError("PROJECT_JOB_MISMATCH", "任务不属于当前项目。")
        else:
            if self.queue_store is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            jobs = [
                item
                for item in self.queue_store.list()
                if (item.snapshot or {}).get("project_id") == project_id and item.output_dir
            ]
            if not jobs:
                raise M3ProjectError("OUTPUT_NOT_FOUND", "当前项目还没有可定位的导出目录。")
            job = max(jobs, key=lambda item: str(item.created_at))
        output_dir = Path(job.output_dir or "").resolve()
        if not output_dir.is_dir():
            raise M3ProjectError("OUTPUT_NOT_FOUND", "导出目录不存在。")
        return output_dir

    @staticmethod
    def _color_override_for_snapshot(snapshot: Any) -> str | None:
        value = getattr(snapshot, "color_override", None)
        return str(value) if value else None

    @staticmethod
    def _safe_export_component(value: str, fallback: str = "项目") -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\u0000-\u001f]', "_", str(value or "")).strip(" .")
        if not cleaned:
            cleaned = fallback
        if cleaned.lower() in {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}:
            cleaned = f"{cleaned}_"
        return cleaned

    def _new_export_directory(self, root: Path, project_name: str, batch_id: str) -> Path:
        root = root.resolve()
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        folder_name = f"livephotos {self._safe_export_component(project_name)} {timestamp}"
        candidate = root / folder_name
        try:
            candidate.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            candidate = root / f"{folder_name}_{batch_id[:8]}"
            candidate.mkdir(parents=True, exist_ok=False)
        return candidate.resolve()

    @staticmethod
    def _export_intent_key(
        service: M3ProjectService,
        selected: list[Any],
        settings: dict[str, Any],
        root: Path,
    ) -> str:
        """Hash only stable export intent, excluding generated batch paths and IDs."""
        payload = {
            "project_id": service.snapshot.project_id,
            "source_identity": service.snapshot.source_identity,
            "edit_version": int(getattr(service.snapshot, "saved_revision", 0)),
            "clips": [
                {
                    "clip_id": segment.clip_id,
                    "start_index": segment.start_index,
                    "end_index": segment.end_index,
                    "audio_enabled": bool(segment.audio_enabled),
                    "cover_frame_index": segment.cover_frame_index,
                    "output_number": segment.output_number,
                }
                for segment in selected
            ],
            "settings": {
                "output_root": str(root),
                "quality": str(settings.get("quality", "source")),
                "color": str(settings.get("color", "sdr_rec709")),
                "name_base": str(settings.get("name_base") or Path(service.snapshot.source_path).stem),
            },
        }
        return compute_snapshot_hash(payload)

    def _run_analysis(self, analysis_id: str, params: dict[str, Any], token: CancellationToken, epoch: int) -> dict[str, Any]:
        source_path = str(self._resolve_media_path(params))
        request_id = str(params.get("request_id") or "")
        project_path_value = str(params.get("project_path") or "").strip()
        if project_path_value:
            project_path = Path(project_path_value)
        else:
            root = Path(
                os.environ.get(
                    "VIDEO2LIVEPHOTO_PROJECT_DIR",
                    str(default_storage_root() / "Projects"),
                )
            )
            root.mkdir(parents=True, exist_ok=True)
            project_path = root / f"{uuid.uuid4()}.sqlite3"
        cache_root = params.get("cache_root") or str(project_path.with_suffix(".m1-cache"))
        selected_stream = None if params.get("video_stream_index") is None else int(params["video_stream_index"])
        color_override = str(params.get("color_override") or "").strip() or None
        if selected_stream is not None:
            cache_path = Path(str(cache_root))
            cache_root = str(cache_path.with_name(f"{cache_path.name}-stream-{selected_stream}"))
        seq = 0
        current_stage = "probe"
        stage_state: dict[str, dict[str, Any]] = {
            "probe": {"id": "probe", "status": "running", "progress": None, "note": None},
            "frame_index": {"id": "frame_index", "status": "pending", "progress": None, "note": None},
            "shot_detect": {"id": "shot_detect", "status": "pending", "progress": None, "note": None},
        }

        def publish(*, shots_found: int | None = None, error: dict[str, Any] | None = None) -> None:
            nonlocal seq
            seq += 1
            payload = {
                "analysis_id": analysis_id,
                "request_id": request_id,
                "seq": seq,
                "stages": [deepcopy(stage_state[key]) for key in ("probe", "frame_index", "shot_detect")],
                "shots_found": shots_found,
                "slow_hint": None,
            }
            if error is not None:
                payload["error"] = error
            self._emit("v2lp:analysis:event", payload)

        def on_progress(stage: str, done: int, total: int | None) -> None:
            nonlocal current_stage
            current_stage = stage
            state = stage_state[stage]
            state["status"] = "done" if total is not None and done >= total else "running"
            state["progress"] = {"done": max(0, int(done)), "total": int(total), "unit": "frames"} if total is not None else None
            if stage == "frame_index":
                stage_state["probe"]["status"] = "done"
            elif stage == "shot_detect":
                stage_state["probe"]["status"] = "done"
                stage_state["frame_index"]["status"] = "done"
            publish()

        publish()
        try:
            service = M3ProjectService.import_media(
                source_path,
                project_path=project_path,
                cache_root=cache_root,
                token=token,
                video_stream_index=selected_stream,
                color_override=color_override,
                progress_callback=on_progress,
            )
            with self._state_lock:
                if epoch == self._analysis_epoch:
                    self._close_project()
                    self.service = service
                    self._remember_project(service.snapshot.project_id, project_path)
                    self._configure_queue(project_path)
                else:
                    service.close()
            result = {
                "project_id": service.snapshot.project_id,
                "warnings": ([{"code": "COLOR_SELECTED_BY_USER", "message": "已按导入时选择的色彩类型保存项目。"}] if color_override else []),
                "project_path": str(project_path.resolve()),
            }
            for state in stage_state.values():
                state["status"] = "done"
            stage_state["frame_index"]["progress"] = {"done": service.snapshot.frame_count, "total": service.snapshot.frame_count, "unit": "frames"}
            stage_state["shot_detect"]["progress"] = {"done": service.snapshot.frame_count, "total": service.snapshot.frame_count, "unit": "frames"}
            publish(shots_found=len(service.snapshot.cuts))
            return result
        except Exception as exc:
            code = getattr(exc, "code", "ANALYSIS_WORKER_EXITED")
            stage_state[current_stage]["status"] = "failed"
            stage_state[current_stage]["note"] = str(exc)
            publish(error=error_payload(exc))
            raise M3ProjectError(code, str(exc), details=getattr(exc, "details", {})) from exc

    def _start_analysis(self, request: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        rid = str(params.get("request_id") or request.get("id") or "")
        if rid and rid in self._analysis_by_request:
            analysis_id = self._analysis_by_request[rid]
            task = self._analysis_tasks.get(analysis_id)
            if params.get("await_result"):
                if task is None:
                    raise M3ProjectError("ANALYSIS_NOT_FOUND", "分析任务不存在。")
                return {"ok": True, **task["future"].result()}
            return {"ok": True, "analysis_id": analysis_id, "deduplicated": True}
        analysis_id = str(uuid.uuid4())
        self._analysis_epoch += 1
        epoch = self._analysis_epoch
        token = CancellationToken()
        future = self._analysis_executor.submit(self._run_analysis, analysis_id, params, token, epoch)
        self._analysis_tasks[analysis_id] = {"future": future, "token": token, "request_id": rid}
        if rid:
            self._analysis_by_request[rid] = analysis_id
        if params.get("await_result"):
            return {"ok": True, **future.result()}
        return {"ok": True, "analysis_id": analysis_id, "accepted": True}

    def _contract_edit(self, service: M3ProjectService, params: dict[str, Any], request: dict[str, Any], *, undo: bool = False, redo: bool = False) -> dict[str, Any]:
        base = params.get("base_edit_version")
        current = int(getattr(service.snapshot, "saved_revision", 0))
        if base is not None and int(base) != current:
            raise M3ProjectError("EDIT_VERSION_CONFLICT", "项目已被其他操作更新，请重新载入后再编辑。", details={"expected": current, "received": int(base)})
        if undo:
            service.undo()
            affected, removed, notes = [], [], ["已撤销上一步编辑"]
        elif redo:
            service.redo()
            affected, removed, notes = [], [], ["已重做上一步编辑"]
        else:
            cmd = dict(params.get("cmd") or {})
            affected, removed, notes = self._apply_edit_command(service, cmd)
        return {
            "ok": True,
            "edit_version": int(getattr(service.snapshot, "saved_revision", 0)),
            "timeline": _timeline(service.snapshot, service.frame_at),
            "history": {"can_undo": bool(service._undo), "can_redo": bool(service._redo), "undo_label": "上一步编辑" if service._undo else None, "redo_label": "下一步编辑" if service._redo else None},
            "affected_clip_ids": affected,
            "removed_clip_ids": removed,
            "notes": notes,
            "outdated_clip_ids": [],
        }

    def _apply_edit_command(self, service: M3ProjectService, cmd: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        kind = str(cmd.get("type", ""))
        before = {item.clip_id for item in service.snapshot.segments}
        if kind == "add_cut":
            service.add_cut(int(cmd["frame"]), needs_review=True)
        elif kind == "move_cut":
            service.move_cut(str(cmd["cut_id"]), int(cmd["frame"]))
        elif kind == "set_clip_bounds":
            service.set_segment_bounds(
                str(cmd["clip_id"]), int(cmd["start_frame"]), int(cmd["end_frame"])
            )
        elif kind == "remove_cut":
            cut = service._cut(str(cmd["cut_id"]))
            segments = sorted(service.snapshot.segments, key=lambda item: item.start_index)
            idx = next((i for i, item in enumerate(segments) if item.end_index == cut.boundary_index), None)
            if idx is None or idx + 1 >= len(segments):
                raise M3ProjectError("CUT_REJECTED", "切点不对应可合并的相邻片段。")
            service.merge_segments(segments[idx].clip_id, segments[idx + 1].clip_id, audio_enabled=(None if cmd.get("audio_resolution") is None else cmd.get("audio_resolution") == "source"))
        elif kind == "merge_clips":
            ids = [str(item) for item in cmd.get("clip_ids", [])]
            if len(ids) < 2:
                raise M3ProjectError("MERGE_NOT_CONTIGUOUS", "至少需要两个相邻片段。")
            resolution = cmd.get("audio_resolution")
            service.merge_segments_many(ids, audio_enabled=(None if resolution is None else resolution == "source"))
        elif kind == "set_clip_props":
            patch = dict(cmd.get("patch") or {})
            service.set_segment_properties_many(
                [str(item) for item in cmd.get("clip_ids", [])],
                audio_enabled=(patch["audio"] == "source") if "audio" in patch else None,
                selected_for_export=bool(patch["export_selected"]) if "export_selected" in patch else None,
                **({"name": patch["name"]} if "name" in patch else {}),
            )
        elif kind == "set_cover":
            service.set_segment_cover(str(cmd["clip_id"]), cmd.get("frame"))
        elif kind == "regenerate_cover":
            service.set_segment_cover(str(cmd["clip_id"]), None)
        elif kind == "review_cut":
            service.mark_cut_checked(str(cmd["cut_id"]), cmd.get("action") == "confirm")
        else:
            raise M3ProjectError("IPC_METHOD_UNKNOWN", f"未知编辑命令：{kind}")
        after = {item.clip_id for item in service.snapshot.segments}
        return sorted(after), sorted(before - after), []

    def _create_contract_batch(self, params: dict[str, Any]) -> dict[str, Any]:
        service = self._ensure_project(str(params.get("project_id") or ""))
        if int(params.get("edit_version", getattr(service.snapshot, "saved_revision", 0))) != int(getattr(service.snapshot, "saved_revision", 0)):
            raise M3ProjectError("EDIT_VERSION_CONFLICT", "导出基于过期编辑版本。")
        clip_ids = {str(item) for item in params.get("clip_ids", [])}
        settings = dict(params.get("settings") or {})
        if not clip_ids:
            raise M3ProjectError("EMPTY_SELECTION", "没有参与导出的片段。")
        selected = [segment for segment in service.snapshot.segments if segment.clip_id in clip_ids and segment.selected_for_export]
        if not selected:
            raise M3ProjectError("EMPTY_SELECTION", "没有参与导出的片段。")
        source = Path(service.snapshot.source_path).resolve()
        if self.queue_store is None or self.runner is None:
            raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
        configured_root = str(settings.get("output_dir") or "").strip()
        legacy_default = (source.parent / "导出").resolve()
        root_value = configured_root or str(self._settings_defaults()["default_output_dir"])
        root_path = Path(root_value).expanduser()
        if not root_path.is_absolute():
            raise M3ProjectError("OUTPUT_DIR_INVALID", "导出目录必须是绝对路径。")
        root = root_path.resolve()
        if root == legacy_default:
            root = Path(str(self._settings_defaults()["default_output_dir"])).resolve()
        try:
            root.relative_to(source.parent)
        except ValueError:
            pass
        if root == source or source in root.parents:
            raise M3ProjectError("OUTPUT_OVERWRITES_SOURCE", "导出目录不能位于源文件路径内。")
        export_intent_key = self._export_intent_key(service, selected, settings, root)
        prior_jobs = [
            job
            for job in self.queue_store.list()
            if (job.snapshot or {}).get("export_intent_key") == export_intent_key
        ]
        if prior_jobs:
            grouped: dict[str, list[Any]] = {}
            for job in prior_jobs:
                prior_batch_id = str((job.snapshot or {}).get("batch_id") or "")
                if prior_batch_id:
                    grouped.setdefault(prior_batch_id, []).append(job)
            complete_groups = [
                (batch_id, jobs)
                for batch_id, jobs in grouped.items()
                if {job.clip_id for job in jobs} >= {segment.clip_id for segment in selected}
            ]
            if complete_groups:
                batch_id, jobs = max(complete_groups, key=lambda item: max(job.created_at for job in item[1]))
                self._batch_meta.setdefault(
                    batch_id,
                    {
                        "project_id": service.snapshot.project_id,
                        "job_ids": [job.job_id for job in jobs],
                        "created_at": min(job.created_at for job in jobs),
                        "seq": 0,
                    },
                )
                output_dir = Path(jobs[0].output_dir or "").resolve()
                snapshot_id = str(self._batch_meta[batch_id].get("snapshot", {}).get("snapshot_id") or f"snapshot:{batch_id}")
                return {
                    "ok": True,
                    "batch_id": batch_id,
                    "snapshot_id": snapshot_id,
                    "output_dir": str(output_dir),
                    "output_root": str(root),
                    "deduplicated": True,
                }
        batch_id = str(uuid.uuid4())
        output_dir = self._new_export_directory(root, Path(service.snapshot.source_path).stem, batch_id)
        snapshot_id = str(uuid.uuid4())
        color_mode = "hdr" if settings.get("color") == "hdr_keep" else "sdr"
        color_override = self._color_override_for_snapshot(service.snapshot)
        temp_dir = output_dir.parent / f".{output_dir.name}.export-tmp"
        name_base = self._safe_export_component(
            str(settings.get("name_base") or Path(service.snapshot.source_path).stem),
            "项目",
        )
        self._mark_export_report_in_progress(output_dir, service.snapshot.project_id)
        jobs = []
        clip_snapshots = []
        for segment in selected:
            job_snapshot = {
                "source_path": service.snapshot.source_path,
                "frame_index_path": service.snapshot.frame_index_path,
                "project_id": service.snapshot.project_id,
                "batch_id": batch_id,
                "export_intent_key": export_intent_key,
                "segment": segment.__dict__.copy(),
                "temp_root": str(temp_dir),
                "output_dir": str(output_dir),
                "color_mode": color_mode,
                "source_color_override": color_override,
            }
            job_snapshot["segment"]["file_stem"] = f"{name_base}_{int(segment.output_number):03d}"
            clip_snapshots.append({
                "clip_id": segment.clip_id,
                "display_index": segment.output_number,
                "start_frame": segment.start_index,
                "end_frame": segment.end_index,
                "audio": "source" if segment.audio_enabled else "muted",
                "cover_frame": segment.cover_frame_index if segment.cover_frame_index is not None else segment.start_index,
                "file_stem": job_snapshot["segment"]["file_stem"],
                "pair_id": segment.clip_id,
            })
            existing = [
                job
                for job in self.queue_store.list()
                if (job.snapshot or {}).get("export_intent_key") == export_intent_key
                and (job.snapshot.get("segment") or {}).get("clip_id") == segment.clip_id
            ] if self.queue_store else []
            jobs.append(existing[0] if existing else self.queue_store.enqueue(clip_id=segment.clip_id, snapshot=job_snapshot, source_identity=service.snapshot.source_identity, temp_dir=str(temp_dir), output_dir=str(output_dir)))
        self._batch_meta[batch_id] = {
            "project_id": service.snapshot.project_id,
            "job_ids": [job.job_id for job in jobs],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "seq": 0,
            "snapshot": {
                "snapshot_id": snapshot_id,
                "project_id": service.snapshot.project_id,
                "edit_version": int(getattr(service.snapshot, "saved_revision", 0)),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "settings": {"output_dir": str(output_dir), "output_root": str(root), "quality": settings.get("quality", "source"), "color": settings.get("color", "sdr_rec709"), "name_base": settings.get("name_base", Path(service.snapshot.source_path).stem)},
                "clips": clip_snapshots,
            },
        }
        self.runner.pump()
        return {"ok": True, "batch_id": batch_id, "snapshot_id": snapshot_id, "output_dir": str(output_dir), "output_root": str(root), "deduplicated": all(job.attempt_count > 0 for job in jobs)}

    def _preview_request_id(self, request: dict[str, Any], params: dict[str, Any]) -> str:
        request_id = str(
            params.get("preview_request_id")
            or params.get("request_id")
            or request.get("id")
            or ""
        ).strip()
        if not request_id:
            raise M3ProjectError("PREVIEW_REQUEST_ID_MISSING", "预览请求缺少可取消的请求 ID。")
        return request_id

    def _write_response(self, response: dict[str, Any], request: dict[str, Any]) -> None:
        if "id" in request:
            response["id"] = request["id"]
        writer = self._output_writer
        if writer is None:
            return
        with self._output_lock:
            writer.write(json.dumps(response, ensure_ascii=False) + "\n")
            writer.flush()

    def _submit_preview(self, request: dict[str, Any], request_logger: Any) -> None:
        params = dict(request.get("params") or {})
        preview_request_id = self._preview_request_id(request, params)
        with self._preview_lock:
            if preview_request_id in self._preview_tasks:
                raise M3ProjectError("PREVIEW_DUPLICATE_REQUEST", "预览请求 ID 已在处理中。")
            generation = self._preview_generation
            token = CancellationToken()
            started = time.perf_counter()
            task: dict[str, Any] = {
                "token": token,
                "generation": generation,
                "started": started,
                "logger": request_logger,
                "request": request,
            }
            future = self._preview_executor.submit(
                self.handle, request, _preview_token=token
            )
            task["future"] = future
            self._preview_tasks[preview_request_id] = task

        def _complete(done: Future) -> None:
            try:
                if done.cancelled():
                    raise M3ProjectError("CANCELLED", "帧预览已取消。")
                response = done.result()
                with self._preview_lock:
                    current_generation = self._preview_generation
                    task_generation = task["generation"]
                if task_generation != current_generation:
                    raise M3ProjectError("PREVIEW_STALE", "预览请求已过期，请重新读取当前项目。")
            except Exception as exc:  # keep the JSONL worker alive
                response = {
                    "ok": False,
                    "error": {
                        "code": getattr(exc, "code", "IPC_ERROR"),
                        "message": str(exc),
                        "details": getattr(exc, "details", {}),
                    },
                }
            self._write_response(response, request)
            if request_logger:
                log_event(
                    request_logger,
                    "ipc.request.end",
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    ok=bool(response.get("ok")),
                )
            with self._preview_lock:
                if self._preview_tasks.get(preview_request_id) is task:
                    self._preview_tasks.pop(preview_request_id, None)

        future.add_done_callback(_complete)

    def _cancel_preview(self, request: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        preview_request_id = self._preview_request_id(request, params)
        with self._preview_lock:
            task = self._preview_tasks.get(preview_request_id)
            if task is None:
                return {
                    "ok": True,
                    "preview_request_id": preview_request_id,
                    "cancel_requested": False,
                    "already_finished": True,
                }
            task["token"].cancel()
            future = task.get("future")
            if isinstance(future, Future):
                future.cancel()
        return {
            "ok": True,
            "preview_request_id": preview_request_id,
            "cancel_requested": True,
        }

    def _handle_contract(
        self,
        request: dict[str, Any],
        method: str,
        params: dict[str, Any],
        *,
        preview_token: CancellationToken | None = None,
    ) -> dict[str, Any] | None:
        if method == "connect":
            return {"ok": True, "connection": self._contract_connection()}
        if method == "projects.listRecent":
            result = []
            for project_id in list(self._recent_projects):
                path = self._project_registry.get(project_id)
                if not path or not Path(path).is_file():
                    continue
                try:
                    service = M3ProjectService.open_project(path, verify_source=False)
                    try:
                        p = contract_project(service.snapshot, service)
                        result.append({"project_id": p["project_id"], "name": p["name"], "updated_at": datetime.now(timezone.utc).isoformat(), "status": "needs_review" if service.pending_reviews() else "ready_to_export", "clip_count": len(p["timeline"]["clips"]), "pending_review": len(service.pending_reviews()), "source_name": Path(service.snapshot.source_path).name, "thumb_key": None, "orientation": "portrait" if (p["media"]["video_streams"] and p["media"]["video_streams"][0]["height"] > p["media"]["video_streams"][0]["width"]) else "landscape"})
                    finally:
                        service.close()
                except Exception:
                    continue
            return {"ok": True, "projects": result}
        if method == "projects.open":
            project_id = str(params.get("project_id") or "")
            service = self._ensure_project(project_id)
            project = contract_project(service.snapshot, service)
            defaults = self._settings_defaults()
            project["export_settings"].update({
                "output_dir": str(defaults["default_output_dir"]),
                "quality": str(defaults["default_quality"]),
                "color": str(defaults["default_color"]),
            })
            return {"ok": True, "result": {"project": project, "warnings": []}}
        if method == "projects.pickProjectFile":
            # The main process may return a path for the native dialog.  It is
            # intentionally treated as a project id by the next open call.
            return {"ok": True, "project_id": params.get("project_path")}
        if method == "projects.rename":
            raise AdapterContractError("PROJECT_RENAME_UNSUPPORTED", "当前 M3 项目格式未持久化自定义项目名称。")
        if method == "projects.removeRecent":
            project_id = str(params.get("project_id") or "")
            self._recent_projects = [item for item in self._recent_projects if item != project_id]
            self._persist_recent_projects()
            return {"ok": True}
        if method == "projects.save":
            service = self._ensure_project(str(params.get("project_id") or ""))
            version = int(params.get("edit_version", getattr(service.snapshot, "saved_revision", 0)))
            current = int(getattr(service.snapshot, "saved_revision", 0))
            if version > current:
                raise M3ProjectError("SAVE_VERSION_UNKNOWN", "保存版本尚未由后端产生。")
            return {"ok": True, "saved_edit_version": current}
        if method == "projects.relocateSource":
            service = self._ensure_project(str(params.get("project_id") or ""))
            candidate = dict(params.get("candidate") or {})
            source_path = str(candidate.get("source_path") or candidate.get("display_path") or "")
            if not source_path:
                raise M3ProjectError("SOURCE_MISSING", "未提供可核验的候选源文件。")
            current = capture_identity(source_path)
            stored = service.snapshot.source_identity
            accepted = identities_match(service.snapshot.source_identity, current)
            if accepted:
                service.snapshot.source_path = str(Path(source_path).resolve())
                service.snapshot.source_identity = {"canonical_path": current.canonical_path, "physical_file_id": current.physical_file_id, "size": current.size, "mtime_ns": current.mtime_ns, "sampled_fingerprint": current.sampled_fingerprint, "full_sha256": current.full_sha256, "captured_at_utc": current.captured_at_utc}
                service.store.save(service.snapshot)
            mismatch = [] if accepted else ["identity_mismatch"]
            return {"ok": True, "accepted": accepted, "identity": source_identity(service.snapshot), "mismatch": mismatch}
        if method == "media.probe":
            source_path = self._resolve_media_path(params)
            result = probe_media(source_path, allow_ambiguous=True)
            raw = result.to_dict()
            pseudo = SimpleNamespace(probe=raw, frame_count=0, source_identity={})
            probe_media_info = media_info(pseudo)
            needs_stream_choice = result.selected_video_reason == "ambiguous_unselected"
            return {"ok": True, "probe": {"file": params.get("file"), "media": probe_media_info, "notes": [{"code": "AMBIGUOUS_VIDEO_STREAM" if needs_stream_choice else item, "message": item} for item in raw.get("diagnostics", [])], "needs_stream_choice": needs_stream_choice}}
        if method == "analysis.start":
            return self._start_analysis(request, params)
        if method == "analysis.result":
            analysis_id = str(params.get("analysis_id") or "")
            task = self._analysis_tasks.get(analysis_id)
            if task is None:
                raise M3ProjectError("ANALYSIS_NOT_FOUND", "分析任务不存在。")
            result = task["future"].result()
            return {"ok": True, **result}
        if method == "analysis.cancel":
            analysis_id = str(params.get("analysis_id") or "")
            task = self._analysis_tasks.get(analysis_id)
            if task is None:
                raise M3ProjectError("ANALYSIS_NOT_FOUND", "分析任务不存在。")
            task["token"].cancel()
            return {"ok": True, "analysis_id": analysis_id, "cancel_requested": True}
        if method == "analysis.reanalyze":
            raise AdapterContractError("REANALYZE_UNSUPPORTED", "当前项目服务没有在不覆盖人工编辑的情况下重建分析版本的入口。")
        if method == "preview.getSource":
            service = self._ensure_project(str(params.get("project_id") or ""))
            video = (media_info(service.snapshot).get("video_streams") or [{}])[0]
            audio = bool(media_info(service.snapshot).get("audio_streams"))
            return {"ok": True, "source": {"url": None, "kind": "none", "width": int(video.get("width", 0)), "height": int(video.get("height", 0)), "has_audio": audio, "note": None, "_source_path": service.snapshot.source_path}}
        if method == "preview.cancel":
            return self._cancel_preview(request, params)
        if method == "preview.getFrame":
            active_jobs = tuple(self.runner.running_job_ids) if self.runner else ()
            if active_jobs:
                raise M3ProjectError(
                    "PREVIEW_BUSY",
                    "导出期间暂停帧预览解码，导出完成后会自动恢复。",
                    details={"active_job_count": len(active_jobs), "retry_after_ms": 1000},
                )
            project_id = str(params.get("project_id") or "")
            if preview_token is not None:
                if preview_token.cancelled:
                    raise M3ProjectError("CANCELLED", "帧预览已取消。")
                service = self.service
                if service is None or service.snapshot.project_id != project_id:
                    raise M3ProjectError("PREVIEW_STALE", "当前项目已切换，请重新读取预览。")
            else:
                service = self._ensure_project(project_id)
            index = int(params.get("frame", 0))
            preview = service.preview_frame(index, width=320 if params.get("size") == "thumb" else 960, token=preview_token)
            return {"ok": True, "frame": {"url": preview["data_uri"], "frame": index, "exact": True, "note": None, "pts": str(preview["pts"])}}
        if method == "preview.releaseFrame":
            return {"ok": True}
        if method in {"timeline.apply", "timeline.undo", "timeline.redo"}:
            service = self._ensure_project(str(params.get("project_id") or ""))
            return self._contract_edit(service, params, request, undo=method.endswith("undo"), redo=method.endswith("redo"))
        if method == "export.preflight":
            service = self._ensure_project(str(params.get("project_id") or ""))
            configured_root = str((params.get("settings") or {}).get("output_dir") or "").strip()
            output_dir = Path(configured_root or str(self._settings_defaults()["default_output_dir"])).resolve()
            free = shutil.disk_usage(output_dir.parent if output_dir.parent.exists() else service.store.path.parent).free
            issues = []
            selected_stream = next(
                (
                    stream
                    for stream in (service.snapshot.probe.get("streams") or [])
                    if int(stream.get("index", -1)) == int(service.snapshot.probe.get("selected_video_stream", -2))
                    and stream.get("codec_type") == "video"
                ),
                None,
            )
            source_color = (selected_stream or {}).get("color") or {}
            if not service.snapshot.color_override and (
                source_color.get("transfer") in {None, "", "unknown"}
                or source_color.get("primaries") in {None, "", "unknown"}
            ):
                issues.append({"level": "error", "code": "COLOR_SELECTION_REQUIRED", "message": "项目导入时未确认源视频色彩。请重新导入，并在导入阶段选择 SDR / Rec.709、HDR10 / PQ 或 HDR / HLG。", "action": None})
            if service.pending_reviews():
                issues.append({"level": "warning", "code": "PENDING_REVIEW", "message": "仍有待审核切点。", "action": "review"})
            return {"ok": True, "preflight": {"ok": not any(item["level"] == "error" for item in issues), "issues": issues, "free_space_bytes": str(free), "estimated_bytes": None, "existing_outputs": {"count": len(list(output_dir.glob("*"))) if output_dir.is_dir() else 0, "externally_modified": 0, "locked": 0}, "sample_names": {"mp4": "clip.mp4", "livp": "clip.livp"}}}
        if method == "export.createBatch":
            return self._create_contract_batch(params)
        if method == "tasks.subscribe":
            project_id = str(params.get("project_id") or "")
            self._subscriptions.add(project_id)
            for batch_id, meta in self._batch_meta.items():
                if meta.get("project_id") == project_id:
                    batch = self._contract_batch(batch_id, project_id)
                    self._task_snapshots[batch_id] = deepcopy(batch)
                    self._emit("v2lp:tasks:event", {"type": "batch_snapshot", "project_id": project_id, "batch": batch})
            return {"ok": True}
        if method == "tasks.unsubscribe":
            self._subscriptions.discard(str(params.get("project_id") or ""))
            return {"ok": True}
        if method == "tasks.getBatch":
            return {"ok": True, "batch": self._contract_batch(str(params.get("batch_id") or ""))}
        if method == "tasks.listBatches":
            project_id = str(params.get("project_id") or "")
            return {"ok": True, "batches": [self._contract_batch(batch_id, project_id) for batch_id, meta in self._batch_meta.items() if meta.get("project_id") == project_id]}
        if method in {"tasks.pauseQueue", "tasks.resumeQueue"}:
            if self.runner is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            if method.endswith("pauseQueue"):
                self.runner.pause()
            else:
                self.runner.resume()
            return {"ok": True}
        if method == "tasks.cancelJob":
            if self.runner is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            job = self.queue_store.get(str(params.get("job_id"))) if self.queue_store else None
            immediate = bool(job and job.state == QueueState.PENDING)
            self.runner.cancel(str(params.get("job_id")))
            return {"ok": True, "immediate": immediate, "wait_reason": None if immediate else "当前编码阶段结束后确认取消。"}
        if method == "tasks.stopBatch":
            if self.runner is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            meta = self._batch_meta.get(str(params.get("batch_id")))
            for job_id in (meta or {}).get("job_ids", []):
                self.runner.cancel(job_id)
            return {"ok": True}
        if method == "tasks.retryFailed":
            if self.queue_store is None or self.runner is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            meta = self._batch_meta.get(str(params.get("batch_id")))
            ids = set(str(item) for item in params.get("job_ids", [])) or set((meta or {}).get("job_ids", []))
            retried = 0
            for job_id in ids:
                job = self.queue_store.get(job_id)
                if job.state == QueueState.FAILED:
                    self.queue_store.retry(job_id)
                    retried += 1
            self.runner.pump()
            return {"ok": True, "retried": retried}
        if method == "recovery.inspect":
            service = self._ensure_project(str(params.get("project_id") or ""))
            jobs = [job for job in (self.queue_store.list() if self.queue_store else []) if (job.snapshot or {}).get("project_id") == service.snapshot.project_id and job.state == QueueState.INTERRUPTED]
            batch_id = next(
                (
                    batch
                    for batch, meta in self._batch_meta.items()
                    if meta.get("project_id") == service.snapshot.project_id
                    and any(job.job_id in set(meta.get("job_ids") or []) for job in jobs)
                ),
                None,
            )
            for index, job in enumerate(jobs, 1):
                self._emit("v2lp:recovery:progress", {"project_id": service.snapshot.project_id, "checked": index, "total": len(jobs), "current": job.job_id})
            return {"ok": True, "summary": {"project_id": service.snapshot.project_id, "batch_id": batch_id, "interrupted_at": datetime.now(timezone.utc).isoformat(), "verified_success": [], "needs_redo": [{"clip_id": job.clip_id, "display_index": int((job.snapshot.get("segment") or {}).get("output_number", 0)), "reason": job.error_message or "任务中断"} for job in jobs], "reusable_intermediate": [], "needs_relocate": [], "commit_unknown": [], "pending_actions": ["用户确认后继续剩余任务"] if jobs else []}}
        if method in {"recovery.continueRemaining", "recovery.dismiss"}:
            if method.endswith("dismiss"):
                return {"ok": True}
            project_id = str(params.get("project_id") or "")
            self._ensure_project(project_id)
            batches = [batch_id for batch_id, meta in self._batch_meta.items() if meta.get("project_id") == project_id]
            if not batches:
                raise M3ProjectError("NOTHING_TO_CONTINUE", "没有待恢复的任务。")
            for job in self.queue_store.list() if self.queue_store else []:
                if (job.snapshot or {}).get("project_id") == project_id and job.state == QueueState.INTERRUPTED:
                    self.queue_store.confirm_recovery([job.job_id])
            self.runner.pump() if self.runner else None
            return {"ok": True, "batch_id": batches[0]}
        if method == "files.readReport":
            if self.queue_store is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            job = self.queue_store.get(str(params.get("job_id")))
            report = Path(job.output_dir or "") / "导出报告.json"
            if not report.is_file():
                self._write_export_report(
                    str((job.snapshot or {}).get("batch_id") or f"legacy:{(job.snapshot or {}).get('project_id', '')}")
                )
            if not report.is_file():
                raise M3ProjectError("REPORT_NOT_FOUND", "导出报告尚未生成。")
            return {"ok": True, "body": report.read_text(encoding="utf-8")}
        if method == "files.openArtifact":
            job = self._get_queue_job(str(params.get("job_id") or ""))
            kind = str(params.get("kind") or "").lower()
            return {"ok": True, "path": str(self._committed_artifact_path(job, kind))}
        if method == "files.revealOutput":
            return {"ok": True, "path": str(self._output_directory_for_request(params))}
        if method == "files.pickOutputDir":
            raise AdapterContractError("FILE_ACTION_REQUIRES_ELECTRON", "文件打开与目录选择必须由 Electron 主进程执行。")
        if method == "settings.get":
            return {"ok": True, "settings": self._settings_defaults()}
        if method == "settings.update":
            current = self._handle_contract({"id": request.get("id")}, "settings.get", {})["settings"]
            current.update(dict(params.get("patch") or params))
            self._settings_path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
            return {"ok": True, "settings": current}
        if method == "settings.cacheInfo":
            return {"ok": True, "cache": {"items": []}}
        if method == "settings.clearCache":
            raise AdapterContractError("CACHE_CLEAR_UNSUPPORTED", "当前版本没有可安全枚举的缓存条目。")
        if method == "diagnostics.info":
            return {"ok": True, "diagnostics": {"app_version": os.environ.get("VIDEO2LIVEPHOTO_APP_VERSION", "1.0.0-candidate"), "backend_version": "m3-python+queue.v1", "ui_build": "desktop", "mode": "desktop", "capabilities": self._contract_connection()["capabilities"], "recent_errors": [], "workers": [{"name": "python-ipc", "status": "running"}]}}
        if method == "diagnostics.logs":
            return {"ok": True, "logs": []}
        if method == "diagnostics.exportBundle":
            raise AdapterContractError("DIAGNOSTICS_EXPORT_UNSUPPORTED", "诊断包导出需要 Electron 日志目录适配。")
        if method == "app.quit":
            return {"ok": True}
        return None

    def run(self) -> int:
        self._output_writer = sys.stdout
        for line in sys.stdin:
            if not line.strip():
                continue
            request: dict[str, Any] = {}
            started = time.perf_counter()
            request_id = ""
            method = ""
            request_logger = self.logger
            try:
                request = json.loads(line)
                request_id = str(request.get("id", ""))
                method = str(request.get("method", ""))
                if self.logger:
                    request_logger = self.logger.bind(request_id=request_id or None, method=method)
                    log_event(request_logger, "ipc.request.start", params=dict(request.get("params") or {}))
                if method == "preview.getFrame":
                    self._submit_preview(request, request_logger)
                    # The worker callback writes the response after ffmpeg
                    # exits.  Continuing here keeps the JSONL reader free to
                    # accept preview.cancel and all unrelated IPC requests.
                    continue
                response = self.handle(request)
            except Exception as exc:  # keep the worker alive for the next request
                if request_logger:
                    log_event(
                        request_logger,
                        "ipc.request.error",
                        level=40,
                        error_code=getattr(exc, "code", "IPC_ERROR"),
                        error_message=str(exc),
                    )
                response = {
                    "ok": False,
                    "error": {
                        "code": getattr(exc, "code", "IPC_ERROR"),
                        "message": str(exc),
                        "details": getattr(exc, "details", {}),
                    },
                }
            if "id" in request:
                response["id"] = request["id"]
            with self._output_lock:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            if request_logger:
                log_event(
                    request_logger,
                    "ipc.request.end",
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    ok=bool(response.get("ok")),
                )
        self._close_project()
        self._preview_executor.shutdown(wait=True, cancel_futures=True)
        self._analysis_executor.shutdown(wait=False, cancel_futures=False)
        return 0

    def handle(
        self,
        request: dict[str, Any],
        *,
        _preview_token: CancellationToken | None = None,
    ) -> dict[str, Any]:
        if request.get("protocol", self.PROTOCOL) != self.PROTOCOL:
            raise M3ProjectError("IPC_VERSION_UNSUPPORTED", "IPC 协议版本不受支持。")
        method = str(request.get("method", ""))
        params = dict(request.get("params") or {})
        request_key = self._request_key(request, method, params)
        if request_key and request_key in self._request_results:
            return deepcopy(self._request_results[request_key])
        if method == "ping":
            return {"ok": True, "protocol": self.PROTOCOL, "service": "m3-python"}
        contract_result = self._handle_contract(
            request, method, params, preview_token=_preview_token
        )
        if contract_result is not None:
            if request_key:
                self._remember_result(request_key, contract_result)
            return contract_result
        if method == "import":
            if self.logger:
                log_event(self.logger.bind(request_id=str(request.get("id", "")), method=method), "project.import.start", source_path=params.get("source_path"), project_path=params.get("project_path"))
            self._close_project()
            self.service = M3ProjectService.import_media(
                params["source_path"],
                project_path=params["project_path"],
                cache_root=params.get("cache_root"),
                color_override=(str(params.get("color_override") or "").strip() or None),
            )
            self._configure_queue(params["project_path"])
            self._remember_project(self.service.snapshot.project_id, params["project_path"])
            return {"ok": True, "project": self.service.to_dict()}
        if method == "open":
            if self.logger:
                log_event(self.logger.bind(request_id=str(request.get("id", "")), method=method), "project.open.start", project_path=params.get("project_path"))
            self._close_project()
            self.service = M3ProjectService.open_project(params["project_path"])
            self._configure_queue(params["project_path"])
            self._remember_project(self.service.snapshot.project_id, params["project_path"])
            return {"ok": True, "project": self.service.to_dict()}
        if self.service is None:
            raise M3ProjectError("PROJECT_NOT_OPEN", "请先导入或打开项目。")
        if method == "state":
            return {"ok": True, "project": self.service.to_dict()}
        if method == "frame_window":
            frames = self.service.frame_window(
                int(params["center_index"]), int(params.get("radius", 3))
            )
            return {"ok": True, "frames": [frame.__dict__ for frame in frames]}
        if method == "preview_frame":
            return {
                "ok": True,
                "preview": self.service.preview_frame(
                    int(params["display_index"]),
                    width=int(params.get("width", 640)),
                ),
            }
        if method == "add_cut":
            self.service.add_cut(
                int(params["boundary_index"]),
                needs_review=bool(params.get("needs_review", True)),
            )
        elif method == "move_cut":
            self.service.move_cut(str(params["cut_id"]), int(params["boundary_index"]))
        elif method == "delete_cut":
            self.service.delete_cut(str(params["cut_id"]))
        elif method == "merge_segments":
            self.service.merge_segments(
                str(params["left_clip_id"]),
                str(params["right_clip_id"]),
                audio_enabled=params.get("audio_enabled"),
            )
        elif method == "set_segment_audio":
            self.service.set_segment_audio(
                str(params["clip_id"]), bool(params["enabled"])
            )
        elif method == "set_all_audio":
            self.service.set_all_audio(bool(params["enabled"]))
        elif method == "mark_cut_checked":
            self.service.mark_cut_checked(
                str(params["cut_id"]), bool(params.get("checked", True))
            )
        elif method == "undo":
            self.service.undo()
        elif method == "redo":
            self.service.redo()
        elif method == "confirm_export":
            return {
                "ok": True,
                "export": self.service.confirm_export(
                    allow_unreviewed=bool(params.get("allow_unreviewed", False))
                ),
            }
        elif method == "start_export":
            if (
                self.queue_store is None
                or self.runner is None
                or self.project_path is None
            ):
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            confirmation = self.service.confirm_export(
                allow_unreviewed=bool(params.get("allow_unreviewed", False))
            )
            project = confirmation["project"]
            output_dir = Path(
                params.get("output_dir") or self.project_path.parent / "导出"
            )
            self._mark_export_report_in_progress(
                output_dir, str(project.get("project_id"))
            )
            temp_dir = output_dir.resolve().parent / f".{output_dir.name}.export-tmp"
            jobs = []
            for segment in project["segments"]:
                if not segment.get("selected_for_export", True):
                    continue
                job_snapshot = {
                    "source_path": project["source_path"],
                    "frame_index_path": project["frame_index_path"],
                    "project_id": project["project_id"],
                    "segment": segment,
                    "temp_root": str(temp_dir),
                    "output_dir": str(output_dir),
                    "color_mode": params.get("color_mode", "warn"),
                    "source_color_override": self._color_override_for_snapshot(self.service.snapshot),
                }
                snapshot_hash = compute_snapshot_hash(job_snapshot)
                existing = self.queue_store.find_by_snapshot_hash(snapshot_hash)
                if existing:
                    # The same immutable snapshot may be submitted repeatedly
                    # from a double click or a renderer retry.  Return the
                    # durable job instead of creating competing workers.
                    jobs.append(existing[0])
                    continue
                jobs.append(
                    self.queue_store.enqueue(
                        clip_id=str(segment["clip_id"]),
                        snapshot=job_snapshot,
                        source_identity=project.get("source_identity"),
                        temp_dir=str(temp_dir),
                        output_dir=str(output_dir),
                    )
                )
            self.runner.pump()
            if self.logger:
                log_event(self.logger.bind(request_id=str(request.get("id", "")), method=method), "export.batch.submitted", project_id=project.get("project_id"), output_dir=str(output_dir), job_count=len(jobs), color_mode=params.get("color_mode", "warn"))
            return {
                "ok": True,
                "export": confirmation,
                "jobs": [self._job_dict(job) for job in jobs],
            }
        elif method == "export_status":
            if self.queue_store is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            report_path = self._write_export_report()
            return {
                "ok": True,
                "jobs": [self._job_dict(job) for job in self.queue_store.list()],
                "worker_limit": self.runner.worker_limit if self.runner else 0,
                "report_path": report_path,
            }
        elif method == "pause_export":
            if self.runner is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            self.runner.pause()
            return {"ok": True}
        elif method == "resume_export":
            if self.runner is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            self.runner.resume()
            return {"ok": True}
        elif method == "confirm_recovery":
            if self.queue_store is None or self.runner is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            requested = [str(item) for item in params.get("job_ids", [])]
            if self.logger:
                log_event(self.logger.bind(request_id=str(request.get("id", "")), method=method), "queue.recovery.request", job_ids=requested)
            if not requested:
                requested = [
                    job.job_id
                    for job in self.queue_store.list(states=[QueueState.INTERRUPTED])
                    if job.user_confirmation_required
                ]
            transaction_states: dict[str, str] = {}
            for job_id in requested:
                job = self.queue_store.get(job_id)
                if job.state != QueueState.INTERRUPTED:
                    raise M3ProjectError(
                        "RECOVERY_NOT_REQUIRED", f"任务 {job_id} 当前不需要恢复确认。"
                    )
                manifest = (
                    Path(job.temp_dir or "")
                    / (job.transaction_id or job.job_id)
                    / "transaction.json"
                )
                if manifest.is_file():
                    try:
                        transaction_states[job_id] = recover_transaction(manifest)
                    except CommitError as exc:
                        raise M3ProjectError(
                            "RECOVERY_FAILED",
                            str(exc),
                            details={"job_id": job_id, "code": exc.code},
                        ) from exc
            recovered = self.queue_store.confirm_recovery(requested)
            self.runner.pump()
            if self.logger:
                log_event(self.logger.bind(request_id=str(request.get("id", "")), method=method), "queue.recovery.confirmed", job_ids=requested, transaction_states=transaction_states)
            return {
                "ok": True,
                "transactions": transaction_states,
                "jobs": [self._job_dict(job) for job in recovered],
            }
        elif method == "cancel_export":
            if self.runner is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            self.runner.cancel(str(params["job_id"]))
            return {"ok": True}
        elif method == "retry_export":
            if self.queue_store is None or self.runner is None:
                raise M3ProjectError("QUEUE_NOT_READY", "导出队列尚未初始化。")
            job = self.queue_store.get(str(params["job_id"]))
            if job.state != QueueState.FAILED:
                raise M3ProjectError(
                    "RETRY_NOT_AVAILABLE", "只有失败任务可以从界面重试；中断任务请先确认恢复。"
                )
            retried = self.queue_store.retry(job.job_id)
            self._mark_export_report_in_progress(
                Path(job.output_dir).resolve()
                if job.output_dir
                else self.project_path.parent / "导出",
                str(job.snapshot.get("project_id")),
            )
            self.runner.pump()
            return {"ok": True, "job": self._job_dict(retried)}
        else:
            raise M3ProjectError("IPC_METHOD_UNKNOWN", f"未知 IPC 方法：{method}")
        return {"ok": True, "project": self.service.to_dict()}


def _configure_utf8_stdio() -> None:
    """Keep JSONL IPC UTF-8 on Windows where the console default is often GBK."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _configure_utf8_stdio()
    logger = configure_logging("python-ipc", file_name="python.jsonl")
    install_uncaught_exception_logging(logger)
    return JsonlIpcServer(logger=logger).run()


if __name__ == "__main__":
    raise SystemExit(main())
