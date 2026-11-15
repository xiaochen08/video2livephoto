from __future__ import annotations

import time
from pathlib import Path

from core.media.toolchain import Toolchain
from desktop.ipc_server import JsonlIpcServer


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
