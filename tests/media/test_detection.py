from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.analysis.shot_detection import (
    DetectionResult,
    detect_shots,
    detection_to_json,
)
from core.media.errors import MediaError
from core.media.frame_index import build_frame_index
from core.media.toolchain import Toolchain


def _detect(
    path: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> DetectionResult:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    report = build_frame_index(
        path, cache_root=tmp_path / f"cache-{path.stem}", toolchain=toolchain
    )
    return detect_shots(path, frame_index_report=report, toolchain=toolchain)


def test_hard_cut_is_reported_on_display_frame_boundary(
    hard_cut_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    result = _detect(hard_cut_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    assert result.status == "complete"
    assert result.analyzed_frame_count == 30
    hard = [item for item in result.candidates if item.kind == "hard_cut"]
    assert hard
    assert min(abs(item.frame_index - 15) for item in hard) <= 1
    assert all(item.pts >= 0 for item in hard)
    assert all(
        result.segments[index].end_frame == result.segments[index + 1].start_frame
        for index in range(len(result.segments) - 1)
    )


def test_black_transition_keeps_black_frames_and_marks_review(
    black_transition_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    result = _detect(black_transition_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    black = [item for item in result.candidates if item.kind == "black_transition"]
    assert len(black) >= 2
    assert all(item.review_required for item in black)
    assert any(item.frame_index in {12, 18} for item in black)
    assert any(
        segment.start_frame == 12 and segment.end_frame == 18
        for segment in result.segments
    )


def test_dissolve_is_snapped_to_midpoint_and_requires_review(
    dissolve_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    result = _detect(dissolve_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    dissolve = [item for item in result.candidates if item.kind == "dissolve_midpoint"]
    assert dissolve
    assert all(item.review_required for item in dissolve)
    assert any(20 <= item.frame_index <= 28 for item in dissolve)


def test_short_shot_is_retained_and_all_frames_are_covered(
    short_shot_sequence_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    result = _detect(short_shot_sequence_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    assert result.analyzed_frame_count == 36
    assert any(
        segment.short_shot and segment.start_frame == 0 for segment in result.segments
    )
    assert result.segments[0].start_frame == 0
    assert result.segments[-1].end_frame == result.analyzed_frame_count
    covered = [
        frame
        for segment in result.segments
        for frame in range(segment.start_frame, segment.end_frame)
    ]
    assert covered == list(range(result.analyzed_frame_count))


def test_vfr_and_b_frame_index_are_consumed_without_fps_estimation(
    vfr_mp4: Path, small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    vfr_result = _detect(vfr_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    b_result = _detect(small_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    assert vfr_result.analyzed_frame_count > 10
    assert b_result.analyzed_frame_count >= 20
    assert all(
        segment.end_frame == next_segment.start_frame
        for segment, next_segment in zip(vfr_result.segments, vfr_result.segments[1:])
    )


def test_detection_result_is_versioned_and_json_serializable(
    hard_cut_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    result = _detect(hard_cut_mp4, ffmpeg_path, ffprobe_path, tmp_path)
    payload = json.loads(detection_to_json(result))
    assert payload["schema_version"] == "m2.detection.v1"
    assert payload["config"]["version"] == "m2.config.v1"
    assert payload["segments"]


def test_detection_rejects_audio_only_media(
    tmp_path: Path, ffmpeg_path: str, ffprobe_path: str
) -> None:
    path = tmp_path / "audio-only.mp4"
    subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=8000",
            "-t",
            "0.2",
            "-c:a",
            "aac",
            "-vn",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    with pytest.raises(MediaError) as exc:
        build_frame_index(path, cache_root=tmp_path / "cache", toolchain=toolchain)
    assert exc.value.code == "NO_VIDEO_STREAM"
