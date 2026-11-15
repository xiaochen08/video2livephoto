from __future__ import annotations

import json
import hashlib
import sqlite3
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from core.media.errors import MediaError
from core.media.process import CancellationToken, kill_process
from core.media.source_identity import capture_identity, identities_match
from core.media.toolchain import Toolchain, process_creation_flags
from core.protocol.media import FrameIndexReport, Rational, SourceIdentity


DETECTION_PROTOCOL_VERSION = "m2.detection.v1"


@dataclass(frozen=True)
class DetectionConfig:
    """Deterministic thresholds; all values are part of the result snapshot."""

    version: str = "m2.config.v1"
    feature_size: int = 16
    # Luma-only red/blue cuts are around 0.18 normalized SAD; 0.12 keeps
    # ordinary camera motion below the hard-cut gate while covering that case.
    hard_cut_threshold: float = 0.12
    black_luma_threshold: float = 0.08
    dissolve_delta_threshold: float = 0.01
    dissolve_cumulative_threshold: float = 0.12
    dissolve_min_frames: int = 3
    short_shot_seconds: float = 1.0


@dataclass(frozen=True)
class CutCandidate:
    candidate_id: str
    kind: str
    frame_index: int
    pts: int
    time_base: Rational
    confidence: float
    transition_start_frame: int | None
    transition_end_frame: int | None
    review_required: bool
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_base", Rational.from_value(self.time_base))


@dataclass(frozen=True)
class ShotSegment:
    segment_id: str
    start_frame: int
    end_frame: int
    start_pts: int
    end_pts: int
    time_base: Rational
    short_shot: bool
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_base", Rational.from_value(self.time_base))


@dataclass(frozen=True)
class DetectionResult:
    schema_version: str
    status: str
    source_identity: SourceIdentity
    frame_index_path: str
    analyzed_frame_count: int
    candidates: tuple[CutCandidate, ...]
    segments: tuple[ShotSegment, ...]
    diagnostics: tuple[str, ...]
    config: DetectionConfig

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _FrameInfo:
    index: int
    pts: int
    duration: int | None
    time_base: Rational


@dataclass(frozen=True)
class _Feature:
    mean: float
    sad: float
    blocks: tuple[float, ...]


def _load_index(report: FrameIndexReport) -> list[_FrameInfo]:
    if report.status != "complete" or not report.index_path:
        raise MediaError(
            code="FRAME_INDEX_UNAVAILABLE",
            stage="shot_detection",
            path=None,
            stream_index=report.stream_index,
            retryable=True,
            message="镜头检测需要完整的显示帧索引",
        )
    path = Path(report.index_path)
    if not path.is_file():
        raise MediaError(
            code="FRAME_INDEX_UNAVAILABLE",
            stage="shot_detection",
            path=str(path),
            stream_index=report.stream_index,
            retryable=True,
            message="显示帧索引缓存不存在",
        )
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "SELECT display_index, pts, best_effort_pts, duration, "
            "time_base_num, time_base_den FROM frames ORDER BY display_index"
        ).fetchall()
    frames: list[_FrameInfo] = []
    for row in rows:
        pts = row[2] if row[2] is not None else row[1]
        if pts is None:
            raise MediaError(
                code="FRAME_TIMESTAMP_UNAVAILABLE",
                stage="shot_detection",
                path=str(path),
                stream_index=report.stream_index,
                retryable=False,
                message=f"显示帧 {row[0]} 缺少可用 PTS",
            )
        frames.append(
            _FrameInfo(
                index=int(row[0]),
                pts=int(pts),
                duration=int(row[3]) if row[3] is not None else None,
                time_base=Rational(int(row[4]), int(row[5])),
            )
        )
    if not frames:
        raise MediaError(
            code="FRAME_INDEX_EMPTY",
            stage="shot_detection",
            path=str(path),
            stream_index=report.stream_index,
            retryable=False,
            message="显示帧索引为空",
        )
    if [frame.index for frame in frames] != list(range(len(frames))):
        raise MediaError(
            code="FRAME_INDEX_INVALID",
            stage="shot_detection",
            path=str(path),
            stream_index=report.stream_index,
            retryable=False,
            message="显示帧索引的 display_index 不连续",
        )
    return frames


