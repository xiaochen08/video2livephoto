from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from core.media.errors import MediaError
from core.media.fragment_inspector import inspect_fragments
from core.media.process import CancellationToken, kill_process
from core.media.source_identity import capture_identity, identities_match
from core.media.toolchain import Toolchain, process_creation_flags
from core.protocol.media import (
    ColorSummary,
    ContainerSummary,
    MediaProbeResult,
    Rational,
    StreamSummary,
)


def _int(value: Any) -> int | None:
    if value is None or value == "" or value == "N/A":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or value == "" or value == "N/A":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rational(value: Any) -> Rational | None:
    if value is None or value == "" or value == "N/A" or value == "0/0":
        return None
    try:
        numerator, denominator = str(value).split("/", 1)
        if int(denominator) == 0:
            return None
        return Rational(int(numerator), int(denominator))
    except (TypeError, ValueError):
        return None


def _mapping(value: Any) -> dict[str, str]:
    return {str(key): str(item) for key, item in (value or {}).items()}


def _color(raw: dict[str, Any]) -> ColorSummary:
    transfer = raw.get("color_transfer") or "unknown"
    primaries = raw.get("color_primaries") or "unknown"
    side_data = raw.get("side_data_list") or []
    side_types = " ".join(
        str(item.get("side_data_type", "")) for item in side_data
    ).lower()
    values = " ".join(
        str(raw.get(key, "")) for key in ("profile", "codec_name", "codec_long_name")
    )
    values = f"{values} {_mapping(raw.get('tags'))}".lower()
    dolby = "dolby" in side_types or "dovi" in values or "dolby" in values
    hdr = transfer in {"smpte2084", "arib-std-b67"} or primaries == "bt2020" or dolby
    log_like = "log" in values or "cineon" in values
    return ColorSummary(
        range=raw.get("color_range") or "unknown",
        space=raw.get("color_space") or "unknown",
        transfer=transfer,
        primaries=primaries,
        chroma_location=raw.get("chroma_location") or "unknown",
        hdr_present=hdr,
        dolby_vision_present=dolby,
        log_like_present=log_like,
    )


def _rotation(raw: dict[str, Any]) -> int | None:
    tags = _mapping(raw.get("tags"))
    value = tags.get("rotate")
    if value is not None:
        try:
            return int(float(value)) % 360
        except ValueError:
            pass
    for item in raw.get("side_data_list") or []:
        if str(item.get("side_data_type", "")).lower() == "display matrix":
            rotation = _float(item.get("rotation"))
            if rotation is not None:
                return int(round(rotation)) % 360
    return None


def _stream(raw: dict[str, Any]) -> StreamSummary:
    side_data = raw.get("side_data_list") or []
    return StreamSummary(
        index=int(raw.get("index", -1)),
        codec_type=str(raw.get("codec_type", "unknown")),
        codec_name=raw.get("codec_name"),
        profile=raw.get("profile"),
        level=_int(raw.get("level")),
        width=_int(raw.get("width")),
        height=_int(raw.get("height")),
        coded_width=_int(raw.get("coded_width")),
        coded_height=_int(raw.get("coded_height")),
        pixel_format=raw.get("pix_fmt"),
        bits_per_raw_sample=_int(raw.get("bits_per_raw_sample")),
        sample_aspect_ratio=_rational(raw.get("sample_aspect_ratio")),
        display_aspect_ratio=_rational(raw.get("display_aspect_ratio")),
        time_base=_rational(raw.get("time_base")),
        start_time=_int(raw.get("start_pts")),
        duration=_int(raw.get("duration_ts")),
        duration_seconds=_float(raw.get("duration")),
        frame_rate_hint=_rational(raw.get("r_frame_rate")),
        avg_frame_rate_hint=_rational(raw.get("avg_frame_rate")),
        rotation=_rotation(raw),
        color=_color(raw),
        sample_rate=_int(raw.get("sample_rate")),
        channels=_int(raw.get("channels")),
        channel_layout=raw.get("channel_layout"),
        sample_format=raw.get("sample_fmt"),
        disposition={str(k): int(v) for k, v in (raw.get("disposition") or {}).items()},
        attached_picture=bool((raw.get("disposition") or {}).get("attached_pic", 0)),
        tags=_mapping(raw.get("tags")),
        side_data_types=tuple(
            str(item.get("side_data_type", "")) for item in side_data
        ),
    )


