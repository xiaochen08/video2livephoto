from __future__ import annotations

import sqlite3
import json
import subprocess
from pathlib import Path

import pytest

from core.media.encode import encode_segment
from core.media.errors import MediaError
from core.media.frame_index import build_frame_index
from core.media.toolchain import Toolchain
from core.protocol.media import FrameRef, Rational


def _frames(report) -> tuple[FrameRef, ...]:
    assert report.index_path
    with sqlite3.connect(report.index_path) as db:
        rows = db.execute(
            "SELECT stream_index,display_index,pts,best_effort_pts,time_base_num,"
            "time_base_den,duration,duration_source,keyframe,pict_type,dts,packet_pos "
            "FROM frames ORDER BY display_index"
        ).fetchall()
    return tuple(
        FrameRef(
            stream_index=row[0],
            display_index=row[1],
            pts=row[2],
            best_effort_pts=row[3],
            time_base=Rational(row[4], row[5]),
            duration=row[6],
            duration_source=row[7],
            keyframe=bool(row[8]) if row[8] is not None else None,
            pict_type=row[9],
            dts=row[10],
            packet_pos=row[11],
        )
        for row in rows
    )


def test_encode_segment_preserves_confirmed_vfr_display_frame_range(
    vfr_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        vfr_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    frames = _frames(index)
    output = tmp_path / "out" / "clip.mp4"
    progress: list[float] = []
    result = encode_segment(
        vfr_mp4,
        frames,
        start_display_index=3,
        end_display_index=14,
        output_path=output,
        toolchain=toolchain,
        color_mode="warn",
        prefer_gpu=False,
        progress_callback=progress.append,
    )
    assert result.status == "complete"
    assert result.encoder == "libx264"
    assert result.frame_count == 11
    assert result.validation["frame_count"] == 11
    assert output.exists()
    assert result.validation["source_frame_range"]["start_display_index"] == 3
    assert progress
    assert progress[-1] == pytest.approx(1.0)
    assert all(previous <= current for previous, current in zip(progress, progress[1:]))


def test_encode_gpu_failure_restarts_from_beginning_with_cpu(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        small_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    result = encode_segment(
        small_mp4,
        _frames(index),
        start_display_index=0,
        end_display_index=index.frame_count,
        output_path=tmp_path / "clip.mp4",
        toolchain=toolchain,
        color_mode="warn",
        gpu_encoders=("m1_encoder_that_does_not_exist",),
    )
    assert result.status == "complete"
    assert result.encoder == "libx264"
    assert result.gpu_fallback is True
    assert result.gpu_attempted == ("m1_encoder_that_does_not_exist",)
    assert result.validation["frame_count"] == index.frame_count


def test_encode_silent_segment_has_no_audio_stream(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        small_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    result = encode_segment(
        small_mp4,
        _frames(index),
        start_display_index=0,
        end_display_index=min(index.frame_count, 6),
        output_path=tmp_path / "silent.mp4",
        toolchain=toolchain,
        audio_enabled=False,
        color_mode="warn",
        prefer_gpu=False,
    )
    assert result.status == "complete"
    assert result.validation["audio_stream_count"] == 0


def test_encode_rejects_source_as_output_and_preserves_source(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    import hashlib

    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        small_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    before = hashlib.sha256(small_mp4.read_bytes()).hexdigest()
    with pytest.raises(MediaError) as exc:
        encode_segment(
            small_mp4,
            _frames(index),
            start_display_index=0,
            end_display_index=min(index.frame_count, 2),
            output_path=small_mp4,
            toolchain=toolchain,
            color_mode="warn",
            prefer_gpu=False,
        )
    assert exc.value.code == "PATH_CONFLICT"
    assert hashlib.sha256(small_mp4.read_bytes()).hexdigest() == before


def test_encode_rejects_unknown_color_metadata_by_default(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        small_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    with pytest.raises(MediaError) as exc:
        encode_segment(
            small_mp4,
            _frames(index),
            start_display_index=0,
            end_display_index=2,
            output_path=tmp_path / "reject.mp4",
            toolchain=toolchain,
            prefer_gpu=False,
        )
    assert exc.value.code == "UNKNOWN_COLOR_METADATA"


def test_encode_uses_imported_sdr_color_choice_for_unknown_metadata(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        small_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    result = encode_segment(
        small_mp4,
        _frames(index),
        start_display_index=0,
        end_display_index=2,
        output_path=tmp_path / "sdr-selected.mp4",
        toolchain=toolchain,
        color_mode="sdr",
        source_color_override="sdr_rec709",
        prefer_gpu=False,
    )
    assert result.status == "complete"
    assert result.color_transform == "sdr-assumed-rec709"


def test_encode_rejects_unknown_import_color_choice(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        small_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    with pytest.raises(MediaError) as exc:
        encode_segment(
            small_mp4,
            _frames(index),
            start_display_index=0,
            end_display_index=2,
            output_path=tmp_path / "invalid-selection.mp4",
            toolchain=toolchain,
            color_mode="sdr",
            source_color_override="not-a-color-choice",
            prefer_gpu=False,
        )
    assert exc.value.code == "INVALID_COLOR_OVERRIDE"


def test_encode_uses_imported_hdr_pq_color_choice_for_unknown_metadata(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        small_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    output = tmp_path / "hdr-selected.mp4"
    result = encode_segment(
        small_mp4,
        _frames(index),
        start_display_index=0,
        end_display_index=2,
        output_path=output,
        toolchain=toolchain,
        color_mode="hdr",
        source_color_override="hdr_pq",
        prefer_gpu=False,
    )
    assert result.status == "complete"
    assert result.color_transform == "preserve-hdr"
    probe = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "stream=color_space,color_transfer,color_primaries",
            "-select_streams",
            "v:0",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["color_transfer"] == "smpte2084"
    assert stream["color_primaries"] == "bt2020"


def test_hdr10_input_is_tone_mapped_to_rec709_when_real_fixture_is_available(
    ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    fixture = Path(r"F:\M1_samples\hdr10_hevc_1s_v2.mp4")
    if not fixture.is_file():
        pytest.skip("real HDR10 fixture is not available on this machine")
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        fixture, cache_root=tmp_path / "index", toolchain=toolchain
    )
    result = encode_segment(
        fixture,
        _frames(index),
        start_display_index=0,
        end_display_index=index.frame_count,
        output_path=tmp_path / "hdr-sdr.mp4",
        toolchain=toolchain,
        color_mode="auto",
        prefer_gpu=False,
    )
    assert result.color_transform == "hdr-to-rec709-sdr"
    probe = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "stream=pix_fmt,color_space,color_transfer,color_primaries",
            "-select_streams",
            "v:0",
            result.output_path,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    payload = json.loads(probe.stdout)
    stream = payload["streams"][0]
    assert stream["pix_fmt"] == "yuv420p"
    assert stream["color_transfer"] == "bt709"
    assert stream["color_primaries"] == "bt709"
