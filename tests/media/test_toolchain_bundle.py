from __future__ import annotations

from pathlib import Path

from core.media.toolchain import Toolchain


def test_toolchain_discover_accepts_explicit_runtime_directory(
    ffmpeg_path: str, ffprobe_path: str, monkeypatch
) -> None:
    runtime = str(Path(ffmpeg_path).parent)
    monkeypatch.setenv("VIDEO2LIVEPHOTO_FFMPEG_DIR", str(runtime))
    result = Toolchain.discover()
    assert result.ffmpeg.path.endswith("ffmpeg.exe")
    assert result.ffprobe.path.endswith("ffprobe.exe")
