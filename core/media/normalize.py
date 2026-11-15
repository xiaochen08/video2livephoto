from __future__ import annotations

import subprocess
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from core.media.errors import MediaError
from core.media.fragment_inspector import inspect_fragments
from core.media.frame_index import build_frame_index
from core.media.probe import probe_media
from core.media.process import CancellationToken, kill_process
from core.media.source_identity import (
    capture_identity,
    identities_match,
    paths_refer_same_file,
)
from core.media.toolchain import ProcessMemorySampler, Toolchain, process_creation_flags
from core.protocol.media import NormalizedMediaRef


def _stream_signature(result) -> list[tuple[object, ...]]:
    return [
        (
            stream.codec_type,
            stream.codec_name,
            stream.profile,
            stream.width,
            stream.height,
            stream.pixel_format,
            stream.time_base.num if stream.time_base else None,
            stream.time_base.den if stream.time_base else None,
        )
        for stream in result.streams
    ]


def _read_pts(index_path: str | None) -> list[int | None]:
    if not index_path:
        return []
    with sqlite3.connect(index_path) as db:
        return [
            row[0]
            for row in db.execute("SELECT pts FROM frames ORDER BY display_index")
        ]


def _read_audio_packets(
    path: Path,
    toolchain: Toolchain,
    timeout_seconds: float,
    token: CancellationToken | None = None,
) -> dict[int, list[tuple[int | None, int | None, int | None]]]:
    token = token or CancellationToken()
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [
                toolchain.ffprobe.path,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_packets",
                "-show_entries",
                "packet=stream_index,pts,dts,duration:packet_side_data=",
                "-of",
                "compact=p=0:nk=0",
                str(path),
            ],
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=process_creation_flags(),
        )
    except OSError as exc:
        raise MediaError(
            code="FFPROBE_FAILED",
            stage="normalize",
            path=str(path),
            stream_index=None,
            retryable=True,
            message="无法启动用于音频时间轴校验的 ffprobe",
            diagnostics={"error": str(exc)},
        ) from exc
    started = time.monotonic()
    result: dict[str, str] = {}

    def communicate() -> None:
        stdout, stderr = process.communicate()
        result["stdout"], result["stderr"] = stdout, stderr

    reader = threading.Thread(target=communicate, daemon=True)
    reader.start()
    try:
        while reader.is_alive():
            if token.cancelled:
                kill_process(process)
                reader.join(timeout=2)
                raise MediaError(
                    code="CANCELLED",
                    stage="normalize",
                    path=str(path),
                    stream_index=None,
                    retryable=True,
                    message="读取音频包时间轴已取消",
                )
            if time.monotonic() - started > timeout_seconds:
                kill_process(process)
                reader.join(timeout=2)
                raise MediaError(
                    code="FFPROBE_TIMEOUT",
                    stage="normalize",
                    path=str(path),
                    stream_index=None,
                    retryable=True,
                    message="读取音频包时间轴超时",
                    diagnostics={"timeout_seconds": timeout_seconds},
                )
            time.sleep(0.05)
        reader.join(timeout=1)
    finally:
        if process.poll() is None:
            kill_process(process)
        reader.join(timeout=2)
    stdout = result.get("stdout", "")
    stderr = result.get("stderr", "")
    if process.returncode != 0:
        raise MediaError(
            code="FFPROBE_FAILED",
            stage="normalize",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="无法读取规范化校验所需的音频包时间轴",
            diagnostics={
                "returncode": process.returncode,
                "stderr": stderr[-4000:],
            },
        )
    packets: dict[int, list[tuple[int | None, int | None, int | None]]] = {}
    for line in stdout.splitlines():
        fields = {
            key: value
            for token in line.split("|")
            if "=" in token
            for key, value in [token.split("=", 1)]
        }
        if fields.get("stream_index") is None:
            continue

        def _int(value: str | None) -> int | None:
            if value in (None, "", "N/A"):
                return None
            return int(value)

        index = int(fields["stream_index"])
        packets.setdefault(index, []).append(
            (
                _int(fields.get("pts")),
                _int(fields.get("dts")),
                _int(fields.get("duration")),
            )
        )
    return packets


