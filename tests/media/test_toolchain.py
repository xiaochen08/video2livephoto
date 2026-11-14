from __future__ import annotations

import pytest

from core.media.errors import MediaError
from core.media.toolchain import Toolchain


def test_toolchain_records_versions_and_hashes(
    ffmpeg_path: str, ffprobe_path: str
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    payload = toolchain.to_dict()
    assert payload["ffmpeg"]["version"]
    assert len(payload["ffmpeg"]["sha256"]) == 64
    assert payload["ffprobe"]["version"]
    assert len(payload["ffprobe"]["sha256"]) == 64


def test_toolchain_rejects_hash_mismatch(ffmpeg_path: str, ffprobe_path: str) -> None:
    with pytest.raises(MediaError) as exc:
        Toolchain.from_paths(
            ffmpeg_path,
            ffprobe_path,
            expected_ffmpeg_sha256="0" * 64,
        )
    assert exc.value.code == "TOOLCHAIN_MISMATCH"
