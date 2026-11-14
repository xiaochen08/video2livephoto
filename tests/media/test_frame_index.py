from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.media.errors import MediaError
from core.media.frame_index import CancellationToken, build_frame_index
from core.media.toolchain import Toolchain


def test_frame_index_keeps_b_frame_order_and_integer_pts(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    report = build_frame_index(
        small_mp4,
        cache_root=tmp_path / "cache",
        toolchain=toolchain,
    )
    assert report.status == "complete"
    assert report.frame_count >= 20
    assert report.index_path is not None
    with sqlite3.connect(report.index_path) as db:
        rows = db.execute(
            "SELECT display_index, pts, duration_source, pict_type FROM frames "
            "ORDER BY display_index LIMIT 5"
        ).fetchall()
    assert [row[0] for row in rows] == [0, 1, 2, 3, 4]
    assert all(row[1] is not None for row in rows)
    assert any(row[3] == "B" for row in rows)


def test_vfr_index_preserves_non_uniform_pts(
    vfr_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    report = build_frame_index(
        vfr_mp4,
        cache_root=tmp_path / "cache",
        toolchain=toolchain,
    )
    assert report.status == "complete"
    with sqlite3.connect(report.index_path) as db:
        pts = [
            row[0]
            for row in db.execute("SELECT pts FROM frames ORDER BY display_index")
        ]
    assert len(pts) > 4
    assert len(set(b - a for a, b in zip(pts, pts[1:]))) > 1


def test_cancelled_index_is_not_reported_as_complete(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(MediaError) as exc:
        build_frame_index(
            small_mp4,
            cache_root=tmp_path / "cache",
            toolchain=toolchain,
            token=token,
        )
    assert exc.value.code == "CANCELLED"
    databases = list((tmp_path / "cache").glob("*.sqlite3"))
    if databases:
        import sqlite3

        with sqlite3.connect(databases[0]) as db:
            assert (
                db.execute("SELECT value FROM metadata WHERE key='status'").fetchone()[
                    0
                ]
                != "complete"
            )


def test_completed_cache_is_reused_when_source_and_toolchain_match(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    first = build_frame_index(
        small_mp4, cache_root=tmp_path / "cache", toolchain=toolchain
    )
    second = build_frame_index(
        small_mp4, cache_root=tmp_path / "cache", toolchain=toolchain
    )
    assert first.index_path == second.index_path
    assert second.resource_stats["cache_reused"] is True


def test_cache_path_cannot_be_the_source_file(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    with pytest.raises(MediaError) as exc:
        build_frame_index(small_mp4, cache_root=small_mp4, toolchain=toolchain)
    assert exc.value.code == "PATH_CONFLICT"


def test_fragmented_media_can_build_direct_index_when_ffprobe_is_trustworthy(
    fragmented_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    report = build_frame_index(
        fragmented_mp4,
        cache_root=tmp_path / "cache",
        toolchain=toolchain,
    )
    assert report.status == "complete"
    assert report.frame_count == 30


def test_moof_without_mvex_is_rejected_when_ffprobe_cannot_verify_it(
    fragmented_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    malformed = tmp_path / "moof-without-mvex.mp4"
    malformed.write_bytes(fragmented_mp4.read_bytes().replace(b"mvex", b"free", 1))
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    with pytest.raises(MediaError) as exc:
        build_frame_index(malformed, cache_root=tmp_path / "cache", toolchain=toolchain)
    assert exc.value.code in {"FFPROBE_FAILED", "FRAME_INDEX_EMPTY"}