def _compare_audio_packets(
    source: dict[int, list[tuple[int | None, int | None, int | None]]],
    output: dict[int, list[tuple[int | None, int | None, int | None]]],
) -> dict[str, dict[str, int | None]]:
    if set(source) != set(output):
        raise MediaError(
            code="NORMALIZATION_AUDIO_MISMATCH",
            stage="normalize",
            path=None,
            stream_index=None,
            retryable=False,
            message="规范化前后的音频流集合不一致",
            diagnostics={
                "source_streams": sorted(source),
                "output_streams": sorted(output),
            },
        )
    report: dict[str, dict[str, int | None]] = {}
    for stream_index in sorted(source):
        source_packets = source[stream_index]
        output_packets = output[stream_index]
        if len(source_packets) != len(output_packets):
            raise MediaError(
                code="NORMALIZATION_AUDIO_MISMATCH",
                stage="normalize",
                path=None,
                stream_index=stream_index,
                retryable=False,
                message="规范化前后的音频包数量不一致",
                diagnostics={
                    "source_count": len(source_packets),
                    "output_count": len(output_packets),
                },
            )
        offsets = {
            output_pts - source_pts
            for source_packet, output_packet in zip(source_packets, output_packets)
            for source_pts, output_pts in [(source_packet[0], output_packet[0])]
            if source_pts is not None and output_pts is not None
        }
        if len(offsets) > 1:
            raise MediaError(
                code="NORMALIZATION_AUDIO_MISMATCH",
                stage="normalize",
                path=None,
                stream_index=stream_index,
                retryable=False,
                message="规范化前后的音频 PTS 偏移不一致",
                diagnostics={"offsets": sorted(offsets)},
            )
        report[str(stream_index)] = {
            "packet_count": len(source_packets),
            "pts_offset": next(iter(offsets)) if offsets else None,
        }
    return report


def _time_base_payload(stream) -> dict[str, int] | None:
    if stream.time_base is None:
        return None
    return {"num": stream.time_base.num, "den": stream.time_base.den}


def _timestamp_seconds(value: int | None, stream) -> float | None:
    if value is None or stream.time_base is None:
        return None
    return value * stream.time_base.num / stream.time_base.den


def _first_packet_pts(
    packets: list[tuple[int | None, int | None, int | None]],
) -> int | None:
    return next((packet[0] for packet in packets if packet[0] is not None), None)


def _compare_audio_video_sync(
    source_probe,
    output_probe,
    source_index,
    output_index,
    source_audio_packets: dict[int, list[tuple[int | None, int | None, int | None]]],
    output_audio_packets: dict[int, list[tuple[int | None, int | None, int | None]]],
) -> dict[str, dict[str, float | None]]:
    source_streams = {stream.index: stream for stream in source_probe.audio_streams}
    output_streams = {stream.index: stream for stream in output_probe.audio_streams}
    report: dict[str, dict[str, float | None]] = {}
    for stream_index in sorted(source_streams.keys() | output_streams.keys()):
        source_stream = source_streams.get(stream_index)
        output_stream = output_streams.get(stream_index)
        source_audio_pts = _first_packet_pts(source_audio_packets.get(stream_index, []))
        output_audio_pts = _first_packet_pts(output_audio_packets.get(stream_index, []))
        source_audio_start = _timestamp_seconds(source_audio_pts, source_stream)
        output_audio_start = _timestamp_seconds(output_audio_pts, output_stream)
        source_video_start = _timestamp_seconds(
            source_index.first_pts, source_probe.video_stream
        )
        output_video_start = _timestamp_seconds(
            output_index.first_pts, output_probe.video_stream
        )
        source_delta = (
            source_audio_start - source_video_start
            if source_audio_start is not None and source_video_start is not None
            else None
        )
        output_delta = (
            output_audio_start - output_video_start
            if output_audio_start is not None and output_video_start is not None
            else None
        )
        report[str(stream_index)] = {
            "source_audio_minus_video_seconds": source_delta,
            "normalized_audio_minus_video_seconds": output_delta,
            "change_seconds": (
                output_delta - source_delta
                if source_delta is not None and output_delta is not None
                else None
            ),
        }
    return report


