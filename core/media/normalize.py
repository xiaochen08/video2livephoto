from __future__ import annotations

import subprocess
import sqlite3
import time
import uuid
from pathlib import Path

from core.media.errors import MediaError
from core.media.fragment_inspector import inspect_fragments
from core.media.frame_index import build_frame_index
from core.media.probe import probe_media
from core.media.process import CancellationToken
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
    root.mkdir(parents=True, exist_ok=True)
    work = root / f"normalize-{uuid.uuid4().hex}"
    work.mkdir()
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
                "source_to_normalized_pts_offset": timeline_offset,
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
