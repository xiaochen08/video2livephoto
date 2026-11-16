from __future__ import annotations

import sqlite3
import base64
import subprocess
import hashlib
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.media.toolchain import Toolchain
from core.media.process import CancellationToken
from desktop.models import AudioConflictError, M3ProjectError
from desktop.service import M3ProjectService


def _service(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> M3ProjectService:
    return M3ProjectService.import_media(
        small_mp4,
        project_path=tmp_path / "project.m3.sqlite3",
        cache_root=tmp_path / "cache",
        toolchain=Toolchain.from_paths(ffmpeg_path, ffprobe_path),
    )


def test_import_uses_real_m1_probe_and_frame_index_and_reopens(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    try:
        assert service.snapshot.frame_count >= 20
        assert service.snapshot.detector_status == "complete"
        assert service.snapshot.detector_version == "m2.detection.v1"
        assert service.frame_at(0).display_index == 0
        service.add_cut(5, needs_review=True)
        assert service.snapshot.segments[0].end_index == 5
        assert len(service.pending_reviews()) == 1
    finally:
        service.close()
    reopened = M3ProjectService.open_project(tmp_path / "project.m3.sqlite3")
    try:
        assert reopened.snapshot.cuts[0].boundary_index == 5
        assert reopened.snapshot.segments[0].start_index == 0
        with sqlite3.connect(tmp_path / "project.m3.sqlite3") as db:
            assert db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0] >= 2
    finally:
        reopened.close()


def test_import_runs_m2_and_decodes_bounded_preview(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    try:
        preview = service.preview_frame(0, width=320)
        assert preview["mime"] == "image/jpeg"
        assert preview["data_uri"].startswith("data:image/jpeg;base64,")
    finally:
        service.close()


def test_import_persists_user_color_override(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    service = M3ProjectService.import_media(
        small_mp4,
        project_path=tmp_path / "color-project.m3.sqlite3",
        cache_root=tmp_path / "color-cache",
        toolchain=Toolchain.from_paths(ffmpeg_path, ffprobe_path),
        color_override="sdr_rec709",
    )
    assert service.snapshot.color_override == "sdr_rec709"
    service.close()

    reopened = M3ProjectService.open_project(tmp_path / "color-project.m3.sqlite3")
    try:
        assert reopened.snapshot.color_override == "sdr_rec709"
    finally:
        reopened.close()


def test_preview_frame_uses_exact_display_pts(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    try:
        frame = service.frame_at(7)
        timestamp = frame.best_effort_pts if frame.best_effort_pts is not None else frame.pts
        assert timestamp is not None
        preview = service.preview_frame(7, width=320)
        actual = base64.b64decode(preview["data_uri"].split(",", 1)[1])
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-copyts",
                "-i",
                str(small_mp4),
                "-map",
                "0:v:0",
                "-an",
                "-sn",
                "-dn",
                "-frames:v",
                "1",
                "-vf",
                f"select='eq(pts\\,{timestamp})',scale=320:-2",
                "-vsync",
                "0",
                "-q:v",
                "3",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            check=False,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert hashlib.sha256(actual).hexdigest() == hashlib.sha256(result.stdout).hexdigest()
    finally:
        service.close()


def test_preview_frame_kills_ffmpeg_when_cancelled(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)

    class SlowProcess:
        def __init__(self, *_args, **_kwargs) -> None:
            self.kwargs = _kwargs
            self.started = threading.Event()
            self.finished = threading.Event()
            self.killed = False
            self.returncode: int | None = None
            self.started.set()

        def communicate(self):
            self.finished.wait(timeout=5)
            return b"", b"cancelled"

        def poll(self):
            return None if not self.finished.is_set() else self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9
            self.finished.set()

        def wait(self, timeout=None):
            self.finished.wait(timeout=timeout)
            return self.returncode

        def terminate(self):
            self.kill()

    process: SlowProcess | None = None

    def fake_popen(*args, **kwargs):
        nonlocal process
        process = SlowProcess(*args, **kwargs)
        return process

    monkeypatch.setattr("desktop.service.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        service,
        "frame_at",
        lambda _index: SimpleNamespace(
            best_effort_pts=0, pts=0, time_base_num=1, time_base_den=30
        ),
    )
    token = CancellationToken()
    result: list[BaseException] = []

    def run_preview() -> None:
        try:
            service.preview_frame(0, width=320, token=token)
        except BaseException as exc:  # assert the concrete cancellation below
            result.append(exc)

    worker = threading.Thread(target=run_preview)
    worker.start()
    deadline = time.monotonic() + 2
    while process is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert process is not None
    assert process.kwargs["stdin"] is subprocess.DEVNULL
    token.cancel()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert process.killed is True
    assert len(result) == 1
    assert isinstance(result[0], M3ProjectError)
    assert result[0].code == "CANCELLED"
    service.close()


def test_timeline_editing_undo_redo_and_contiguous_ranges(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    try:
        service.add_cut(5, needs_review=False)
        service.add_cut(12, needs_review=False)
        cut = service.snapshot.cuts[0]
        service.move_cut(cut.cut_id, 6)
        assert [
            (item.start_index, item.end_index) for item in service.snapshot.segments
        ] == [(0, 6), (6, 12), (12, service.snapshot.frame_count)]
        service.delete_cut(service.snapshot.cuts[1].cut_id)
        assert len(service.snapshot.segments) == 2
        service.undo()
        assert len(service.snapshot.segments) == 3
        service.redo()
        assert len(service.snapshot.segments) == 2
    finally:
        service.close()


def test_set_segment_bounds_is_atomic_and_single_undo_step(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    try:
        service.add_cut(5, needs_review=False)
        service.add_cut(12, needs_review=False)
        target = service.snapshot.segments[1]
        original = [(item.start_index, item.end_index) for item in service.snapshot.segments]
        service.set_segment_bounds(target.clip_id, 7, 14)
        assert [(item.start_index, item.end_index) for item in service.snapshot.segments] == [
            (0, 7),
            (7, 14),
            (14, service.snapshot.frame_count),
        ]
        service.undo()
        assert [(item.start_index, item.end_index) for item in service.snapshot.segments] == original
    finally:
        service.close()


def test_unreviewed_cut_requires_explicit_export_confirmation(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    try:
        service.add_cut(5, needs_review=True)
        with pytest.raises(M3ProjectError) as exc:
            service.confirm_export()
        assert exc.value.code == "PENDING_REVIEW"
        export = service.confirm_export(allow_unreviewed=True)
        assert export["encoder"] == "M4_M5_QUEUE_PIPELINE"
        assert export["confirmed_by_user"] is True
    finally:
        service.close()


def test_merge_audio_conflict_requires_choice_and_audio_settings_are_independent(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    try:
        service.add_cut(5, needs_review=False)
        left, right = service.snapshot.segments
        service.set_segment_audio(right.clip_id, False)
        with pytest.raises(AudioConflictError):
            service.merge_segments(left.clip_id, right.clip_id)
        service.merge_segments(left.clip_id, right.clip_id, audio_enabled=False)
        assert len(service.snapshot.segments) == 1
        assert service.snapshot.segments[0].audio_enabled is False
    finally:
        service.close()


def test_merge_many_selected_adjacent_segments_removes_internal_cuts_and_undoes(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    try:
        service.add_cut(5, needs_review=False)
        service.add_cut(12, needs_review=False)
        service.add_cut(18, needs_review=False)
        segments = sorted(service.snapshot.segments, key=lambda item: item.start_index)
        selected = [item.clip_id for item in segments[:3]]
        surviving_id = selected[0]

        service.merge_segments_many(selected, audio_enabled=True)
        assert [(item.start_index, item.end_index) for item in service.snapshot.segments] == [
            (0, 18),
            (18, service.snapshot.frame_count),
        ]
        assert [cut.boundary_index for cut in service.snapshot.cuts] == [18]
        assert service.snapshot.segments[0].clip_id == surviving_id

        service.undo()
        assert [cut.boundary_index for cut in service.snapshot.cuts] == [5, 12, 18]
        assert len(service.snapshot.segments) == 4
        service.redo()
        assert [cut.boundary_index for cut in service.snapshot.cuts] == [18]
        assert len(service.snapshot.segments) == 2
    finally:
        service.close()


def test_split_inherits_parent_audio_choice(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    try:
        original = service.snapshot.segments[0]
        service.set_segment_audio(original.clip_id, False)
        service.add_cut(5, needs_review=False)
        assert [item.audio_enabled for item in service.snapshot.segments] == [
            False,
            False,
        ]
    finally:
        service.close()


def test_open_rejects_changed_source_identity(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    service = _service(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    service.close()
    with small_mp4.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(M3ProjectError) as exc:
        M3ProjectService.open_project(tmp_path / "project.m3.sqlite3")
    assert exc.value.code == "SOURCE_CHANGED"
