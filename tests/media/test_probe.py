from __future__ import annotations

from pathlib import Path

from core.media.probe import probe_media
from core.media.process import CancellationToken
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


def test_probe_cancellation_returns_structured_error(
    small_mp4: Path, ffmpeg_path: str, ffprobe_path: str
) -> None:
    token = CancellationToken()
    token.cancel()
    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    try:
        probe_media(small_mp4, toolchain=toolchain, token=token)
    except Exception as exc:
        assert getattr(exc, "code", None) == "CANCELLED"
    else:
        raise AssertionError("probe should have been cancelled")


def test_probe_excludes_attached_picture_from_primary_video_selection(
    ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    cover = tmp_path / "cover.jpg"
    sample = tmp_path / "multi-video-attached-pic.mp4"
    import subprocess

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
            "color=c=yellow:s=160x90",
            "-frames:v",
            "1",
            str(cover),
        ],
        check=True,
    )
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
            "testsrc2=size=160x90:rate=30",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x90:rate=30",
            "-loop",
            "1",
            "-i",
            str(cover),
            "-t",
            "1",
            "-map",
            "0:v",
            "-map",
            "1:v",
            "-map",
            "2:v",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:v:2",
            "mjpeg",
            "-disposition:v:0",
            "default",
            "-disposition:v:1",
            "0",
            "-disposition:v:2",
            "attached_pic",
            "-metadata:s:v:2",
            "mimetype=image/jpeg",
            str(sample),
        ],
        check=True,
    )
    result = probe_media(
        sample, toolchain=Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    )
    assert result.selected_video_stream == 0
    assert [stream.index for stream in result.attached_picture_streams] == [2]
    assert not any("multiple video streams" in item for item in result.diagnostics)


def test_probe_rejects_multiple_default_video_streams(
    ffmpeg_path: str, ffprobe_path: str, tmp_path: Path
) -> None:
    sample = tmp_path / "ambiguous-default-videos.mp4"
    import subprocess

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
            "testsrc2=size=160x90:rate=30",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:size=160x90:rate=30",
            "-t",
            "1",
            "-map",
            "0:v",
            "-map",
            "1:v",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-disposition:v:0",
            "default",
            "-disposition:v:1",
            "default",
            str(sample),
        ],
        check=True,
    )
    from core.media.errors import MediaError

    try:
        probe_media(
            sample, toolchain=Toolchain.from_paths(ffmpeg_path, ffprobe_path)
        )
    except MediaError as exc:
        assert exc.code == "AMBIGUOUS_VIDEO_STREAM"
        assert exc.diagnostics["default_streams"] == [0, 1]
        selected = probe_media(
            sample,
            toolchain=Toolchain.from_paths(ffmpeg_path, ffprobe_path),
            selected_video_stream=1,
        )
        assert selected.selected_video_stream == 1
        assert selected.selected_video_reason == "user_selection"
    else:
        raise AssertionError("multiple default video streams must be refused")


def test_probe_rejects_multiple_video_streams_without_default(
    ffmpeg_path: str, ffprobe_path: str, tmp_path: Path, monkeypatch
) -> None:
    sample = tmp_path / "ambiguous-no-default-videos.mp4"
    import subprocess

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
            "testsrc2=size=160x90:rate=30",
            "-f",
            "lavfi",
            "-i",
            "color=c=green:size=160x90:rate=30",
            "-t",
            "1",
            "-map",
            "0:v",
            "-map",
            "1:v",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-disposition:v:0",
            "0",
            "-disposition:v:1",
            "0",
            str(sample),
        ],
        check=True,
    )
    from copy import deepcopy

    from core.media.errors import MediaError
    import core.media.probe as probe_module

    toolchain = Toolchain.from_paths(ffmpeg_path, ffprobe_path)
    raw = deepcopy(probe_module._run_probe(sample, toolchain, 30.0, None))
    for stream in raw["streams"]:
        if stream.get("codec_type") == "video":
            stream.setdefault("disposition", {})["default"] = 0
    monkeypatch.setattr(
        probe_module,
        "_run_probe",
        lambda *_args, **_kwargs: raw,
    )

    try:
        probe_media(sample, toolchain=toolchain)
    except MediaError as exc:
        assert exc.code == "AMBIGUOUS_VIDEO_STREAM"
        assert exc.diagnostics["default_streams"] == []
        provisional = probe_media(
            sample,
            toolchain=toolchain,
            allow_ambiguous=True,
        )
        assert provisional.selected_video_reason == "ambiguous_unselected"
    else:
        raise AssertionError("multiple video streams without a default must be refused")
