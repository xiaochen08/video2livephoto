from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from core.media.cache import FrameIndexCache
from core.media.errors import MediaError
from core.media.process import CancellationToken, kill_process
from core.media.probe import probe_media
from core.media.source_identity import (
    capture_identity,
    identities_match,
    paths_refer_same_file,
)
from core.media.toolchain import (
    ProcessMemorySampler,
    Toolchain,
    process_creation_flags,
    query_private_bytes,
)
from core.protocol.media import FrameIndexReport, FrameRef, MediaProbeResult, Rational


def _int(value: str | None) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _frame_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in line.strip().split("|"):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        fields[key] = value
    return fields


def _packet_frame(fields: dict[str, str], index: int, time_base: Rational) -> FrameRef | None:
    pts = _int(fields.get("pts"))
    if pts is None:
        return None
    duration = _int(fields.get("duration"))
    flags = fields.get("flags", "")
    stream_index = _int(fields.get("stream_index"))
    return FrameRef(
        stream_index=stream_index if stream_index is not None else -1,
        display_index=index,
        pts=pts,
        best_effort_pts=pts,
        time_base=time_base,
        duration=duration,
        duration_source="packet" if duration is not None else "unknown",
        keyframe="K" in flags,
        pict_type=None,
        dts=_int(fields.get("dts")),
        packet_pos=_int(fields.get("pos")),
    )


def _constant_frame_step(probe, time_base: Rational) -> int | None:
    rate = probe.video_stream.avg_frame_rate_hint
    nominal = probe.video_stream.frame_rate_hint
    if rate is None or nominal is None or rate != nominal or rate.num <= 0 or rate.den <= 0:
        return None
    step = Fraction(rate.den * time_base.den, rate.num * time_base.num)
    if step.denominator != 1 or step.numerator <= 0:
        return None
    return step.numerator


