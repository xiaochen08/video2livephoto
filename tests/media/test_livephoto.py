from __future__ import annotations

import json
from pathlib import Path

from core.livephoto.pack import pack_live_photo
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
    assert Path(manifest.jpg_path).exists()
    assert Path(manifest.mov_path).exists()
    assert Path(result.manifest_path).exists()
    assert manifest.validation["jpg_makernote_uuid"] == manifest.pairing_uuid
    assert manifest.validation["mov_contains_pairing_uuid"] is True
    assert manifest.validation["timed_metadata_track"] is False
    loaded = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert loaded["jpg_sha256"] == manifest.jpg_sha256
    assert loaded["mov_sha256"] == manifest.mov_sha256