def _block_feature(pixels: bytes, size: int) -> tuple[float, ...]:
    block_size = max(1, size // 4)
    values: list[float] = []
    for by in range(4):
        for bx in range(4):
            total = 0
            count = 0
            for y in range(by * block_size, min(size, (by + 1) * block_size)):
                start = y * size + bx * block_size
                stop = min(y * size + size, start + block_size)
                row = pixels[start:stop]
                total += sum(row)
                count += len(row)
            values.append(total / count / 255.0 if count else 0.0)
    return tuple(values)


def _extract_features(
    source: Path,
    stream_index: int,
    frame_count: int,
    toolchain: Toolchain,
    config: DetectionConfig,
    token: CancellationToken,
    timeout_seconds: float,
) -> list[_Feature]:
    size = config.feature_size
    if size < 4 or size > 64:
        raise MediaError(
            code="DETECTION_CONFIG_INVALID",
            stage="shot_detection",
            path=str(source),
            stream_index=stream_index,
            retryable=False,
            message="检测特征尺寸必须在 4 到 64 之间",
        )
    args = [
        toolchain.ffmpeg.path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        f"0:{stream_index}",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"scale={size}:{size},format=gray",
        "-vsync",
        "0",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    process = subprocess.Popen(
        args,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=process_creation_flags(),
    )
    frame_bytes = size * size
    features: list[_Feature] = []
    previous: bytes | None = None
    started = time.monotonic()
    stderr_box: dict[str, bytes] = {"value": b""}

    def _drain_stderr() -> None:
        if process.stderr is not None:
            stderr_box["value"] = process.stderr.read()

    stderr_reader = threading.Thread(
        target=_drain_stderr, name="m2-ffmpeg-stderr", daemon=True
    )
    stderr_reader.start()
    try:
        while True:
            if token.cancelled:
                kill_process(process)
                raise MediaError(
                    code="CANCELLED",
                    stage="shot_detection",
                    path=str(source),
                    stream_index=stream_index,
                    retryable=True,
                    message="镜头检测已取消",
                )
            if time.monotonic() - started > timeout_seconds:
                kill_process(process)
                raise MediaError(
                    code="FFMPEG_TIMEOUT",
                    stage="shot_detection",
                    path=str(source),
                    stream_index=stream_index,
                    retryable=True,
                    message="镜头特征提取超时",
                )
            assert process.stdout is not None
            chunks: list[bytes] = []
            remaining = frame_bytes
            while remaining:
                chunk = process.stdout.read(remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            pixels = b"".join(chunks)
            if not pixels:
                break
            if len(pixels) != frame_bytes:
                raise MediaError(
                    code="DETECTION_FRAME_DECODE_FAILED",
                    stage="shot_detection",
                    path=str(source),
                    stream_index=stream_index,
                    retryable=False,
                    message="镜头特征帧未完整解码",
                    diagnostics={
                        "expected_bytes": frame_bytes,
                        "actual_bytes": len(pixels),
                    },
                )
            mean = sum(pixels) / len(pixels) / 255.0
            sad = (
                sum(abs(left - right) for left, right in zip(previous, pixels))
                / len(pixels)
                / 255.0
                if previous is not None
                else 0.0
            )
            features.append(
                _Feature(mean=mean, sad=sad, blocks=_block_feature(pixels, size))
            )
            previous = pixels
        return_code = process.wait(timeout=10)
        stderr_reader.join(timeout=1)
        stderr = stderr_box["value"].decode("utf-8", errors="replace")
        if return_code != 0:
            raise MediaError(
                code="FFMPEG_FAILED",
                stage="shot_detection",
                path=str(source),
                stream_index=stream_index,
                retryable=False,
                message="无法解码用于镜头检测的显示帧",
                diagnostics={"returncode": return_code, "stderr": stderr[-4000:]},
            )
        if len(features) != frame_count:
            raise MediaError(
                code="DETECTION_FRAME_MISMATCH",
                stage="shot_detection",
                path=str(source),
                stream_index=stream_index,
                retryable=False,
                message="特征帧数量与 M1 显示帧索引不一致",
                diagnostics={
                    "index_count": frame_count,
                    "decoded_count": len(features),
                },
            )
        return features
    except MediaError:
        if process.poll() is None:
            kill_process(process)
        raise
    except Exception as exc:
        if process.poll() is None:
            kill_process(process)
        raise MediaError(
            code="DETECTION_FAILED",
            stage="shot_detection",
            path=str(source),
            stream_index=stream_index,
            retryable=True,
            message="镜头特征提取发生未分类错误",
            diagnostics={"error": str(exc)},
        ) from exc


def _distance(left: Iterable[float], right: Iterable[float]) -> float:
    values = [abs(a - b) for a, b in zip(left, right)]
    return sum(values) / len(values) if values else 0.0


def _candidate(
    *,
    kind: str,
    frame: _FrameInfo,
    time_base: Rational,
    confidence: float,
    start: int | None,
    end: int | None,
    review: bool,
    reason: str,
) -> CutCandidate:
    return CutCandidate(
        candidate_id="pending",
        kind=kind,
        frame_index=frame.index,
        pts=frame.pts,
        time_base=time_base,
        confidence=max(0.0, min(1.0, confidence)),
        transition_start_frame=start,
        transition_end_frame=end,
        review_required=review,
        reason=reason,
    )


def _detect_candidates(
    frames: list[_FrameInfo], features: list[_Feature], config: DetectionConfig
) -> list[CutCandidate]:
    time_base = frames[0].time_base
    candidates: list[CutCandidate] = []
    black = [item.mean <= config.black_luma_threshold for item in features]
    black_runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_black in enumerate(black + [False]):
        if is_black and start is None:
            start = index
        elif not is_black and start is not None:
            black_runs.append((start, index))
            start = None
    black_boundaries: set[int] = set()
    for run_start, run_end in black_runs:
        if run_start > 0:
            black_boundaries.add(run_start)
            candidates.append(
                _candidate(
                    kind="black_transition",
                    frame=frames[run_start],
                    time_base=time_base,
                    confidence=0.95,
                    start=run_start,
                    end=run_end,
                    review=True,
                    reason="连续低亮度帧进入黑场，保留黑场并要求人工检查",
                )
            )
        if run_end < len(frames):
            black_boundaries.add(run_end)
            candidates.append(
                _candidate(
                    kind="black_transition",
                    frame=frames[run_end],
                    time_base=time_base,
                    confidence=0.95,
                    start=run_start,
                    end=run_end,
                    review=True,
                    reason="连续低亮度帧离开黑场，保留黑场并要求人工检查",
                )
            )

    for index in range(1, len(features)):
        feature = features[index]
        if index in black_boundaries or index - 1 in black_boundaries:
            continue
        if feature.sad < config.hard_cut_threshold:
            continue
        neighbour = []
        if index > 1:
            neighbour.append(features[index - 1].sad)
        if index + 1 < len(features):
            neighbour.append(features[index + 1].sad)
        local_motion = sum(neighbour) / len(neighbour) if neighbour else 0.0
        if feature.sad < max(config.hard_cut_threshold, local_motion * 1.5):
            continue
        candidates.append(
            _candidate(
                kind="hard_cut",
                frame=frames[index],
                time_base=time_base,
                confidence=0.75 + min(0.25, (feature.sad - config.hard_cut_threshold)),
                start=index - 1,
                end=index + 1,
                review=False,
                reason="相邻显示帧的局部画面差异超过硬切阈值",
            )
        )

    index = 1
    while index < len(features):
        if (
            index in black_boundaries
            or features[index].sad < config.dissolve_delta_threshold
        ):
            index += 1
            continue
        run_start = index
        while index < len(features):
            item = features[index]
            if (
                item.sad < config.dissolve_delta_threshold
                or item.sad >= config.hard_cut_threshold
            ):
                break
            index += 1
        run_end = index
        if run_end == run_start:
            # A hard-cut-sized delta terminates this gradual-transition scan;
            # advance so the outer loop cannot revisit the same frame forever.
            index += 1
            continue
        if run_end - run_start >= config.dissolve_min_frames:
            left = features[run_start - 1].blocks
            right = (
                features[run_end].blocks
                if run_end < len(features)
                else features[-1].blocks
            )
            distance = _distance(left, right)
            cumulative = sum(features[item].sad for item in range(run_start, run_end))
            if (
                distance >= config.dissolve_cumulative_threshold
                and cumulative >= config.dissolve_cumulative_threshold
            ):
                midpoint = (run_start + run_end) // 2
                candidates.append(
                    _candidate(
                        kind="dissolve_midpoint",
                        frame=frames[midpoint],
                        time_base=time_base,
                        confidence=min(0.9, 0.45 + distance),
                        start=run_start - 1,
                        end=run_end,
                        review=True,
                        reason="连续渐变候选已吸附到转场区间的实际显示帧中点，需人工检查",
                    )
                )
    candidates.sort(key=lambda item: (item.frame_index, item.kind))
    deduped: list[CutCandidate] = []
    seen: set[tuple[int, str]] = set()
    for candidate in candidates:
        key = (candidate.frame_index, candidate.kind)
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def _pts_end(frames: list[_FrameInfo], end_index: int) -> int:
    if end_index < len(frames):
        return frames[end_index].pts
    last = frames[-1]
    if last.duration is not None and last.duration > 0:
        return last.pts + last.duration
    if len(frames) > 1:
        delta = frames[-1].pts - frames[-2].pts
        if delta > 0:
            return last.pts + delta
    return last.pts + 1


def _segments(
    frames: list[_FrameInfo],
    candidates: list[CutCandidate],
    config: DetectionConfig,
    source: SourceIdentity,
) -> tuple[ShotSegment, ...]:
    boundaries = sorted({0, len(frames), *(item.frame_index for item in candidates)})
    segments: list[ShotSegment] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start:
            continue
        start_pts = frames[start].pts
        end_pts = _pts_end(frames, end)
        seconds = (
            (end_pts - start_pts)
            * frames[start].time_base.num
            / frames[start].time_base.den
        )
        segments.append(
            ShotSegment(
                segment_id=(
                    "segment-"
                    + hashlib.sha256(
                        f"{source.sampled_fingerprint}:{start}:{end}".encode("utf-8")
                    ).hexdigest()[:16]
                ),
                start_frame=start,
                end_frame=end,
                start_pts=start_pts,
                end_pts=end_pts,
                time_base=frames[start].time_base,
                short_shot=seconds < config.short_shot_seconds,
                source="m2.detected",
            )
        )
    return tuple(segments)


def detect_shots(
    path: str | Path,
    *,
    frame_index_report: FrameIndexReport,
    toolchain: Toolchain | None = None,
    config: DetectionConfig | None = None,
    token: CancellationToken | None = None,
    timeout_seconds: float = 3600.0,
) -> DetectionResult:
    """Analyze display frames without altering source media or filtering short shots."""

    source = Path(path)
    config = config or DetectionConfig()
    token = token or CancellationToken()
    toolchain = toolchain or Toolchain.discover()
    frames = _load_index(frame_index_report)
    if frame_index_report.source_identity.canonical_path != str(source.resolve()):
        raise MediaError(
            code="SOURCE_IDENTITY_MISMATCH",
            stage="shot_detection",
            path=str(source),
            stream_index=frame_index_report.stream_index,
            retryable=False,
            message="镜头检测输入与 M1 帧索引源文件不一致",
        )
    before = capture_identity(source)
    features = _extract_features(
        source,
        frame_index_report.stream_index,
        len(frames),
        toolchain,
        config,
        token,
        timeout_seconds,
    )
    after = capture_identity(source)
    if not identities_match(before, after):
        raise MediaError(
            code="SOURCE_CHANGED",
            stage="shot_detection",
            path=str(source),
            stream_index=frame_index_report.stream_index,
            retryable=True,
            message="镜头检测期间源文件发生变化",
        )
    candidates = _detect_candidates(frames, features, config)
    candidates = [
        replace(
            item,
            candidate_id=(
                "cut-"
                + hashlib.sha256(
                    f"{before.sampled_fingerprint}:{item.kind}:{item.frame_index}".encode(
                        "utf-8"
                    )
                ).hexdigest()[:16]
            ),
        )
        for item in candidates
    ]
    return DetectionResult(
        schema_version=DETECTION_PROTOCOL_VERSION,
        status="complete",
        source_identity=before,
        frame_index_path=frame_index_report.index_path or "",
        analyzed_frame_count=len(frames),
        candidates=tuple(candidates),
        segments=_segments(frames, candidates, config, before),
        diagnostics=(
            "候选切点需经预览人工确认；短镜头已保留",
            "叠化中点使用显示帧边界吸附，不能替代最终人工审核",
        ),
        config=config,
    )


def detection_to_json(result: DetectionResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)
