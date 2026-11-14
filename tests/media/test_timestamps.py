from __future__ import annotations

import sqlite3
import re
import subprocess
from pathlib import Path

from core.media.frame_index import build_frame_index
from core.media.toolchain import Toolchain


def _compact_records(ffprobe: str, args: list[str], path: Path) -> list[dict[str, str]]:
    result = subprocess.run(
        [ffprobe, "-v", "error", *args, str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    records: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        records.append(
            {
                key: value
                for token in line.split("|")
                if "=" in token
                for key, value in [token.split("=", 1)]
            }
        )
    return records


def test_negative_audio_pts_and_edit_list_are_preserved_in_frame_evidence(
    negative_pts_edit_list_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    data = negative_pts_edit_list_mp4.read_bytes()
    assert b"edts" in data
    assert b"elst" in data

    audio_packets = _compact_records(
        ffprobe_path,
        [
            "-show_packets",
            "-select_streams",
            "a",
            "-show_entries",
            "packet=pts,dts,duration:packet_side_data=",
            "-of",
            "compact=p=0:nk=0",
        ],
        negative_pts_edit_list_mp4,
    )
    video_packets = _compact_records(
        ffprobe_path,
        [
            "-show_packets",
            "-select_streams",
            "v",
            "-show_entries",
            "packet=pts,dts,duration:packet_side_data=",
            "-of",
            "compact=p=0:nk=0",
        ],
        negative_pts_edit_list_mp4,
    )
    assert min(int(packet["pts"]) for packet in audio_packets) < 0
    assert min(int(packet["dts"]) for packet in video_packets) < 0

    independent_frames = _compact_records(
        ffprobe_path,
        [
            "-select_streams",
            "v",
            "-show_frames",
            "-show_entries",
            "frame=stream_index,best_effort_timestamp:frame_side_data=",
            "-of",
            "compact=p=0:nk=0",
        ],
        negative_pts_edit_list_mp4,
    )
    expected_pts = [int(frame["best_effort_timestamp"]) for frame in independent_frames]

    report = build_frame_index(
        negative_pts_edit_list_mp4,
        cache_root=tmp_path / "cache",
        toolchain=Toolchain.from_paths(ffmpeg_path, ffprobe_path),
    )
    with sqlite3.connect(report.index_path) as db:
        indexed_pts = [
            row[0]
            for row in db.execute("SELECT pts FROM frames ORDER BY display_index")
        ]
    assert indexed_pts == expected_pts

    decoded = subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(negative_pts_edit_list_mp4),
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
    decoded_pts = [
        int(match.group(1))
        for match in re.finditer(
            r"showinfo.*?n:\s*\d+\s+pts:\s*(-?\d+)", decoded.stderr
        )
    ]
    assert decoded_pts == indexed_pts