def _run_probe(
    path: Path,
    toolchain: Toolchain,
    timeout_seconds: float,
    token: CancellationToken | None,
) -> dict[str, Any]:
    args = [
        toolchain.ffprobe.path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_error",
        "-show_format",
        "-show_streams",
        "-show_programs",
        "-show_chapters",
        str(path),
    ]
    process = subprocess.Popen(
        args,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=process_creation_flags(),
    )
    result_queue: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=1)

    def _communicate() -> None:
        stdout, stderr = process.communicate()
        result_queue.put((stdout, stderr))

    reader = threading.Thread(
        target=_communicate, name="m1-ffprobe-communicate", daemon=True
    )
    reader.start()
    started = time.monotonic()
    while True:
        if token is not None and token.cancelled:
            kill_process(process)
            raise MediaError(
                code="CANCELLED",
                stage="probe",
                path=str(path),
                stream_index=None,
                retryable=True,
                message="媒体探测已取消",
            )
        if time.monotonic() - started > timeout_seconds:
            kill_process(process)
            raise MediaError(
                code="FFPROBE_TIMEOUT",
                stage="probe",
                path=str(path),
                stream_index=None,
                retryable=True,
                message="ffprobe 探测超时",
            )
        try:
            stdout, stderr = result_queue.get(timeout=0.05)
            break
        except queue.Empty:
            continue
    if process.returncode != 0:
        raise MediaError(
            code="FFPROBE_FAILED",
            stage="probe",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="ffprobe 无法读取媒体",
            diagnostics={"returncode": process.returncode, "stderr": stderr[-4000:]},
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(
            code="FFPROBE_INVALID_JSON",
            stage="probe",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="ffprobe 返回内容不是有效 JSON",
            diagnostics={"stdout_tail": stdout[-1000:]},
        ) from exc


def probe_media(
    path: str | Path,
    *,
    toolchain: Toolchain | None = None,
    token: CancellationToken | None = None,
    timeout_seconds: float = 30.0,
    include_full_sha256: bool = False,
    selected_video_stream: int | None = None,
    allow_ambiguous: bool = False,
) -> MediaProbeResult:
    source = Path(path)
    toolchain = toolchain or Toolchain.discover()
    before = capture_identity(source, include_full_sha256=include_full_sha256)
    fragment = inspect_fragments(source)
    raw = _run_probe(source, toolchain, timeout_seconds, token)
    after = capture_identity(source, include_full_sha256=include_full_sha256)
    if not identities_match(before, after):
        raise MediaError(
            code="SOURCE_CHANGED",
            stage="probe",
            path=str(source),
            stream_index=None,
            retryable=True,
            message="源文件在探测期间发生变化",
        )
    streams = tuple(_stream(item) for item in raw.get("streams", []))
    attached_pictures = tuple(item for item in streams if item.attached_picture)
    videos = tuple(
        item
        for item in streams
        if item.codec_type == "video" and not item.attached_picture
    )
    if not videos:
        raise MediaError(
            code="NO_VIDEO_STREAM",
            stage="probe",
            path=str(source),
            stream_index=None,
            retryable=False,
            message="媒体中没有可用视频流",
        )
    defaults = tuple(item for item in videos if item.disposition.get("default", 0) == 1)
    if selected_video_stream is not None:
        selected = next((item for item in videos if item.index == int(selected_video_stream)), None)
        if selected is None:
            raise MediaError(
                code="VIDEO_STREAM_NOT_FOUND",
                stage="probe",
                path=str(source),
                stream_index=int(selected_video_stream),
                retryable=False,
                message="用户选择的视频流不存在或不可用",
                diagnostics={"candidate_streams": [item.index for item in videos]},
            )
        candidates = (selected,)
        reason = "user_selection"
    elif len(defaults) > 1 or (len(videos) > 1 and not defaults):
        if not allow_ambiguous:
            raise MediaError(
                code="AMBIGUOUS_VIDEO_STREAM",
                stage="probe",
                path=str(source),
                stream_index=None,
                retryable=False,
                message="媒体包含多个未能唯一确定的视频流，无法安全确定主视频",
                diagnostics={
                    "candidate_streams": [item.index for item in videos],
                    "default_streams": [item.index for item in defaults],
                    "attached_picture_streams": [item.index for item in attached_pictures],
                },
            )
        candidates = videos
        selected = min(candidates, key=lambda item: item.index)
        reason = "ambiguous_unselected"
    else:
        candidates = defaults or videos
        selected = min(candidates, key=lambda item: item.index)
        reason = "default_disposition" if defaults else "lowest_stream_index"
    diagnostics: list[str] = []
    if reason == "ambiguous_unselected":
        diagnostics.append(
            "multiple video streams; user selection is required before analysis"
        )
    elif len(candidates) > 1:
        diagnostics.append(
            f"multiple video streams; selected stream {selected.index} by {reason}"
        )
    if selected.color.transfer == "unknown" or selected.color.primaries == "unknown":
        diagnostics.append("color metadata is incomplete; preserved as unknown")
    raw_format = raw.get("format") or {}
    format_names = tuple(str(raw_format.get("format_name", "")).split(","))
    format_names = tuple(item for item in format_names if item)
    container = ContainerSummary(
        format_names=format_names,
        duration_seconds=_float(raw_format.get("duration")),
        start_time_seconds=_float(raw_format.get("start_time")),
        bit_rate=_int(raw_format.get("bit_rate")),
        tags=_mapping(raw_format.get("tags")),
    )
    return MediaProbeResult(
        schema_version="m1.media.v1",
        source_identity=before,
        container=container,
        streams=streams,
        selected_video_stream=selected.index,
        selected_video_reason=reason,
        video_stream=selected,
        audio_streams=tuple(item for item in streams if item.codec_type == "audio"),
        attached_picture_streams=attached_pictures,
        subtitle_and_data_streams=tuple(
            item
            for item in streams
            if item.codec_type not in {"video", "audio"} and not item.attached_picture
        ),
        color=selected.color,
        fragment=fragment,
        diagnostics=tuple(diagnostics),
        toolchain=toolchain.to_dict(),
    )
