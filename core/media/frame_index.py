from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
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
from core.protocol.media import FrameIndexReport, FrameRef, Rational


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


def _make_frame(fields: dict[str, str], index: int, time_base: Rational) -> FrameRef:
    best_effort = _int(fields.get("best_effort_timestamp"))
    pts = _int(fields.get("pts"))
    duration = _int(fields.get("duration")) or _int(fields.get("pkt_duration"))
    return FrameRef(
        stream_index=_int(fields.get("stream_index")) or -1,
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
    probe = probe_media(
        source,
        toolchain=toolchain,
        token=token,
        timeout_seconds=min(timeout_seconds, 120.0),
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
