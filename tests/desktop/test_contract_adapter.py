from __future__ import annotations

import json
import time
from types import SimpleNamespace
from pathlib import Path

import pytest

from core.media.toolchain import Toolchain
from core.queue.store import QueueState
from desktop.adapter_contract import media_info
from desktop.ipc_server import JsonlIpcServer


def _request(method: str, params: dict | None = None) -> dict:
    return {"id": f"test-{method}-{time.monotonic_ns()}", "protocol": "m3.ipc.v1", "method": method, "params": params or {}}


def test_contract_connect_is_explicit_desktop() -> None:
    response = JsonlIpcServer().handle(_request("connect"))
    assert response["ok"] is True
    assert response["connection"]["mode"] == "desktop"
    assert response["connection"]["capabilities"]["frame_accurate_preview"] is True
    assert response["connection"]["capabilities"]["livephoto_hint"]["long_above_ms"] == 3000


def test_file_actions_resolve_committed_paths_for_electron(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "exports"
    video = output_dir / "视频片段" / "clip.mp4"
    livephoto = output_dir / "LivePhoto" / "clip.livp"
    for item in (video, livephoto):
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_bytes(b"artifact")

    job = SimpleNamespace(
        job_id="job-files",
        snapshot={"project_id": "project-files"},
        output_dir=str(output_dir),
        state=QueueState.SUCCEEDED,
        result={
            "target_paths": [str(video), str(livephoto)],
            "manifest_path": str(output_dir / "LivePhoto" / "clip.manifest.json"),
        },
    )

    class FakeQueue:
        def get(self, job_id: str):
            assert job_id == job.job_id
            return job

        def list(self):
            return [job]

    server = JsonlIpcServer()
    server.queue_store = FakeQueue()

    opened = server.handle(_request("files.openArtifact", {"job_id": job.job_id, "kind": "mp4"}))
    opened_livephoto = server.handle(_request("files.openArtifact", {"job_id": job.job_id, "kind": "livp"}))
    revealed = server.handle(_request("files.revealOutput", {"project_id": "project-files", "job_id": job.job_id}))

    assert opened == {"ok": True, "path": str(video.resolve())}
    assert opened_livephoto == {"ok": True, "path": str(livephoto.resolve())}
    assert revealed == {"ok": True, "path": str(output_dir.resolve())}


def test_media_probe_namespace_without_color_override_is_supported() -> None:
    snapshot = SimpleNamespace(
        probe={
            "selected_video_stream": 0,
            "container": {"format_names": ["mp4"], "duration_seconds": 1.0},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 320,
                    "height": 240,
                    "avg_frame_rate_hint": {"num": 30, "den": 1},
                    "time_base": {"num": 1, "den": 30},
                    "duration_seconds": 1.0,
                    "color": {"transfer": "unknown", "primaries": "unknown"},
                    "disposition": {"default": 1},
                }
            ],
        },
        frame_count=0,
    )
    result = media_info(snapshot)
    assert result["video_streams"][0]["color"]["transfer"] == "unknown"


def test_contract_job_reports_gpu_attempt_and_real_frame_progress() -> None:
    server = JsonlIpcServer()
    job = SimpleNamespace(
        job_id="job-1",
        clip_id="clip-1",
        attempt_count=1,
        created_at="2026-11-15T00:00:00Z",
        updated_at="2026-11-15T00:00:01Z",
        state=QueueState.PROCESSING,
        phase="encoding",
        progress=0.05 + 0.60 * 0.5,
        snapshot={"segment": {"start_index": 0, "end_index": 642, "output_number": 1}},
        result={},
        error_code=None,
        error_message=None,
    )

    contract = server._contract_job(job, "batch-1")

    assert contract["attempts"][0]["encoder"] == "gpu"
    assert contract["progress"] == {"kind": "frames", "done": 321, "total": 642}


def test_default_output_path_uses_selected_storage_and_replaces_legacy_home_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_data = tmp_path / "appdata"
    app_data.mkdir()
    legacy_default = Path.home() / "Videos" / "Video2LivePhoto"
    (app_data / "settings.json").write_text(
        json.dumps({"default_output_dir": str(legacy_default)}),
        encoding="utf-8",
    )
    selected_root = tmp_path / "largest-ssd" / "Video2LivePhoto"
    monkeypatch.setenv("VIDEO2LIVEPHOTO_APP_DATA_DIR", str(app_data))
    monkeypatch.setattr("desktop.ipc_server.default_storage_root", lambda: selected_root)

    defaults = JsonlIpcServer()._settings_defaults()

    assert Path(defaults["default_output_dir"]) == selected_root / "Exports"


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
    source = server.handle(_request("preview.getSource", {"project_id": project_id}))
    assert source["source"]["_source_path"] == str(small_mp4.resolve())
    frame = server.handle(_request("preview.getFrame", {"project_id": project_id, "frame": 0, "size": "thumb"}))
    assert frame["frame"]["exact"] is True
    assert frame["frame"]["url"].startswith("data:image/jpeg;base64,")
    server._close_project()


