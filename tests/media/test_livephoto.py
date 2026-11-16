from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

from core.livephoto.pack import pack_live_photo
from core.media.errors import MediaError
from core.media.encode import encode_segment
from core.media.frame_index import build_frame_index
from core.media.toolchain import Toolchain
from tests.media.test_encode import _frames


def test_livephoto_pair_has_matching_uuid_hashes_and_local_validation(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        small_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    segment = tmp_path / "segment.mp4"
    encode_segment(
        small_mp4,
        _frames(index),
        start_display_index=0,
        end_display_index=min(index.frame_count, 12),
        output_path=segment,
        toolchain=toolchain,
        color_mode="warn",
        prefer_gpu=False,
    )
    result = pack_live_photo(
        segment,
        output_dir=tmp_path / "LivePhoto",
        clip_id="clip-001",
        pairing_uuid="12345678-1234-5678-1234-567812345678",
        toolchain=toolchain,
    )
    assert result.status == "complete"
    assert result.manifest is not None
    manifest = result.manifest
    assert manifest.pairing_uuid == "12345678-1234-5678-1234-567812345678"
    assert manifest.jpg_path is None
    assert manifest.mov_path is None
    assert Path(manifest.livp_path).exists()
    assert Path(result.manifest_path).exists()
    with zipfile.ZipFile(manifest.livp_path) as archive:
        assert archive.testzip() is None
        assert len(archive.comment) == 28
        assert archive.comment[-8:] == b"1000LIVP"
        assert archive.namelist() == [
            "IMB_12345678.JPG",
            "IMB_12345678.MOV",
        ]
        assert all(
            item.compress_type == zipfile.ZIP_STORED
            for item in archive.infolist()
        )
        extracted_mov = tmp_path / "extracted.MOV"
        with archive.open("IMB_12345678.MOV") as source, extracted_mov.open("wb") as target:
            target.write(source.read())
    assert manifest.validation["livp"]["valid"] is True
    assert manifest.validation["livp"]["entry_count"] == 2
    assert manifest.validation["jpg_makernote_uuid"] == manifest.pairing_uuid
    assert manifest.validation["mov_contains_pairing_uuid"] is True
    assert manifest.validation["timed_metadata_track"] is True
    assert manifest.validation["timed_metadata_codec"] == "mebx"
    assert manifest.validation["timed_metadata_sample_marker"] == -1
    assert manifest.validation["timed_metadata_edit_list"] == [(0, -1), (1, 0)]
    assert manifest.validation["iphone_photos_import"] == "unverified"
    assert manifest.validation["motion_sensor_track"] is False
    assert manifest.validation["video_codec"] == "h264"
    assert manifest.validation["livephoto_duration_cap_seconds"] == 3.0
    assert manifest.validation["compatibility_warnings"] == [
        "non_hevc_video",
        "motion_sensor_track_missing",
    ]
    probe = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "stream=index,codec_type,codec_tag_string:stream_tags=handler_name",
            str(extracted_mov),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert probe.returncode == 0, probe.stderr
    streams = json.loads(probe.stdout)["streams"]
    assert any(
        stream.get("codec_type") == "data"
        and stream.get("codec_tag_string") == "mebx"
        for stream in streams
    )
    assert not any(stream.get("codec_tag_string") == "tmcd" for stream in streams)
    assert any(stream.get("codec_type") == "video" for stream in streams)
    assert any(stream.get("codec_type") == "audio" for stream in streams)
    metadata_probe = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_entries",
            "format_tags",
            str(extracted_mov),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert metadata_probe.returncode == 0, metadata_probe.stderr
    tags = json.loads(metadata_probe.stdout)["format"].get("tags") or {}
    assert tags["major_brand"] == "qt  "
    assert tags["com.apple.quicktime.content.identifier"] == manifest.pairing_uuid
    assert tags["com.apple.quicktime.live-photo.auto"] == "1"
    assert tags["com.apple.quicktime.live-photo.vitality-score"] == "1.0"
    assert tags["com.apple.quicktime.live-photo.vitality-scoring-version"] == "4"
    assert tags["com.apple.quicktime.full-frame-rate-playback-intent"] == "1"
    loaded = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert loaded["jpg_sha256"] == manifest.jpg_sha256
    assert loaded["mov_sha256"] == manifest.mov_sha256
    assert loaded["livp_sha256"] == manifest.livp_sha256
    assert loaded["livp_bytes"] == manifest.livp_bytes


def test_livephoto_rejects_still_time_outside_video(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        small_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    segment = tmp_path / "segment.mp4"
    encode_segment(
        small_mp4,
        _frames(index),
        start_display_index=0,
        end_display_index=min(index.frame_count, 12),
        output_path=segment,
        toolchain=toolchain,
        color_mode="warn",
        prefer_gpu=False,
    )
    try:
        pack_live_photo(
            segment,
            output_dir=tmp_path / "LivePhoto",
            clip_id="out-of-range",
            still_image_time_seconds=999.0,
            toolchain=toolchain,
        )
    except MediaError as exc:
        assert exc.code == "STILL_IMAGE_TIME_OUT_OF_RANGE"
    else:
        raise AssertionError("out-of-range still-image-time must be rejected")


def test_livephoto_mebx_edit_list_tracks_nonzero_still_time(
    small_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    index = build_frame_index(
        small_mp4, cache_root=tmp_path / "index", toolchain=toolchain
    )
    segment = tmp_path / "segment.mp4"
    encode_segment(
        small_mp4,
        _frames(index),
        start_display_index=0,
        end_display_index=min(index.frame_count, 18),
        output_path=segment,
        toolchain=toolchain,
        color_mode="warn",
        prefer_gpu=False,
    )
    result = pack_live_photo(
        segment,
        output_dir=tmp_path / "LivePhoto",
        clip_id="clip-nonzero",
        still_image_time_seconds=0.2,
        toolchain=toolchain,
    )
    assert result.manifest is not None
    validation = result.manifest.validation
    assert validation["timed_metadata_still_units"] == 200
    assert validation["timed_metadata_edit_list"] == [(200, -1), (1, 0)]


def test_livephoto_normalizes_fragmented_segment_before_mebx(
    fragmented_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    result = pack_live_photo(
        fragmented_mp4,
        output_dir=tmp_path / "LivePhoto",
        clip_id="clip-fmp4",
        pairing_uuid="12345678-1234-5678-1234-567812345679",
        toolchain=toolchain,
    )
    assert result.manifest is not None
    assert result.manifest.validation["timed_metadata_track"] is True
    assert result.manifest.validation["timed_metadata_codec"] == "mebx"
