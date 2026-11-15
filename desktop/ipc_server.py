from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.commit.transaction import CommitError, recover_transaction
from core.queue import QueueRunner, QueueState, QueueStore, compute_snapshot_hash

from .export_pipeline import export_queue_job
from .models import M3ProjectError
from .service import M3ProjectService


class JsonlIpcServer:
    """Versioned JSONL bridge for Electron main/preload.

    One request per line and one response per line keeps the bridge usable in
    a frozen Python worker and easy to diagnose from a Windows log file.
    """

    PROTOCOL = "m3.ipc.v1"

    def __init__(self) -> None:
        self.service: M3ProjectService | None = None
        self.project_path: Path | None = None
        self.queue_store: QueueStore | None = None
        self.runner: QueueRunner | None = None

    def _close_project(self) -> None:
        if self.runner is not None:
            self.runner.close(cancel_running=True)
            self.runner = None
        self.queue_store = None
        if self.service is not None:
            self.service.close()
            self.service = None

    def _configure_queue(self, project_path: str | Path) -> None:
        self.project_path = Path(project_path).resolve()
        self.queue_store = QueueStore(self.project_path.with_suffix(".queue.sqlite3"))
        self.queue_store.mark_interrupted_for_restart()
        assert self.service is not None

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
        )

    @staticmethod
    def _job_dict(job) -> dict[str, Any]:
        payload = dict(job.__dict__)
        payload["state"] = job.state.value
        return payload

    def _write_export_report(self) -> str | None:
        """Write a batch report only after every queued job reaches a terminal state."""
        if self.queue_store is None:
            return None
        jobs = self.queue_store.list()
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

    def run(self) -> int:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                response = self.handle(request)
            except Exception as exc:  # keep the worker alive for the next request
                response = {
                    "ok": False,
                    "error": {
                        "code": getattr(exc, "code", "IPC_ERROR"),
                        "message": str(exc),
                        "details": getattr(exc, "details", {}),
                    },
                }
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        self._close_project()
        return 0

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        if request.get("protocol", self.PROTOCOL) != self.PROTOCOL:
            raise M3ProjectError("IPC_VERSION_UNSUPPORTED", "IPC 协议版本不受支持。")
        method = str(request.get("method", ""))
        params = dict(request.get("params") or {})
        if method == "ping":
            return {"ok": True, "protocol": self.PROTOCOL, "service": "m3-python"}
        if method == "import":
            self._close_project()
            self.service = M3ProjectService.import_media(
                params["source_path"],
                project_path=params["project_path"],
                cache_root=params.get("cache_root"),
            )
            self._configure_queue(params["project_path"])
            return {"ok": True, "project": self.service.to_dict()}
        if method == "open":
            self._close_project()
            self.service = M3ProjectService.open_project(params["project_path"])
            self._configure_queue(params["project_path"])
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
            temp_dir = (
                self.project_path.parent / f".{self.project_path.stem}.export-tmp"
            )
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
            self.runner.pump()
            return {"ok": True, "job": self._job_dict(retried)}
        else:
            raise M3ProjectError("IPC_METHOD_UNKNOWN", f"未知 IPC 方法：{method}")
        return {"ok": True, "project": self.service.to_dict()}


def main() -> int:
    return JsonlIpcServer().run()


if __name__ == "__main__":
    raise SystemExit(main())