def test_import_color_choice_is_visible_and_reused_by_export(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server = JsonlIpcServer()
    imported = server.handle(
        _request(
            "import",
            {
                "source_path": str(small_mp4),
                "project_path": str(tmp_path / "color-choice.sqlite3"),
                "cache_root": str(tmp_path / "color-cache"),
                "color_override": "sdr_rec709",
            },
        )
    )
    project_id = imported["project"]["project_id"]
    opened = server.handle(_request("projects.open", {"project_id": project_id}))["result"]["project"]
    selected = next(
        item
        for item in opened["media"]["video_streams"]
        if item["stream_index"] == opened["media"]["selected_video_stream"]
    )
    assert selected["color"]["transfer"] == "bt709"
    assert selected["color"]["primaries"] == "bt709"
    assert opened["export_settings"]["color"] == "sdr_rec709"

    assert server.runner is not None
    server.runner.pause()
    batch = server.handle(
        _request(
            "export.createBatch",
            {
                "project_id": project_id,
                "edit_version": opened["edit_version"],
                "clip_ids": [opened["timeline"]["clips"][0]["clip_id"]],
                "settings": opened["export_settings"],
                "acknowledged": {"unreviewed_cuts": True, "livephoto_hints": True, "replace_existing": True},
                "request_id": "color-choice-export",
            },
        )
    )
    job_id = server._batch_meta[batch["batch_id"]]["job_ids"][0]
    assert server.queue_store is not None
    job = server.queue_store.get(job_id)
    assert job.snapshot["source_color_override"] == "sdr_rec709"
    server._close_project()


def test_export_preflight_blocks_legacy_project_without_color_choice(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server = JsonlIpcServer()
    imported = server.handle(
        _request(
            "import",
            {
                "source_path": str(small_mp4),
                "project_path": str(tmp_path / "legacy-color.sqlite3"),
                "cache_root": str(tmp_path / "legacy-color-cache"),
            },
        )
    )
    project_id = imported["project"]["project_id"]
    opened = server.handle(_request("projects.open", {"project_id": project_id}))["result"]["project"]
    preflight = server.handle(
        _request(
            "export.preflight",
            {
                "project_id": project_id,
                "edit_version": opened["edit_version"],
                "clip_ids": [opened["timeline"]["clips"][0]["clip_id"]],
                "settings": opened["export_settings"],
            },
        )
    )["preflight"]
    assert preflight["ok"] is False
    assert any(issue["code"] == "COLOR_SELECTION_REQUIRED" for issue in preflight["issues"])
    server._close_project()


def test_hdr_import_choice_changes_source_interpretation_not_output_default(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server = JsonlIpcServer()
    imported = server.handle(
        _request(
            "import",
            {
                "source_path": str(small_mp4),
                "project_path": str(tmp_path / "hdr-choice.sqlite3"),
                "cache_root": str(tmp_path / "hdr-choice-cache"),
                "color_override": "hdr_pq",
            },
        )
    )
    project = server.handle(_request("projects.open", {"project_id": imported["project"]["project_id"]}))["result"]["project"]
    selected = next(item for item in project["media"]["video_streams"] if item["stream_index"] == project["media"]["selected_video_stream"])
    assert selected["color"]["transfer"] == "pq"
    assert selected["color"]["primaries"] == "bt2020"
    assert project["export_settings"]["color"] == "sdr_rec709"
    server._close_project()


def test_contract_export_uses_custom_root_and_timestamped_project_folder(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    app_data = tmp_path / "appdata"
    custom_root = tmp_path / "custom-exports"
    app_data.mkdir()
    (app_data / "settings.json").write_text(
        json.dumps({"default_output_dir": str(custom_root)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIDEO2LIVEPHOTO_APP_DATA_DIR", str(app_data))
    server = JsonlIpcServer()
    imported = server.handle(_request("import", {"source_path": str(small_mp4), "project_path": str(tmp_path / "export.sqlite3"), "cache_root": str(tmp_path / "cache")}))
    project_id = imported["project"]["project_id"]
    opened = server.handle(_request("projects.open", {"project_id": project_id}))["result"]["project"]
    assert opened["export_settings"]["output_dir"] == str(custom_root)
    assert server.runner is not None
    server.runner.pause()
    result = server.handle(_request("export.createBatch", {
        "project_id": project_id,
        "edit_version": opened["edit_version"],
        "clip_ids": [opened["timeline"]["clips"][0]["clip_id"]],
        "settings": opened["export_settings"],
        "acknowledged": {"unreviewed_cuts": True, "livephoto_hints": True, "replace_existing": True},
        "request_id": "timestamped-export",
    }))
    output_dir = Path(result["output_dir"])
    assert output_dir.parent == custom_root.resolve()
    assert output_dir.name.startswith(f"livephotos {small_mp4.stem} ")
    assert output_dir.is_dir()
    job_id = server._batch_meta[result["batch_id"]]["job_ids"][0]
    assert server.queue_store is not None
    assert Path(server.queue_store.get(job_id).temp_dir or "").parent == output_dir.parent
    server._close_project()


def test_contract_marks_indexed_vfr_and_uses_pts_clip_boundaries(
    vfr_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server = JsonlIpcServer()
    imported = server.handle(_request("import", {"source_path": str(vfr_mp4), "project_path": str(tmp_path / "vfr.sqlite3"), "cache_root": str(tmp_path / "vfr-cache")}))
    project = server.handle(_request("projects.open", {"project_id": imported["project"]["project_id"]}))["result"]["project"]
    selected = next(item for item in project["media"]["video_streams"] if item["stream_index"] == project["media"]["selected_video_stream"])
    assert selected["vfr"] is True
    assert project["timeline"]["clips"][0]["start_pts"] is not None
    assert project["timeline"]["clips"][-1]["end_pts"] is not None
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


def test_contract_undo_redo_use_monotonic_edit_versions(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server = JsonlIpcServer()
    imported = server.handle(_request("import", {"source_path": str(small_mp4), "project_path": str(tmp_path / "history.sqlite3"), "cache_root": str(tmp_path / "history-cache")}))
    project_id = imported["project"]["project_id"]
    initial = int(imported["project"]["saved_revision"])
    applied = server.handle(_request("timeline.apply", {"project_id": project_id, "base_edit_version": initial, "cmd": {"type": "add_cut", "frame": 5}, "request_id": "history-add"}))
    undone = server.handle(_request("timeline.undo", {"project_id": project_id, "base_edit_version": applied["edit_version"], "request_id": "history-undo"}))
    redone = server.handle(_request("timeline.redo", {"project_id": project_id, "base_edit_version": undone["edit_version"], "request_id": "history-redo"}))
    assert initial < applied["edit_version"] < undone["edit_version"] < redone["edit_version"]
    assert undone["timeline"]["cuts"] == []
    assert len(redone["timeline"]["cuts"]) == 1
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
    completed = server.handle(_request("analysis.result", {"analysis_id": started["analysis_id"], "request_id": params["request_id"]}))
    assert completed["project_id"]
    assert len(server._analysis_by_request) == 1
    server._close_project()
    server._analysis_executor.shutdown(wait=False, cancel_futures=False)


def test_analysis_start_persists_import_color_choice(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    server = JsonlIpcServer()
    started = server.handle(
        _request(
            "analysis.start",
            {
                "source_path": str(small_mp4),
                "project_path": str(tmp_path / "analysis-color.sqlite3"),
                "cache_root": str(tmp_path / "analysis-color-cache"),
                "video_stream_index": 0,
                "project_name": "analysis-color",
                "color_override": "sdr_rec709",
                "request_id": "analysis-color-choice",
            },
        )
    )
    completed = server.handle(
        _request("analysis.result", {"analysis_id": started["analysis_id"]})
    )
    assert completed["warnings"][0]["code"] == "COLOR_SELECTED_BY_USER"
    assert server.service is not None
    assert server.service.snapshot.color_override == "sdr_rec709"
    server._close_project()
    server._analysis_executor.shutdown(wait=False, cancel_futures=False)


def test_analysis_without_project_path_uses_configured_project_directory(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    monkeypatch.setenv("VIDEO2LIVEPHOTO_PROJECT_DIR", str(tmp_path / "projects"))
    server = JsonlIpcServer()
    started = server.handle(_request("analysis.start", {"source_path": str(small_mp4), "video_stream_index": 0, "project_name": "default-path", "request_id": "analysis-default-path"}))
    completed = server.handle(_request("analysis.result", {"analysis_id": started["analysis_id"]}))
    assert Path(completed["project_path"]).is_file()
    server._close_project()
    server._analysis_executor.shutdown(wait=False, cancel_futures=False)


def test_analysis_without_project_path_uses_selected_storage_root(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    monkeypatch.setattr("desktop.service.Toolchain.discover", lambda: toolchain)
    monkeypatch.delenv("VIDEO2LIVEPHOTO_PROJECT_DIR", raising=False)
    selected_root = tmp_path / "largest-ssd" / "Video2LivePhoto"
    monkeypatch.setattr("desktop.ipc_server.default_storage_root", lambda: selected_root)
    server = JsonlIpcServer()

    started = server.handle(
        _request(
            "analysis.start",
            {
                "source_path": str(small_mp4),
                "video_stream_index": 0,
                "project_name": "default-storage-path",
                "request_id": "analysis-default-storage-path",
            },
        )
    )
    completed = server.handle(
        _request("analysis.result", {"analysis_id": started["analysis_id"]})
    )

    assert Path(completed["project_path"]).parent == selected_root / "Projects"
    server._close_project()
    server._analysis_executor.shutdown(wait=False, cancel_futures=False)
