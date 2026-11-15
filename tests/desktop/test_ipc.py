from __future__ import annotations

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
    server.service.close()
