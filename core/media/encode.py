from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Sequence

from core.media.errors import MediaError
from core.media.color import color_override_metadata
from core.media.process import CancellationToken, kill_process
from core.media.probe import probe_media
from core.media.source_identity import (
    capture_identity,
    identities_match,
    paths_refer_same_file,
)
from core.media.toolchain import Toolchain, process_creation_flags
from core.protocol.media import FrameRef, Rational, SourceIdentity


@dataclass(frozen=True)
class SegmentEncodeResult:
    """Verified output for one user-confirmed display-frame range."""

    status: str
    source_identity: SourceIdentity
    output_path: str | None
    start_display_index: int
    end_display_index: int
    frame_count: int
    start_pts: int | None
    end_pts: int | None
    time_base: Rational
    encoder: str | None
    gpu_attempted: tuple[str, ...]
    gpu_fallback: bool
    audio_enabled: bool
    color_mode: str
    color_transform: str
    validation: dict[str, object] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _fraction_seconds(value: int | None, time_base: Rational) -> Fraction | None:
    if value is None:
        return None
    return Fraction(value * time_base.num, time_base.den)


def _decimal_seconds(value: Fraction) -> str:
    # FFmpeg accepts decimal seconds.  Twelve fractional digits keep a 1/15360
    # time base exact enough while avoiding a float round trip in the command.
    return f"{float(value):.12f}".rstrip("0").rstrip(".") or "0"


def _run_process(
    args: Sequence[str],
    *,
    token: CancellationToken,
    timeout_seconds: float,
    progress_callback: Callable[[int], None] | None = None,
    startup_timeout_seconds: float | None = None,
    progress_timeout_seconds: float | None = None,
) -> tuple[int, str, str]:
    process = subprocess.Popen(
        list(args),
        shell=False,
        # The desktop service itself is a JSONL process.  Never let FFmpeg
        # inherit that live stdin pipe: it can consume IPC bytes or wait on
        # the pipe instead of starting the encode.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=process_creation_flags(),
    )
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    progress_seen = False
    last_progress_at = time.monotonic()

    def _report_progress(frame: int) -> None:
        nonlocal progress_seen, last_progress_at
        progress_seen = True
        last_progress_at = time.monotonic()
        if progress_callback is not None:
            progress_callback(frame)

    def _read_stdout() -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            stdout_parts.append(line)
            if progress_callback is None:
                continue
            key, separator, raw_value = line.strip().partition("=")
            if key != "frame" or not separator:
                continue
            try:
                _report_progress(max(0, int(raw_value)))
            except (TypeError, ValueError):
                continue

    def _read_stderr() -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            stderr_parts.append(line)

    stdout_reader = threading.Thread(target=_read_stdout, daemon=True)
    stderr_reader = threading.Thread(target=_read_stderr, daemon=True)
    stdout_reader.start()
    stderr_reader.start()
    started = time.monotonic()
    while process.poll() is None:
        if token.cancelled:
            kill_process(process)
            stdout_reader.join(timeout=2)
            stderr_reader.join(timeout=2)
            raise MediaError(
                code="CANCELLED",
                stage="encode",
                path=None,
                stream_index=None,
                retryable=True,
                message="视频分段编码已取消",
            )
        if time.monotonic() - started > timeout_seconds:
            kill_process(process)
            stdout_reader.join(timeout=2)
            stderr_reader.join(timeout=2)
            raise MediaError(
                code="ENCODE_TIMEOUT",
                stage="encode",
                path=None,
                stream_index=None,
                retryable=True,
                message="视频分段编码超时",
                diagnostics={"timeout_seconds": timeout_seconds},
            )
        elapsed_since_progress = time.monotonic() - last_progress_at
        if startup_timeout_seconds is not None and not progress_seen and elapsed_since_progress > startup_timeout_seconds:
            kill_process(process)
            stdout_reader.join(timeout=2)
            stderr_reader.join(timeout=2)
            raise MediaError(
                code="ENCODE_STARTUP_TIMEOUT",
                stage="encode",
                path=None,
                stream_index=None,
                retryable=True,
                message="编码器启动后没有产生帧进度",
                diagnostics={"timeout_seconds": startup_timeout_seconds},
            )
        if progress_timeout_seconds is not None and progress_seen and elapsed_since_progress > progress_timeout_seconds:
            kill_process(process)
            stdout_reader.join(timeout=2)
            stderr_reader.join(timeout=2)
            raise MediaError(
                code="ENCODE_STALLED",
                stage="encode",
                path=None,
                stream_index=None,
                retryable=True,
                message="编码器长时间没有新的帧进度",
                diagnostics={"timeout_seconds": progress_timeout_seconds},
            )
        time.sleep(0.05)
    stdout_reader.join(timeout=1)
    stderr_reader.join(timeout=1)
    return process.wait(), "".join(stdout_parts), "".join(stderr_parts)