def normalize_fragmented(
    path: str | Path,
    *,
    cache_root: str | Path,
    toolchain: Toolchain | None = None,
    token: CancellationToken | None = None,
    timeout_seconds: float = 3600.0,
) -> NormalizedMediaRef:
    source = Path(path).resolve(strict=True)
    toolchain = toolchain or Toolchain.discover()
    token = token or CancellationToken()
    source_identity = capture_identity(source)
    fragment = inspect_fragments(source)
    if not fragment.is_fragmented:
        return NormalizedMediaRef(
            status="direct",
            source_identity=source_identity,
            normalized_path=None,
            reason="input is already a non-fragmented container",
            source_timeline={},
            validation={"status": "not_needed"},
            cache_key=None,
        )

    root = Path(cache_root).resolve()
    try:
        if root.exists() and not root.is_dir():
            raise MediaError(
                code="CACHE_PATH_UNAVAILABLE",
                stage="normalize",
                path=str(root),
                stream_index=None,
                retryable=True,
                message="规范化缓存根路径不是目录",
                diagnostics={"reason": "not_directory"},
            )
        root.mkdir(parents=True, exist_ok=True)
        work = root / f"normalize-{uuid.uuid4().hex}"
        work.mkdir()
    except MediaError:
        raise
    except OSError as exc:
        raise MediaError(
            code="CACHE_PATH_UNAVAILABLE",
            stage="normalize",
            path=str(root),
            stream_index=None,
            retryable=True,
            message="无法创建规范化缓存目录",
            diagnostics={"errno": exc.errno, "error": str(exc)},
        ) from exc
    partial = work / "normalized.partial.mp4"
    final = work / "normalized.mp4"
    if paths_refer_same_file(source, final):
        raise MediaError(
            code="PATH_CONFLICT",
            stage="normalize",
            path=str(source),
            stream_index=None,
            retryable=False,
            message="规范化输出路径不能与源文件相同",
        )

    source_probe = probe_media(source, toolchain=toolchain, token=token)
    source_index = build_frame_index(
        source,
        cache_root=work / "source-index",
        toolchain=toolchain,
        token=token,
        timeout_seconds=timeout_seconds,
    )
    source_audio_packets = _read_audio_packets(
        source, toolchain, min(timeout_seconds, 120.0), token
    )
    args = [
        toolchain.ffmpeg.path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(partial),
    ]
    started = time.perf_counter()
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
    memory_sampler = ProcessMemorySampler(process.pid)
    memory_sampler.start()
    try:
        while process.poll() is None:
            if token.cancelled:
                process.kill()
                process.wait(timeout=10)
                partial.unlink(missing_ok=True)
                raise MediaError(
                    code="CANCELLED",
                    stage="normalize",
                    path=str(source),
                    stream_index=None,
                    retryable=True,
                    message="fMP4 规范化已取消",
                )
            if time.perf_counter() - started > timeout_seconds:
                process.kill()
                process.wait(timeout=10)
                partial.unlink(missing_ok=True)
                raise MediaError(
                    code="FFMPEG_TIMEOUT",
                    stage="normalize",
                    path=str(source),
                    stream_index=None,
                    retryable=True,
                    message="fMP4 规范化超时",
                )
            time.sleep(0.05)
        stderr = process.stderr.read() if process.stderr else ""
        if process.returncode != 0:
            partial.unlink(missing_ok=True)
            raise MediaError(
                code="FFMPEG_FAILED",
                stage="normalize",
                path=str(source),
                stream_index=None,
                retryable=False,
                message="FFmpeg 无重编码规范化失败",
                diagnostics={
                    "returncode": process.returncode,
                    "stderr": stderr[-4000:],
                },
            )
        if not partial.exists() or partial.stat().st_size == 0:
            raise MediaError(
                code="NORMALIZATION_EMPTY",
                stage="normalize",
                path=str(source),
                stream_index=None,
                retryable=False,
                message="FFmpeg 未生成有效缓存文件",
            )
        output_fragment = inspect_fragments(partial)
        if output_fragment.is_fragmented:
            partial.unlink(missing_ok=True)
            raise MediaError(
                code="NORMALIZATION_STILL_FRAGMENTED",
                stage="normalize",
                path=str(source),
                stream_index=None,
                retryable=False,
                message="规范化结果仍是分片媒体",
            )
        output_probe = probe_media(partial, toolchain=toolchain)
        if _stream_signature(source_probe) != _stream_signature(output_probe):
            partial.unlink(missing_ok=True)
            raise MediaError(
                code="NORMALIZATION_STREAM_MISMATCH",
                stage="normalize",
                path=str(source),
                stream_index=None,
                retryable=False,
                message="规范化前后的流集合或编码信息不一致",
            )
        output_index = build_frame_index(
            partial,
            cache_root=work / "output-index",
            toolchain=toolchain,
            token=token,
            timeout_seconds=timeout_seconds,
        )
        output_audio_packets = _read_audio_packets(
            partial, toolchain, min(timeout_seconds, 120.0), token
        )
        audio_timeline = _compare_audio_packets(
            source_audio_packets, output_audio_packets
        )
        source_pts = _read_pts(source_index.index_path)
        output_pts = _read_pts(output_index.index_path)
        offsets = {
            output - source
            for source, output in zip(source_pts, output_pts)
            if source is not None and output is not None
        }
        timeline_offset = next(iter(offsets)) if len(offsets) == 1 else None
        timeline_matches = (
            source_index.frame_count == output_index.frame_count
            and len(source_pts) == len(output_pts)
            and bool(source_pts)
            and bool(output_pts)
            and len(offsets) == 1
        )
        if not timeline_matches:
            partial.unlink(missing_ok=True)
            raise MediaError(
                code="NORMALIZATION_TIMELINE_MISMATCH",
                stage="normalize",
                path=str(source),
                stream_index=source_probe.selected_video_stream,
                retryable=False,
                message="规范化前后的显示帧时间轴无法一致验证",
                diagnostics={
                    "source": source_index.to_dict(),
                    "output": output_index.to_dict(),
                    "source_pts_offsets": sorted(offsets),
                },
            )
        audio_video_sync = _compare_audio_video_sync(
            source_probe,
            output_probe,
            source_index,
            output_index,
            source_audio_packets,
            output_audio_packets,
        )
        final_identity = capture_identity(source, include_full_sha256=True)
        if not identities_match(source_identity, final_identity):
            partial.unlink(missing_ok=True)
            raise MediaError(
                code="SOURCE_CHANGED",
                stage="normalize",
                path=str(source),
                stream_index=None,
                retryable=True,
                message="源文件在规范化期间发生变化",
            )
        partial.replace(final)
        return NormalizedMediaRef(
            status="complete",
            source_identity=source_identity,
            normalized_path=str(final),
            reason="fragmented input normalized with ffmpeg stream copy",
            source_timeline={
                "first_pts": source_index.first_pts,
                "last_pts": source_index.last_pts,
                "frame_count": source_index.frame_count,
            },
            validation={
                "frame_index_status": output_index.status,
                "source_frame_count": source_index.frame_count,
                "output_frame_count": output_index.frame_count,
                "video_timeline": {
                    "source": {
                        "first_pts": source_index.first_pts,
                        "last_pts": source_index.last_pts,
                        "frame_count": source_index.frame_count,
                        "time_base": _time_base_payload(source_probe.video_stream),
                    },
                    "normalized": {
                        "first_pts": output_index.first_pts,
                        "last_pts": output_index.last_pts,
                        "frame_count": output_index.frame_count,
                        "time_base": _time_base_payload(output_probe.video_stream),
                    },
                },
                "audio_time_bases": {
                    "source": {
                        str(stream.index): _time_base_payload(stream)
                        for stream in source_probe.audio_streams
                    },
                    "normalized": {
                        str(stream.index): _time_base_payload(stream)
                        for stream in output_probe.audio_streams
                    },
                },
                "source_to_normalized_pts_offset": timeline_offset,
                "audio_timeline": audio_timeline,
                "audio_video_sync": audio_video_sync,
                "source_sha256": final_identity.full_sha256,
                "ffmpeg_peak_private_bytes": memory_sampler.stop(),
                "elapsed_seconds": time.perf_counter() - started,
            },
            cache_key=work.name,
        )
    except MediaError:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        raise
    finally:
        memory_sampler.stop()
