from __future__ import annotations

from pathlib import Path

from core.media.probe import probe_media
from core.media.toolchain import Toolchain


def test_probe_reports_streams_colors_and_selected_video(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str
) -> None:
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    result = probe_media(small_mp4, toolchain=toolchain)
    assert result.schema_version == "m1.media.v1"
    assert result.container.format_names
    assert result.selected_video_stream == 0
    assert result.video_stream.codec_name == "h264"
    assert result.video_stream.width == 320
    assert result.video_stream.height == 240
    assert result.audio_streams[0].codec_name == "aac"
    assert result.color.transfer in {"unknown", "bt709"}
    assert result.fragment.is_fragmented is False


def test_probe_does_not_treat_extension_as_container_type(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    renamed = tmp_path / "renamed.MOV"
    renamed.write_bytes(small_mp4.read_bytes())
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    result = probe_media(renamed, toolchain=toolchain)
    assert result.container.format_names
    assert result.source_identity.canonical_path.endswith("renamed.MOV")