def _read_packet_frames(
    source: Path,
    *,
    stream_index: int,
    time_base: Rational,
    expected_step: int,
    toolchain: Toolchain,
    token: CancellationToken,
    timeout_seconds: float,
    expected_frame_count: int | None,
) -> list[FrameRef] | None:
    """Read display PTS from compressed packets when CFR is provable.

    Packet probing avoids decoding every 4K frame.  Packet order follows DTS for
    codecs with B-frames, so the rows are sorted by PTS before assigning display
    indices.  Any ambiguity returns ``None`` and the caller keeps the decoded
    ``show_frames`` path for VFR/edit-list media.
    """

    args = [
        toolchain.ffprobe.path,
        "-v",
        "error",
        "-select_streams",
        "v",
        "-show_packets",
        "-show_entries",
        "packet=stream_index,pts,dts,duration,flags,pos",
        "-of",
        "compact=p=0:nk=0",
        str(source),
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
    result: dict[str, str] = {}
    errors: list[BaseException] = []

    def _communicate() -> None:
        try:
            stdout, stderr = process.communicate()
            result["stdout"] = stdout
            result["stderr"] = stderr
        except BaseException as exc:
            errors.append(exc)

    reader = threading.Thread(target=_communicate, name="m1-packet-reader", daemon=True)
    reader.start()
    started = time.monotonic()
    while reader.is_alive():
        if token.cancelled:
            kill_process(process)
            reader.join(timeout=2)
            raise MediaError(
                code="CANCELLED",
                stage="frame_index",
                path=str(source),
                stream_index=stream_index,
                retryable=True,
                message="帧索引已取消",
            )
        if time.monotonic() - started > timeout_seconds:
            kill_process(process)
            reader.join(timeout=2)
            raise MediaError(
                code="FFPROBE_TIMEOUT",
                stage="frame_index",
                path=str(source),
                stream_index=stream_index,
                retryable=True,
                message="压缩包帧索引探测超时",
            )
        reader.join(timeout=0.05)
    reader.join(timeout=1)
    if errors:
        raise MediaError(
            code="FFPROBE_FAILED",
            stage="frame_index",
            path=str(source),
            stream_index=stream_index,
            retryable=True,
            message="无法读取压缩包帧索引",
            diagnostics={"error": str(errors[0])},
        ) from errors[0]
    if process.returncode != 0:
        return None

    packets: list[FrameRef] = []
    for line in result.get("stdout", "").splitlines():
        fields = _frame_fields(line)
        if _int(fields.get("stream_index")) != stream_index:
            continue
        frame = _packet_frame(fields, len(packets), time_base)
        if frame is not None:
            packets.append(frame)
    if len(packets) < 2:
        return None
    packets.sort(key=lambda frame: (frame.pts if frame.pts is not None else 0, frame.dts or 0))
    pts = [frame.pts for frame in packets]
    if any(value is None for value in pts):
        return None
    if any(right - left != expected_step for left, right in zip(pts, pts[1:])):
        return None
    if expected_frame_count is not None and abs(len(packets) - expected_frame_count) > 1:
        return None
    packets = [
        FrameRef(
            stream_index=frame.stream_index,
            display_index=index,
            pts=frame.pts,
            best_effort_pts=frame.best_effort_pts,
            time_base=frame.time_base,
            duration=frame.duration,
            duration_source=frame.duration_source,
            keyframe=frame.keyframe,
            pict_type=frame.pict_type,
            dts=frame.dts,
            packet_pos=frame.packet_pos,
            source_timeline_offset=frame.source_timeline_offset,
        )
        for index, frame in enumerate(packets)
    ]
    return packets


def _make_frame(fields: dict[str, str], index: int, time_base: Rational) -> FrameRef:
    stream_index = _int(fields.get("stream_index"))
    best_effort = _int(fields.get("best_effort_timestamp"))
    pts = _int(fields.get("pts"))
    duration = _int(fields.get("duration")) or _int(fields.get("pkt_duration"))
    return FrameRef(
        stream_index=stream_index if stream_index is not None else -1,
        display_index=index,
        pts=pts,
        best_effort_pts=best_effort,
        time_base=time_base,
        duration=duration,
        duration_source="packet" if duration is not None else "unknown",
        keyframe=bool(_int(fields.get("key_frame")))
        if fields.get("key_frame") is not None
        else None,
        pict_type=fields.get("pict_type"),
        dts=_int(fields.get("pkt_dts")),
        packet_pos=_int(fields.get("pkt_pos")),
    )


def build_frame_index(
    path: str | Path,
    *,
    cache_root: str | Path,
    toolchain: Toolchain | None = None,
    token: CancellationToken | None = None,
    timeout_seconds: float = 3600.0,
    selected_video_stream: int | None = None,
    packet_fast_path: bool = True,
    probe_result: MediaProbeResult | None = None,
    progress_callback: Callable[[int, int | None], None] | None = None,
) -> FrameIndexReport:
    source = Path(path)
    cache_path = Path(cache_root)
    if (
        cache_path.exists()
        and cache_path.is_file()
        and paths_refer_same_file(source, cache_path)
    ):
        raise MediaError(
            code="PATH_CONFLICT",
            stage="frame_index",
            path=str(source),
            stream_index=None,
            retryable=False,
            message="帧索引缓存路径不能指向源文件",
        )
    toolchain = toolchain or Toolchain.discover()
    token = token or CancellationToken()
    probe = probe_result or probe_media(
        source,
        toolchain=toolchain,
        token=token,
        timeout_seconds=min(timeout_seconds, 120.0),
        selected_video_stream=selected_video_stream,
    )
    time_base = probe.video_stream.time_base
    if time_base is None:
        raise MediaError(
            code="MISSING_TIME_BASE",
            stage="frame_index",
            path=str(source),
            stream_index=probe.selected_video_stream,
            retryable=False,
            message="视频流缺少可用 time_base",
        )
    cache = FrameIndexCache.create(
        cache_path,
        probe.source_identity,
        toolchain.to_dict(),
        mode="display-frames",
        time_base=time_base,
        stream_index=probe.selected_video_stream,
    )
    if cache.status() == "complete":
        rows = cache.connection.execute(
            "SELECT COUNT(*), MIN(pts), MAX(pts) FROM frames"
        ).fetchone()
        cache.close()
        if progress_callback is not None:
            progress_callback(int(rows[0]), int(rows[0]))
        return FrameIndexReport(
            schema_version=1,
            status="complete",
            source_identity=probe.source_identity,
            stream_index=probe.selected_video_stream,
            frame_count=int(rows[0]),
            first_pts=rows[1],
            last_pts=rows[2],
            time_base=time_base,
            index_path=str(cache.path),
            incomplete_reason=None,
            timestamp_diagnostics=(),
            resource_stats={"cache_reused": True},
        )

    expected_step = _constant_frame_step(probe, time_base)
    expected_frame_count = None
    if expected_step is not None and probe.video_stream.duration_seconds is not None:
        duration_ticks = probe.video_stream.duration_seconds / (
            time_base.num / time_base.den
        )
        expected_frame_count = int(round(duration_ticks / expected_step))

    if packet_fast_path:
        if expected_step is not None:
            if progress_callback is not None:
                progress_callback(0, expected_frame_count)
            packet_frames = _read_packet_frames(
                source,
                stream_index=probe.selected_video_stream,
                time_base=time_base,
                expected_step=expected_step,
                toolchain=toolchain,
                token=token,
                timeout_seconds=min(timeout_seconds, 120.0),
                expected_frame_count=expected_frame_count,
            )
            if packet_frames:
                after = capture_identity(source)
                if not identities_match(probe.source_identity, after):
                    cache.mark_incomplete("source_changed")
                    raise MediaError(
                        code="SOURCE_CHANGED",
                        stage="frame_index",
                        path=str(source),
                        stream_index=probe.selected_video_stream,
                        retryable=True,
                        message="源文件在建立帧索引期间发生变化",
                    )
                cache.insert_frames(packet_frames)
                if progress_callback is not None:
                    progress_callback(len(packet_frames), len(packet_frames))
                first_pts = packet_frames[0].pts
                last_pts = packet_frames[-1].pts
                cache.finalize(len(packet_frames), first_pts, last_pts)
                return FrameIndexReport(
                    schema_version=1,
                    status="complete",
                    source_identity=probe.source_identity,
                    stream_index=probe.selected_video_stream,
                    frame_count=len(packet_frames),
                    first_pts=first_pts,
                    last_pts=last_pts,
                    time_base=time_base,
                    index_path=str(cache.path),
                    incomplete_reason=None,
                    timestamp_diagnostics=(
                        "CFR 视频使用压缩包 PTS 快速建立索引；帧类型字段保留为空",
                    ),
                    resource_stats={
                        "cache_reused": False,
                        "index_mode": "packet_cfr",
                    },
                )

    args = [
        toolchain.ffprobe.path,
        "-v",
        "error",
        "-select_streams",
        "v",
        "-show_frames",
        "-show_entries",
        "frame=stream_index,key_frame,pts,best_effort_timestamp,pkt_dts,pkt_duration,duration,pkt_pos,pict_type:frame_side_data=",
        "-of",
        "compact=p=0:nk=0",
        str(source),
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
    python_peak_private = query_private_bytes(os.getpid())
    pending: FrameRef | None = None
    frame_count = 0
    first_pts: int | None = None
    last_pts: int | None = None
    diagnostics: list[str] = []
    batch: list[FrameRef] = []
    last_activity = time.monotonic()
    lines: queue.Queue[str | None] = queue.Queue()

    def _read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    reader = threading.Thread(
        target=_read_stdout, name="m1-ffprobe-reader", daemon=True
    )
    reader.start()
    try:
        if progress_callback is not None:
            progress_callback(0, expected_frame_count)
        stream_closed = False
        while not stream_closed:
            if token.cancelled:
                kill_process(process)
                cache.mark_incomplete("cancelled")
                raise MediaError(
                    code="CANCELLED",
                    stage="frame_index",
                    path=str(source),
                    stream_index=probe.selected_video_stream,
                    retryable=True,
                    message="帧索引已取消",
                )
            if time.monotonic() - last_activity > timeout_seconds:
                kill_process(process)
                cache.mark_incomplete("timeout")
                raise MediaError(
                    code="FFPROBE_TIMEOUT",
                    stage="frame_index",
                    path=str(source),
                    stream_index=probe.selected_video_stream,
                    retryable=True,
                    message="显示帧索引超时",
                )
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                stream_closed = True
                continue
            last_activity = time.monotonic()
            current_python_private = query_private_bytes(os.getpid())
            if current_python_private is not None:
                python_peak_private = max(
                    python_peak_private or 0, current_python_private
                )
            fields = _frame_fields(line)
            if _int(fields.get("stream_index")) != probe.selected_video_stream:
                continue
            current = _make_frame(fields, frame_count, time_base)
            if pending is not None:
                if (
                    pending.duration is None
                    and pending.pts is not None
                    and current.pts is not None
                ):
                    delta = current.pts - pending.pts
                    if delta > 0:
                        pending = FrameRef(
                            stream_index=pending.stream_index,
                            display_index=pending.display_index,
                            pts=pending.pts,
                            best_effort_pts=pending.best_effort_pts,
                            time_base=pending.time_base,
                            duration=delta,
                            duration_source="pts_delta",
                            keyframe=pending.keyframe,
                            pict_type=pending.pict_type,
                            dts=pending.dts,
                            packet_pos=pending.packet_pos,
                            source_timeline_offset=pending.source_timeline_offset,
                        )
                batch.append(pending)
                if len(batch) >= 1000:
                    cache.insert_frames(batch)
                    batch.clear()
            if current.pts is None and current.best_effort_pts is None:
                diagnostics.append(f"frame {frame_count} has no usable timestamp")
            effective_pts = (
                current.best_effort_pts
                if current.best_effort_pts is not None
                else current.pts
            )
            if effective_pts is not None:
                if last_pts is not None and effective_pts <= last_pts:
                    diagnostics.append(
                        f"non_monotonic_pts at display frame {frame_count}"
                    )
                if first_pts is None:
                    first_pts = effective_pts
                last_pts = effective_pts
            pending = current
            frame_count += 1
            if progress_callback is not None and (
                frame_count == 1 or frame_count % 500 == 0
            ):
                progress_callback(frame_count, expected_frame_count)
        if pending is not None:
            batch.append(pending)
        if batch:
            cache.insert_frames(batch)
        return_code = process.wait(timeout=10)
        stderr = process.stderr.read() if process.stderr else ""
        if return_code != 0:
            cache.mark_incomplete("ffprobe_failed")
            raise MediaError(
                code="FFPROBE_FAILED",
                stage="frame_index",
                path=str(source),
                stream_index=probe.selected_video_stream,
                retryable=False,
                message="ffprobe 无法建立显示帧索引",
                diagnostics={"returncode": return_code, "stderr": stderr[-4000:]},
            )
        if frame_count == 0:
            cache.mark_incomplete("empty_index")
            raise MediaError(
                code="FRAME_INDEX_EMPTY",
                stage="frame_index",
                path=str(source),
                stream_index=probe.selected_video_stream,
                retryable=False,
                message="视频流没有可解码显示帧",
                diagnostics={"stderr": stderr[-4000:]},
            )
        after = capture_identity(source)
        if not identities_match(probe.source_identity, after):
            cache.mark_incomplete("source_changed")
            raise MediaError(
                code="SOURCE_CHANGED",
                stage="frame_index",
                path=str(source),
                stream_index=probe.selected_video_stream,
                retryable=True,
                message="源文件在建立帧索引期间发生变化",
            )
        cache.finalize(frame_count, first_pts, last_pts)
        if progress_callback is not None:
            progress_callback(frame_count, frame_count)
        elapsed = time.perf_counter() - started
        child_peak_private = memory_sampler.stop()
        return FrameIndexReport(
            schema_version=1,
            status="complete",
            source_identity=probe.source_identity,
            stream_index=probe.selected_video_stream,
            frame_count=frame_count,
            first_pts=first_pts,
            last_pts=last_pts,
            time_base=time_base,
            index_path=str(cache.path),
            incomplete_reason=None,
            timestamp_diagnostics=tuple(dict.fromkeys(diagnostics)),
            resource_stats={
                "elapsed_seconds": elapsed,
                "cache_reused": False,
                "index_mode": "decoded_frames",
                "ffprobe_peak_private_bytes": child_peak_private,
                "python_peak_private_bytes": python_peak_private,
            },
        )
    except MediaError:
        if process.poll() is None:
            kill_process(process)
        raise
    except Exception as exc:
        if process.poll() is None:
            kill_process(process)
        cache.mark_incomplete(type(exc).__name__)
        raise MediaError(
            code="FRAME_INDEX_FAILED",
            stage="frame_index",
            path=str(source),
            stream_index=probe.selected_video_stream,
            retryable=True,
            message="建立显示帧索引时发生未分类错误",
            diagnostics={"error": str(exc)},
        ) from exc
    finally:
        memory_sampler.stop()
        cache.close()
