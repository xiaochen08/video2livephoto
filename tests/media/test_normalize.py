from __future__ import annotations

from pathlib import Path

from core.media.normalize import normalize_fragmented
from core.media.toolchain import Toolchain


def test_normalize_fragmented_media_stays_in_cache_and_keeps_source(
    fragmented_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    before = fragmented_mp4.read_bytes()
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
    assert result.validation["frame_index_status"] == "complete"
