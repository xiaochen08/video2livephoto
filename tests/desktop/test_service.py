from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.media.toolchain import Toolchain
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
        assert service.snapshot.detector_status == "not_connected"
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
        assert export["encoder"] == "M4_NOT_CONNECTED"
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
