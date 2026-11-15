from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.media.toolchain import Toolchain
from desktop.ipc_server import JsonlIpcServer


def _request(method: str, params: dict | None = None) -> dict:
    return {"id": f"test-{method}-{time.monotonic_ns()}", "protocol": "m3.ipc.v1", "method": method, "params": params or {}}


def test_contract_connect_is_explicit_desktop() -> None:
    response = JsonlIpcServer().handle(_request("connect"))
    assert response["ok"] is True
    assert response["connection"]["mode"] == "desktop"
    assert response["connection"]["capabilities"]["frame_accurate_preview"] is True


def test_contract_open_and_timeline_returns_string_pts(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server = JsonlIpcServer()
    project_path = tmp_path / "contract.sqlite3"
    imported = server.handle(_request("import", {"source_path": str(small_mp4), "project_path": str(project_path), "cache_root": str(tmp_path / "cache")}))
    project_id = imported["project"]["project_id"]
    opened = server.handle(_request("projects.open", {"project_id": project_id}))
    project = opened["result"]["project"]
    assert project["project_id"] == project_id
    assert project["timeline"]["frame_count"] == imported["project"]["frame_count"]
    assert all(item["pts"] is None or isinstance(item["pts"], str) for item in project["timeline"]["cuts"])
    frame = server.handle(_request("preview.getFrame", {"project_id": project_id, "frame": 0, "size": "thumb"}))
    assert frame["frame"]["exact"] is True
    assert frame["frame"]["url"].startswith("data:image/jpeg;base64,")
    server._close_project()


def test_contract_edit_request_id_is_idempotent_and_stale_base_rejected(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server = JsonlIpcServer()
    imported = server.handle(_request("import", {"source_path": str(small_mp4), "project_path": str(tmp_path / "edit.sqlite3"), "cache_root": str(tmp_path / "cache")}))
    project_id = imported["project"]["project_id"]
    rid = "same-edit-intent"
    params = {"project_id": project_id, "base_edit_version": imported["project"]["saved_revision"], "cmd": {"type": "add_cut", "frame": 5}, "request_id": rid}
    first = server.handle(_request("timeline.apply", params))
    repeated = server.handle(_request("timeline.apply", params))
    assert repeated == first
    with pytest.raises(Exception) as exc:
        server.handle(_request("timeline.apply", {**params, "request_id": "stale", "base_edit_version": 0, "cmd": {"type": "add_cut", "frame": 6}}))
    assert getattr(exc.value, "code", None) == "EDIT_VERSION_CONFLICT"
    server._close_project()


def test_analysis_start_is_single_request_and_deduplicates(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server = JsonlIpcServer()
    params = {"source_path": str(small_mp4), "project_path": str(tmp_path / "analysis.sqlite3"), "cache_root": str(tmp_path / "analysis-cache"), "video_stream_index": 0, "project_name": "analysis", "request_id": "analysis-once"}
    started = server.handle(_request("analysis.start", params))
    repeated = server.handle(_request("analysis.start", params))
    assert started["analysis_id"] == repeated["analysis_id"]
    completed = server.handle(_request("analysis.start", {**params, "await_result": True}))
    assert completed["project_id"]
    assert len(server._analysis_by_request) == 1
    server._close_project()
    server._analysis_executor.shutdown(wait=False, cancel_futures=False)
