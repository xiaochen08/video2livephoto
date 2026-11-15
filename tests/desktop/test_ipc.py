from __future__ import annotations

import io
import json
import pytest
import sys
import threading
import time
from pathlib import Path

from core.media.toolchain import Toolchain
from core.media.process import CancellationToken
from desktop.models import M3ProjectError
from desktop.ipc_server import JsonlIpcServer, _configure_utf8_stdio


def test_ipc_stdio_is_configured_as_utf8(monkeypatch) -> None:
    calls: list[dict[str, str]] = []

    class Stream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(sys, "stdin", Stream())
    monkeypatch.setattr(sys, "stdout", Stream())
    monkeypatch.setattr(sys, "stderr", Stream())
    _configure_utf8_stdio()
    assert calls == [{"encoding": "utf-8", "errors": "replace"}] * 3


def test_ipc_run_echoes_request_id(monkeypatch) -> None:
    stdin = io.StringIO(
        '{"id":"renderer-1","protocol":"m3.ipc.v1","method":"ping"}\n'
    )
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    assert JsonlIpcServer().run() == 0
    response = json.loads(stdout.getvalue())
    assert response["id"] == "renderer-1"
    assert response["ok"] is True


def test_ipc_preview_cancel_is_read_while_decode_is_running(monkeypatch) -> None:
    stdin = io.StringIO(
        json.dumps(
            {
                "id": "preview-transport",
                "protocol": "m3.ipc.v1",
                "method": "preview.getFrame",
                "params": {
                    "preview_request_id": "preview-cancel-test",
                    "project_id": "project",
                    "frame": 0,
                    "size": "thumb",
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "id": "cancel-transport",
                "protocol": "m3.ipc.v1",
                "method": "preview.cancel",
                "params": {"preview_request_id": "preview-cancel-test"},
            }
        )
        + "\n"
    )
    stdout = io.StringIO()
    started = threading.Event()

    class FakeService:
        snapshot = type("Snapshot", (), {"project_id": "project"})()

        def preview_frame(self, _index, *, width, token):
            assert width == 320
            started.set()
            while not token.cancelled:
                time.sleep(0.01)
            raise M3ProjectError("CANCELLED", "帧预览已取消。")

        def close(self):
            return None

    server = JsonlIpcServer()
    server.service = FakeService()
    monkeypatch.setattr(server, "_ensure_project", lambda _project_id, **_kwargs: server.service)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    assert server.run() == 0
    assert started.is_set()
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    cancelled = next(item for item in responses if item.get("id") == "cancel-transport")
    preview = next(item for item in responses if item.get("id") == "preview-transport")
    assert cancelled["ok"] is True
    assert cancelled["cancel_requested"] is True
    assert preview["ok"] is False
    assert preview["error"]["code"] == "CANCELLED"


def test_ipc_preview_executor_is_hard_limited_to_two_workers(monkeypatch) -> None:
    stdin = io.StringIO()
    stdout = io.StringIO()
    lock = threading.Lock()
    started = threading.Event()
    release = threading.Event()
    active = 0
    maximum = 0

    class FakeService:
        snapshot = type("Snapshot", (), {"project_id": "project"})()

        def preview_frame(self, index, *, width, token):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                if active == 2:
                    started.set()
            release.wait(timeout=2)
            with lock:
                active -= 1
            return {"data_uri": f"data:image/jpeg;base64,{index}", "pts": index}

        def close(self):
            return None

    server = JsonlIpcServer()
    server.service = FakeService()
    monkeypatch.setattr(server, "_ensure_project", lambda _project_id, **_kwargs: server.service)
    server._output_writer = stdout
    requests = [
        {
            "id": f"transport-{index}",
            "protocol": "m3.ipc.v1",
            "method": "preview.getFrame",
            "params": {
                "preview_request_id": f"preview-{index}",
                "project_id": "project",
                "frame": index,
                "size": "thumb",
            },
        }
        for index in range(3)
    ]
    for request in requests:
        server._submit_preview(request, None)
    assert started.wait(timeout=2)
    with lock:
        assert maximum == 2
    release.set()
    deadline = time.monotonic() + 3
    while len(stdout.getvalue().splitlines()) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(stdout.getvalue().splitlines()) == 3
    server._close_project()
    server._preview_executor.shutdown(wait=True, cancel_futures=True)


def test_async_preview_cannot_reopen_a_project_after_switch() -> None:
    called = False

    class CurrentService:
        snapshot = type("Snapshot", (), {"project_id": "project-p2"})()

        def preview_frame(self, _index, *, width, token):
            nonlocal called
            called = True
            raise AssertionError("stale preview must not decode against the current project")

    server = JsonlIpcServer()
    server.service = CurrentService()
    request = {
        "id": "preview-old-project",
        "protocol": "m3.ipc.v1",
        "method": "preview.getFrame",
        "params": {
            "preview_request_id": "preview-old-project",
            "project_id": "project-p1",
            "frame": 1,
            "size": "thumb",
        },
    }
    with pytest.raises(M3ProjectError) as exc:
        server.handle(request, _preview_token=CancellationToken())
    assert exc.value.code == "PREVIEW_STALE"
    assert called is False
    server._preview_executor.shutdown(wait=True, cancel_futures=True)


def test_ipc_protocol_ping_and_real_import(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch
) -> None:
    server = JsonlIpcServer()
    assert server.handle({"protocol": "m3.ipc.v1", "method": "ping"})["ok"] is True
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    result = server.handle(
        {
            "protocol": "m3.ipc.v1",
            "method": "import",
            "params": {
                "source_path": str(small_mp4),
                "project_path": str(tmp_path / "ipc-project.sqlite3"),
                "cache_root": str(tmp_path / "cache"),
            },
        }
    )
    assert result["ok"] is True
    assert result["project"]["frame_count"] >= 20
    server.handle({"protocol": "m3.ipc.v1", "method": "state"})
    server._close_project()


def test_ipc_start_export_runs_queue_and_publishes_outputs(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch
) -> None:
    server = JsonlIpcServer()
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server.handle(
        {
            "protocol": "m3.ipc.v1",
            "method": "import",
            "params": {
                "source_path": str(small_mp4),
                "project_path": str(tmp_path / "ipc-export.sqlite3"),
                "cache_root": str(tmp_path / "cache"),
            },
        }
    )
    started = server.handle(
        {
            "protocol": "m3.ipc.v1",
            "method": "start_export",
            "params": {"allow_unreviewed": True, "output_dir": str(tmp_path / "out")},
        }
    )
    assert started["jobs"]
    repeated = server.handle(
        {
            "protocol": "m3.ipc.v1",
            "method": "start_export",
            "params": {"allow_unreviewed": True, "output_dir": str(tmp_path / "out")},
        }
    )
    assert [job["job_id"] for job in repeated["jobs"]] == [
        job["job_id"] for job in started["jobs"]
    ]
    for _ in range(100):
        status = server.handle({"protocol": "m3.ipc.v1", "method": "export_status"})
        if all(job["state"] == "succeeded" for job in status["jobs"]):
            break
        time.sleep(0.05)
    else:
        raise AssertionError(status)
    assert list((tmp_path / "out" / "视频片段").glob("*.mp4"))
    assert list((tmp_path / "out" / "LivePhoto").glob("*.JPG"))
    assert status["report_path"] == str(tmp_path / "out" / "导出报告.json")
    assert (tmp_path / "out" / "导出报告.json").is_file()
    assert json.loads((tmp_path / "out" / "导出报告.json").read_text(encoding="utf-8"))["status"] == "complete"
    manifests = list((tmp_path / "out" / "LivePhoto").glob("*.manifest.json"))
    assert manifests
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert Path(manifest["jpg_path"]).is_file()
        assert Path(manifest["mov_path"]).is_file()
    server._close_project()


def test_ipc_recovery_requires_explicit_confirmation(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch
) -> None:
    server = JsonlIpcServer()
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server.handle(
        {
            "protocol": "m3.ipc.v1",
            "method": "import",
            "params": {
                "source_path": str(small_mp4),
                "project_path": str(tmp_path / "ipc-recovery.sqlite3"),
                "cache_root": str(tmp_path / "cache"),
            },
        }
    )
    assert server.runner is not None and server.queue_store is not None
    server.runner.pause()
    job = server.queue_store.enqueue(
        clip_id="recovery-clip", snapshot={"version": 1}
    )
    server.queue_store.claim(worker_pid=1)
    server.queue_store.mark_interrupted_for_restart()
    status = server.handle({"protocol": "m3.ipc.v1", "method": "export_status"})
    assert status["jobs"][0]["user_confirmation_required"] is True
    confirmed = server.handle(
        {
            "protocol": "m3.ipc.v1",
            "method": "confirm_recovery",
            "params": {"job_ids": [job.job_id]},
        }
    )
    assert confirmed["jobs"][0]["state"] == "pending"
    assert confirmed["jobs"][0]["user_confirmation_required"] is False
    server._close_project()


def test_ipc_failed_export_can_be_retried_explicitly(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch
) -> None:
    server = JsonlIpcServer()
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server.handle(
        {
            "protocol": "m3.ipc.v1",
            "method": "import",
            "params": {
                "source_path": str(small_mp4),
                "project_path": str(tmp_path / "ipc-retry.sqlite3"),
                "cache_root": str(tmp_path / "cache"),
            },
        }
    )
    assert server.runner is not None and server.queue_store is not None
    server.runner.pause()
    job = server.queue_store.enqueue(
        clip_id="retry-clip", snapshot={"version": 1}, retry_limit=1
    )
    server.queue_store.claim(worker_pid=1)
    server.queue_store.transition(job.job_id, "failed", error_code="TEST_FAILURE")
    retried = server.handle(
        {
            "protocol": "m3.ipc.v1",
            "method": "retry_export",
            "params": {"job_id": job.job_id},
        }
    )
    assert retried["job"]["state"] == "pending"
    server._close_project()