def _validate_output(
    path: Path,
    *,
    expected_frames: int,
    video_stream_index: int,
    audio_enabled: bool,
    toolchain: Toolchain,
    token: CancellationToken,
    timeout_seconds: float,
) -> dict[str, object]:
    args = [
        toolchain.ffprobe.path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        "-show_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=index,codec_type,codec_name,time_base,width,height,pix_fmt:frame=pts,best_effort_timestamp,pict_type",
        str(path),
    ]
    code, stdout, stderr = _run_process(
        args, token=token, timeout_seconds=timeout_seconds
    )
    if code != 0:
        raise MediaError(
            code="OUTPUT_INVALID",
            stage="encode",
            path=str(path),
            stream_index=video_stream_index,
            retryable=False,
            message="分段输出无法被 ffprobe 解码",
            diagnostics={"returncode": code, "stderr": stderr[-4000:]},
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(
            code="OUTPUT_INVALID",
            stage="encode",
            path=str(path),
            stream_index=video_stream_index,
            retryable=False,
            message="分段输出的 ffprobe 结果无效",
        ) from exc
    streams = payload.get("streams") or []
    frames = payload.get("frames") or []
    if not streams or len(frames) != expected_frames:
        raise MediaError(
            code="FRAME_BOUNDARY_MISMATCH",
            stage="encode",
            path=str(path),
            stream_index=video_stream_index,
            retryable=False,
            message="输出显示帧数量与确认范围不一致",
            diagnostics={
                "expected_frames": expected_frames,
                "actual_frames": len(frames),
            },
        )
    audio_probe_args = [
        toolchain.ffprobe.path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index,codec_type,codec_name,time_base",
        str(path),
    ]
    audio_code, audio_stdout, audio_stderr = _run_process(
        audio_probe_args, token=token, timeout_seconds=timeout_seconds
    )
    if audio_code != 0:
        raise MediaError(
            code="OUTPUT_INVALID",
            stage="encode",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="无法读取分段输出的音频流",
            diagnostics={"returncode": audio_code, "stderr": audio_stderr[-2000:]},
        )
    try:
        output_audio = json.loads(audio_stdout).get("streams") or []
    except json.JSONDecodeError as exc:
        raise MediaError(
            code="OUTPUT_INVALID",
            stage="encode",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="分段输出的音频流结果无效",
        ) from exc
    if audio_enabled and not output_audio:
        raise MediaError(
            code="AUDIO_MISSING",
            stage="encode",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="要求保留音频但输出没有音轨",
        )
    if not audio_enabled and output_audio:
        raise MediaError(
            code="AUDIO_UNEXPECTED",
            stage="encode",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="静音输出仍包含音轨",
        )
    return {
        "frame_count": len(frames),
        "audio_stream_count": len(output_audio),
        "video_stream": streams[0],
        "first_pts": frames[0].get("best_effort_timestamp", frames[0].get("pts")),
        "last_pts": frames[-1].get("best_effort_timestamp", frames[-1].get("pts")),
        "format": payload.get("format", {}),
    }


def _color_filter(
    probe,
    color_mode: str,
    source_color_override: str | None = None,
) -> tuple[str | None, str, dict[str, str]]:
    color = probe.video_stream.color
    override = color_override_metadata(source_color_override)
    if source_color_override is not None and override is None:
        raise MediaError(
            code="INVALID_COLOR_OVERRIDE",
            stage="encode",
            path=None,
            stream_index=probe.selected_video_stream,
            retryable=False,
            message="导入时选择的色彩类型不受支持。",
            diagnostics={"color_override": source_color_override},
        )
    if override is not None:
        color = replace(color, **override)
    unknown = color.transfer in {None, "", "unknown"} or color.primaries in {
        None,
        "",
        "unknown",
    }
    if color_mode not in {"auto", "sdr", "hdr", "warn"}:
        raise MediaError(
            code="INVALID_COLOR_MODE",
            stage="encode",
            path=None,
            stream_index=probe.selected_video_stream,
            retryable=False,
            message="未知的色彩输出模式",
            diagnostics={"color_mode": color_mode},
        )
    output_metadata: dict[str, str] = {}
    if override is not None:
        output_metadata = {
            "color_range": str(override["range"]),
            "colorspace": str(override["space"]),
            "color_primaries": str(override["primaries"]),
            "color_trc": str(override["transfer"]),
        }
    if unknown and color_mode != "warn":
        raise MediaError(
            code="UNKNOWN_COLOR_METADATA",
            stage="encode",
            path=None,
            stream_index=probe.selected_video_stream,
            retryable=False,
            message="输入色彩元数据不完整，无法安全选择转换路径",
            diagnostics={"transfer": color.transfer, "primaries": color.primaries},
        )
    if color_mode == "hdr":
        return None, "preserve-hdr", output_metadata
    if color_mode == "warn":
        return None, "unknown-preserved-with-warning" if unknown else "preserved", output_metadata
    if color.hdr_present or color_mode == "sdr":
        # Real tone mapping plus matrix conversion.  If the frozen ffmpeg build
        # lacks zscale/tonemap, the command fails and the caller reports it.
        if color.hdr_present:
            return (
                "zscale=t=linear:npl=100,format=gbrpf32le,"
                "tonemap=mobius:desat=0,"
                "zscale=primaries=bt709:transfer=bt709:matrix=bt709:range=tv,"
                "format=yuv420p",
                "hdr-to-rec709-sdr",
                {"color_range": "tv", "colorspace": "bt709", "color_primaries": "bt709", "color_trc": "bt709"},
            )
        return None, "sdr-assumed-rec709" if source_color_override == "sdr_rec709" else "sdr-preserved", output_metadata
    return None, "sdr-preserved", output_metadata


def _h264_color_bitstream_filter(metadata: dict[str, str]) -> str | None:
    primaries = {"bt709": "1", "bt2020": "9"}.get(metadata.get("color_primaries", ""))
    transfer = {"bt709": "1", "smpte2084": "16", "arib-std-b67": "18"}.get(metadata.get("color_trc", ""))
    matrix = {"bt709": "1", "bt2020nc": "9"}.get(metadata.get("colorspace", ""))
    range_flag = {"tv": "0", "pc": "1"}.get(metadata.get("color_range", ""))
    if None in {primaries, transfer, matrix, range_flag}:
        return None
    return (
        "h264_metadata="
        f"video_full_range_flag={range_flag}:"
        f"colour_primaries={primaries}:"
        f"transfer_characteristics={transfer}:"
        f"matrix_coefficients={matrix}"
    )


def _validate_frame_range(
    frames: Sequence[FrameRef], start_display_index: int, end_display_index: int
) -> tuple[tuple[FrameRef, ...], FrameRef, FrameRef, int, int]:
    if start_display_index < 0 or end_display_index <= start_display_index:
        raise MediaError(
            code="INVALID_FRAME_RANGE",
            stage="encode",
            path=None,
            stream_index=None,
            retryable=False,
            message="帧范围必须为非空且左闭右开",
        )
    selected = tuple(
        frame
        for frame in frames
        if start_display_index <= frame.display_index < end_display_index
    )
    expected = end_display_index - start_display_index
    if len(selected) != expected or any(
        frame.display_index != start_display_index + i
        for i, frame in enumerate(selected)
    ):
        raise MediaError(
            code="NON_CONTIGUOUS_FRAME_RANGE",
            stage="encode",
            path=None,
            stream_index=None,
            retryable=False,
            message="确认的显示帧范围不连续或不完整",
        )
    if any(frame.pts is None and frame.best_effort_pts is None for frame in selected):
        raise MediaError(
            code="MISSING_FRAME_PTS",
            stage="encode",
            path=None,
            stream_index=selected[0].stream_index,
            retryable=False,
            message="精确分段需要每一帧都有可用显示 PTS",
        )
    return selected, selected[0], selected[-1], expected, selected[0].stream_index


def encode_segment(
    source_path: str | Path,
    frames: Iterable[FrameRef],
    *,
    start_display_index: int,
    end_display_index: int,
    output_path: str | Path,
    toolchain: Toolchain | None = None,
    audio_enabled: bool = True,
    color_mode: str = "auto",
    prefer_gpu: bool = True,
    gpu_encoders: Sequence[str] = ("h264_nvenc", "h264_qsv", "h264_amf"),
    cpu_encoder: str = "libx264",
    token: CancellationToken | None = None,
    timeout_seconds: float = 3600.0,
    video_stream_index: int | None = None,
    source_color_override: str | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> SegmentEncodeResult:
    source = Path(source_path)
    destination = Path(output_path)
    toolchain = toolchain or Toolchain.discover()
    token = token or CancellationToken()
    if paths_refer_same_file(source, destination):
        raise MediaError(
            code="PATH_CONFLICT",
            stage="encode",
            path=str(source),
            stream_index=None,
            retryable=False,
            message="编码输出路径不能与源文件相同",
        )
    source_identity = capture_identity(source)
    frame_list = tuple(frames)
    selected, first, last, frame_count, stream_index = _validate_frame_range(
        frame_list, start_display_index, end_display_index
    )
    time_base = first.time_base
    first_pts = (
        first.best_effort_pts if first.best_effort_pts is not None else first.pts
    )
    last_pts = last.best_effort_pts if last.best_effort_pts is not None else last.pts
    if first_pts is None or last_pts is None:
        raise MediaError(
            code="MISSING_FRAME_PTS",
            stage="encode",
            path=str(source),
            stream_index=stream_index,
            retryable=False,
            message="精确分段的起止帧缺少 PTS",
        )
    duration_ticks = last.duration
    end_pts = (
        last_pts + duration_ticks if duration_ticks and duration_ticks > 0 else last_pts
    )
    probe = probe_media(
        source,
        toolchain=toolchain,
        token=token,
        selected_video_stream=stream_index if video_stream_index is None else video_stream_index,
    )
    # "Preserve audio" means preserve every source audio stream; a silent
    # source is a valid input and must not fail merely because no audio stream
    # exists to map.
    effective_audio = audio_enabled and bool(probe.audio_streams)
    filter_graph, color_transform, color_metadata = _color_filter(
        probe, color_mode, source_color_override
    )
    start_seconds = _fraction_seconds(first_pts, time_base)
    end_seconds = _fraction_seconds(end_pts, time_base)
    if start_seconds is None or end_seconds is None:
        raise MediaError(
            code="MISSING_FRAME_PTS",
            stage="encode",
            path=str(source),
            stream_index=stream_index,
            retryable=False,
            message="无法将帧范围转换为时间轴",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".v1-encode-{uuid.uuid4().hex}"
    staging.mkdir(parents=False, exist_ok=False)
    gpu_attempted: list[str] = []
    selected_encoder: str | None = None
    gpu_fallback = False
    validation: dict[str, object] = {}
    diagnostics: list[str] = []
    reported_progress = 0.0

    def report_frame_progress(done: int) -> None:
        nonlocal reported_progress
        if progress_callback is None:
            return
        ratio = min(max(done / frame_count, 0.0), 1.0)
        if ratio <= reported_progress:
            return
        reported_progress = ratio
        progress_callback(ratio)

    seek_frame = next(
        (
            candidate
            for candidate in reversed(
                tuple(
                    candidate
                    for candidate in frame_list
                    if candidate.display_index <= first.display_index
                )
            )
            if candidate.keyframe
            and (candidate.pts is not None or candidate.best_effort_pts is not None)
        ),
        None,
    )
    seek_pts = (
        seek_frame.best_effort_pts
        if seek_frame is not None and seek_frame.best_effort_pts is not None
        else seek_frame.pts if seek_frame is not None else None
    )
    seek_seconds = (
        _fraction_seconds(seek_pts, seek_frame.time_base)
        if seek_frame is not None and seek_pts is not None
        else None
    )
    try:
        candidate_encoders = list(gpu_encoders) if prefer_gpu else []
        candidate_encoders.append(cpu_encoder)
        for index, encoder in enumerate(candidate_encoders):
            is_gpu = encoder != cpu_encoder
            if is_gpu:
                gpu_attempted.append(encoder)
            partial = staging / f"segment-{index}.partial.mp4"
            args = [
                toolchain.ffmpeg.path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-copyts",
            ]
            if seek_seconds is not None and seek_seconds > 0:
                args.extend(["-ss", _decimal_seconds(seek_seconds)])
            args.extend(
                [
                    "-i",
                    str(source),
                    "-map",
                    f"0:{stream_index}",
                    "-map",
                    "0:a?" if effective_audio else "-0:a?",
                    "-vf",
                    (
                        f"select='gte(pts\\,{first_pts})*lt(pts\\,{end_pts})',"
                        "setpts=PTS-STARTPTS"
                        + (f",{filter_graph}" if filter_graph else "")
                    ),
                    "-fps_mode",
                    "vfr",
                    "-c:v",
                    encoder,
                ]
            )
            if encoder == "h264_nvenc":
                # p2 keeps the source-quality path while avoiding the much
                # slower default NVENC preset on long 4K segments.
                args.extend(["-preset", "p2"])
            args.extend(
                [
                    "-pix_fmt",
                    "yuv420p",
                    *sum(([f"-{key}", value] for key, value in color_metadata.items()), []),
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    "-progress",
                    "pipe:1",
                    "-nostats",
                    str(partial),
                ]
            )
            color_bitstream_filter = _h264_color_bitstream_filter(color_metadata)
            if color_bitstream_filter:
                output_index = args.index(str(partial))
                args[output_index:output_index] = ["-bsf:v", color_bitstream_filter]
            if effective_audio:
                # Insert the audio trim immediately before the codec options;
                # this avoids creating an unconnected filter when the caller
                # explicitly requests a silent segment.
                insert_at = args.index("-c:v")
                args[insert_at:insert_at] = [
                    "-af",
                    f"atrim=start={_decimal_seconds(start_seconds)}:"
                    f"end={_decimal_seconds(end_seconds)},asetpts=PTS-STARTPTS",
                ]
            try:
                returncode, _stdout, stderr = _run_process(
                    args,
                    token=token,
                    timeout_seconds=timeout_seconds,
                    progress_callback=report_frame_progress,
                    startup_timeout_seconds=30.0 if is_gpu else 120.0,
                    progress_timeout_seconds=90.0,
                )
            except MediaError as exc:
                if not is_gpu or exc.code == "CANCELLED":
                    raise
                diagnostics.append(f"encoder {encoder} stalled: {exc}")
                partial.unlink(missing_ok=True)
                gpu_fallback = True
                continue
            if returncode != 0 or not partial.exists() or partial.stat().st_size == 0:
                diagnostics.append(f"encoder {encoder} failed: {stderr[-1000:]}")
                partial.unlink(missing_ok=True)
                if is_gpu:
                    gpu_fallback = True
                    continue
                raise MediaError(
                    code="ENCODE_FAILED",
                    stage="encode",
                    path=str(source),
                    stream_index=stream_index,
                    retryable=True,
                    message="CPU 编码失败",
                    diagnostics={"stderr": stderr[-4000:], "encoders": diagnostics},
                )
            try:
                validation = _validate_output(
                    partial,
                    expected_frames=frame_count,
                    video_stream_index=stream_index,
                    audio_enabled=effective_audio,
                    toolchain=toolchain,
                    token=token,
                    timeout_seconds=min(timeout_seconds, 300.0),
                )
            except MediaError as exc:
                diagnostics.append(f"encoder {encoder} output invalid: {exc}")
                partial.unlink(missing_ok=True)
                if is_gpu:
                    gpu_fallback = True
                    continue
                raise
            after = capture_identity(source)
            if not identities_match(source_identity, after):
                partial.unlink(missing_ok=True)
                raise MediaError(
                    code="SOURCE_CHANGED",
                    stage="encode",
                    path=str(source),
                    stream_index=stream_index,
                    retryable=True,
                    message="编码期间源文件发生变化，已拒绝提交输出",
                )
            selected_encoder = encoder
            os.replace(partial, destination)
            if progress_callback is not None:
                progress_callback(1.0)
            break
        if selected_encoder is None:
            raise MediaError(
                code="ENCODE_FAILED",
                stage="encode",
                path=str(source),
                stream_index=stream_index,
                retryable=True,
                message="没有可用的视频编码器",
                diagnostics={"encoders": diagnostics},
            )
        validation["source_sha256"] = (
            source_identity.full_sha256
            or capture_identity(source, include_full_sha256=True).full_sha256
        )
        validation["requested_frame_count"] = frame_count
        validation["audio_requested"] = audio_enabled
        validation["audio_effective"] = effective_audio
        validation["source_frame_range"] = {
            "start_display_index": start_display_index,
            "end_display_index": end_display_index,
            "first_pts": first_pts,
            "last_pts": last_pts,
            "end_pts": end_pts,
            "time_base": {"num": time_base.num, "den": time_base.den},
        }
        return SegmentEncodeResult(
            status="complete",
            source_identity=source_identity,
            output_path=str(destination),
            start_display_index=start_display_index,
            end_display_index=end_display_index,
            frame_count=frame_count,
            start_pts=first_pts,
            end_pts=end_pts,
            time_base=time_base,
            encoder=selected_encoder,
            gpu_attempted=tuple(gpu_attempted),
            gpu_fallback=gpu_fallback,
            audio_enabled=audio_enabled,
            color_mode=color_mode,
            color_transform=color_transform,
            validation=validation,
            diagnostics=tuple(diagnostics),
        )
    except Exception:
        if destination.exists() and selected_encoder is None:
            # Never remove an existing successful target on a failed retry.
            pass
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


__all__ = ["SegmentEncodeResult", "encode_segment"]
