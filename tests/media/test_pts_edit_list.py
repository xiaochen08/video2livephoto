from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from pathlib import Path

from core.media.frame_index import build_frame_index
from core.media.normalize import normalize_fragmented
from core.media.toolchain import Toolchain


def _ffprobe_json(
    ffprobe_path: str, path: Path, *options: str
) -> dict[str, object]:
    result = subprocess.run(
        [ffprobe_path, "-v", "error", *options, "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(result.stdout)


def _showinfo_pts(ffmpeg_path: str, path: Path) -> list[int]:
    result = subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(path),
            "-map",
            "0:v:0",
            "-vf",
            "showinfo",
            "-an",
            "-f",
            "null",
            "NUL",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [
        int(match.group(1))
        for match in re.finditer(r"showinfo.*\bn:\s*\d+\s+pts:\s*(-?\d+)", result.stderr)
    ]


def _indexed_pts(index_path: str) -> tuple[list[int | None], list[int | None]]:
    with sqlite3.connect(index_path) as db:
        rows = db.execute(
            "SELECT pts, best_effort_pts FROM frames ORDER BY display_index"
        ).fetchall()
    return [row[0] for row in rows], [row[1] for row in rows]


def _display_frame_rows(ffprobe_path: str, path: Path) -> list[dict[str, object]]:
    payload = _ffprobe_json(
        ffprobe_path,
        path,
        "-select_streams",
        "v:0",
        "-show_frames",
        "-show_entries",
        "frame=pts,best_effort_timestamp,pict_type",
    )
    return list(payload.get("frames", []))


def test_negative_pts_edit_list_display_timeline_matches_independent_decoders(
    negative_pts_edit_list_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    """Verify an edit-list/AAC-preroll sample without treating audio PTS as video PTS."""

    source_bytes = negative_pts_edit_list_mp4.read_bytes()
    # The fixture is a real MP4 edit-list sample, not a renamed or hand-written file.
    assert b"edts" in source_bytes
    assert b"elst" in source_bytes

    audio_packets = _ffprobe_json(
        ffprobe_path,
        negative_pts_edit_list_mp4,
        "-select_streams",
        "a:0",
        "-show_packets",
        "-show_entries",
        "packet=pts,dts,duration",
    )["packets"]
    assert audio_packets
    assert int(audio_packets[0]["pts"]) < 0
    assert int(audio_packets[0]["pts"]) == -1024

    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    report = build_frame_index(
        negative_pts_edit_list_mp4,
        cache_root=tmp_path / "cache",
        toolchain=toolchain,
    )
    indexed_pts, indexed_best_effort = _indexed_pts(report.index_path)
    independent_rows = _display_frame_rows(ffprobe_path, negative_pts_edit_list_mp4)
    independent_pts = [row.get("pts") for row in independent_rows]
    independent_best_effort = [
        row.get("best_effort_timestamp") for row in independent_rows
    ]
    assert indexed_pts == [int(value) for value in independent_pts]
    assert indexed_best_effort == [int(value) for value in independent_best_effort]
    assert _showinfo_pts(ffmpeg_path, negative_pts_edit_list_mp4) == indexed_pts
    assert report.frame_count == len(independent_rows)
    assert report.first_pts == indexed_best_effort[0]
    assert report.last_pts == indexed_best_effort[-1]


def test_fmp4_copy_normalization_preserves_display_frames_and_reports_mapping(
    fragmented_av_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    result = normalize_fragmented(
        fragmented_av_mp4,
        cache_root=tmp_path / "cache",
        toolchain=toolchain,
    )
    assert result.status == "complete"
    assert result.normalized_path is not None
    normalized = Path(result.normalized_path)

    source_rows = _display_frame_rows(ffprobe_path, fragmented_av_mp4)
    output_rows = _display_frame_rows(ffprobe_path, normalized)
    source_pts = [int(row["best_effort_timestamp"]) for row in source_rows]
    output_pts = [int(row["best_effort_timestamp"]) for row in output_rows]
    assert len(output_pts) == len(source_pts)
    offsets = {output - source for source, output in zip(source_pts, output_pts)}
    assert len(offsets) == 1
    offset = next(iter(offsets))

    source_stream = _ffprobe_json(
        ffprobe_path,
        fragmented_av_mp4,
        "-show_streams",
        "-select_streams",
        "v:0",
    )["streams"][0]
    output_stream = _ffprobe_json(
        ffprobe_path,
        normalized,
        "-show_streams",
        "-select_streams",
        "v:0",
    )["streams"][0]
    assert source_stream["time_base"] == output_stream["time_base"]
    assert result.validation["source_to_normalized_pts_offset"] == offset
    assert result.validation["video_timeline"]["source"]["frame_count"] == len(
        source_pts
    )
    assert result.validation["video_timeline"]["normalized"]["frame_count"] == len(
        output_pts
    )

    audio_timeline = result.validation["audio_timeline"]
    assert audio_timeline
    for stream in audio_timeline.values():
        assert stream["packet_count"] > 0
        assert stream["pts_offset"] is not None or stream["packet_count"] == 0

