from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core.media.errors import MediaError
from core.media.normalize import normalize_fragmented
from core.media.toolchain import Toolchain


def test_normalize_fragmented_media_stays_in_cache_and_keeps_source(
    fragmented_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    before = fragmented_mp4.read_bytes()
    before_sha = hashlib.sha256(before).hexdigest()
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    result = normalize_fragmented(
        fragmented_mp4,
        cache_root=tmp_path / "cache",
        toolchain=toolchain,
    )
    assert result.status == "complete"
    assert result.normalized_path is not None
    normalized = Path(result.normalized_path)
    assert normalized.parent != fragmented_mp4.parent
    assert normalized.exists()
    assert fragmented_mp4.read_bytes() == before
    assert hashlib.sha256(fragmented_mp4.read_bytes()).hexdigest() == before_sha
    assert not list(normalized.parent.glob("*.partial.mp4"))
    assert result.validation["frame_index_status"] == "complete"


def test_normalize_fragmented_media_checks_audio_packet_timeline(
    fragmented_av_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    result = normalize_fragmented(
        fragmented_av_mp4,
        cache_root=tmp_path / "cache",
        toolchain=toolchain,
    )
    assert result.status == "complete"
    assert result.validation["audio_timeline"]
    assert all(
        item["packet_count"] > 0
        for item in result.validation["audio_timeline"].values()
    )
    assert result.validation["video_timeline"]["source"]["time_base"] == {
        "num": 1,
        "den": 15360,
    }
    assert result.validation["video_timeline"]["normalized"]["time_base"] == {
        "num": 1,
        "den": 15360,
    }
    assert result.validation["audio_time_bases"]["source"] == {
        "1": {"num": 1, "den": 48000}
    }
    assert result.validation["audio_time_bases"]["normalized"] == {
        "1": {"num": 1, "den": 48000}
    }


def test_normalize_cache_root_file_returns_structured_unavailable_error(
    fragmented_mp4: Path,
    ffmpeg_path: str,
    ffprobe_path: str,
    tmp_path: Path,
) -> None:
    occupied = tmp_path / "normalize-root-file"
    occupied.write_bytes(b"occupied")
    with pytest.raises(MediaError) as exc:
        normalize_fragmented(
            fragmented_mp4,
            cache_root=occupied,
            toolchain=Toolchain.from_paths(ffmpeg_path, ffprobe_path),
        )
    assert exc.value.code == "CACHE_PATH_UNAVAILABLE"
    assert exc.value.diagnostics["reason"] == "not_directory"
