from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import threading
import time
import uuid as uuidlib
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from core.media.errors import MediaError
from core.media.process import CancellationToken, kill_process
from core.media.toolchain import Toolchain, process_creation_flags


@dataclass(frozen=True)
class LivePhotoManifest:
    manifest_schema_version: int
    clip_id: str
    pairing_uuid: str
    still_image_time_seconds: float
    jpg_path: str
    mov_path: str
    jpg_sha256: str
    mov_sha256: str
    jpg_bytes: int
    mov_bytes: int
    duration_seconds: float | None
    video_frame_count: int | None
    validation: dict[str, Any] = field(default_factory=dict)
    compatibility: str = "local-validation-only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LivePhotoPackResult:
    status: str
    manifest_path: str | None
    manifest: LivePhotoManifest | None
    reason: str | None = None
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "manifest_path": self.manifest_path,
            "manifest": self.manifest.to_dict() if self.manifest else None,
            "reason": self.reason,
            "diagnostics": list(self.diagnostics),
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contains_bytes(
    path: Path, needle: bytes, *, chunk_size: int = 1024 * 1024
) -> bool:
    """Search a large media file without materializing it in Python memory."""
    overlap = max(0, len(needle) - 1)
    carry = b""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                return needle in carry
            window = carry + chunk
            if needle in window:
                return True
            carry = window[-overlap:] if overlap else b""


def _run(
    args: list[str],
    timeout_seconds: float = 600.0,
    token: CancellationToken | None = None,
) -> tuple[int, str, str]:
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

    def communicate() -> None:
        stdout, stderr = process.communicate()
        result["stdout"], result["stderr"] = stdout, stderr

    reader = threading.Thread(target=communicate, daemon=True)
    reader.start()
    started = time.monotonic()
    while reader.is_alive():
        if token is not None and token.cancelled:
            kill_process(process)
            reader.join(timeout=2)
            raise MediaError(
                code="CANCELLED",
                stage="livephoto",
                path=None,
                stream_index=None,
                retryable=True,
                message="Live Photo 封装已取消",
            )
        if time.monotonic() - started > timeout_seconds:
            kill_process(process)
            reader.join(timeout=2)
            raise MediaError(
                code="LIVEPHOTO_TIMEOUT",
                stage="livephoto",
                path=None,
                stream_index=None,
                retryable=True,
                message="Live Photo 封装超时",
            )
        time.sleep(0.05)
    return process.returncode or 0, result.get("stdout", ""), result.get("stderr", "")


def _ffprobe_json(
    path: Path, toolchain: Toolchain, token: CancellationToken | None = None
) -> dict[str, Any]:
    code, stdout, stderr = _run(
        [
            toolchain.ffprobe.path,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=format_name,duration:format_tags:stream=index,codec_type,codec_name,time_base:frame=best_effort_timestamp,pts",
            str(path),
        ],
        token=token,
    )
    if code != 0:
        raise MediaError(
            code="LIVEPHOTO_INVALID",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="MOV 无法被 ffprobe 解码",
            diagnostics={"returncode": code, "stderr": stderr[-4000:]},
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(
            code="LIVEPHOTO_INVALID",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="MOV 的 ffprobe 结果无效",
        ) from exc


def _inject_jpeg_identifier(jpeg_path: Path, pairing_uuid: str) -> None:
    # Reuse the original project's narrowly scoped JPEG MakerNote implementation
    # while keeping video processing in FFmpeg and streaming.  The import is
    # intentionally local so M5 can be replaced without coupling M1 modules.
    try:
        from livephoto import inject_exif, read_apple_makernote
    except ImportError as exc:  # pragma: no cover - repository packaging issue
        raise MediaError(
            code="LIVEPHOTO_DEPENDENCY_MISSING",
            stage="livephoto",
            path=str(jpeg_path),
            stream_index=None,
            retryable=False,
            message="无法加载 JPEG 配对元数据实现",
        ) from exc
    raw = jpeg_path.read_bytes()
    if not raw.startswith(b"\xff\xd8"):
        raise MediaError(
            code="LIVEPHOTO_INVALID",
            stage="livephoto",
            path=str(jpeg_path),
            stream_index=None,
            retryable=False,
            message="封面不是 JPEG",
        )
    injected = inject_exif(raw, pairing_uuid)
    if read_apple_makernote(injected) != pairing_uuid:
        raise MediaError(
            code="LIVEPHOTO_METADATA_MISMATCH",
            stage="livephoto",
            path=str(jpeg_path),
            stream_index=None,
            retryable=False,
            message="JPEG MakerNote 配对 UUID 读回不一致",
        )
    jpeg_path.write_bytes(injected)


def _validate_pair(
    jpg_path: Path,
    mov_path: Path,
    pairing_uuid: str,
    still_image_time_seconds: float,
    toolchain: Toolchain,
    token: CancellationToken | None = None,
) -> dict[str, Any]:
    if not jpg_path.exists() or not mov_path.exists():
        raise MediaError(
            code="LIVEPHOTO_INCOMPLETE",
            stage="livephoto",
            path=None,
            stream_index=None,
            retryable=False,
            message="JPG/MOV 配对文件不完整",
        )
    try:
        from livephoto import read_apple_makernote

        jpg_id = read_apple_makernote(jpg_path.read_bytes())
    except Exception as exc:
        raise MediaError(
            code="LIVEPHOTO_INVALID",
            stage="livephoto",
            path=str(jpg_path),
            stream_index=None,
            retryable=False,
            message="无法解析 JPEG MakerNote",
        ) from exc
    if jpg_id != pairing_uuid:
        raise MediaError(
            code="LIVEPHOTO_METADATA_MISMATCH",
            stage="livephoto",
            path=str(jpg_path),
            stream_index=None,
            retryable=False,
            message="JPG 配对 UUID 不匹配",
            diagnostics={"expected": pairing_uuid, "actual": jpg_id},
        )
    payload = _ffprobe_json(mov_path, toolchain, token)
    streams = payload.get("streams") or []
    if not streams:
        raise MediaError(
            code="LIVEPHOTO_INVALID",
            stage="livephoto",
            path=str(mov_path),
            stream_index=None,
            retryable=False,
            message="MOV 没有可解码视频流",
        )
    tags = (payload.get("format") or {}).get("tags") or {}
    normalized_tags = {str(key).lower(): str(value) for key, value in tags.items()}
    content_id = normalized_tags.get("com.apple.quicktime.content.identifier")
    still_tag = normalized_tags.get("com.apple.quicktime.still-image-time")
    # FFmpeg may serialize the key in a binary mdta/ilst record that ffprobe
    # presents differently.  Keep a second byte-level evidence check.
    raw_has_uuid = _contains_bytes(mov_path, pairing_uuid.encode("ascii"))
    raw_has_still_key = _contains_bytes(mov_path, b"still-image-time")
    if content_id and content_id.upper() != pairing_uuid.upper() and not raw_has_uuid:
        raise MediaError(
            code="LIVEPHOTO_METADATA_MISMATCH",
            stage="livephoto",
            path=str(mov_path),
            stream_index=None,
            retryable=False,
            message="MOV content.identifier 不匹配",
            diagnostics={"expected": pairing_uuid, "actual": content_id},
        )
    duration = None
    try:
        duration = float((payload.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        pass
    frames = payload.get("frames") or []
    if not math.isfinite(still_image_time_seconds) or still_image_time_seconds < 0:
        raise MediaError(
            code="INVALID_STILL_IMAGE_TIME",
            stage="livephoto",
            path=str(mov_path),
            stream_index=None,
            retryable=False,
            message="still-image-time 必须是非负有限秒数",
        )
    if duration is not None and still_image_time_seconds > duration + 1e-6:
        raise MediaError(
            code="STILL_IMAGE_TIME_OUT_OF_RANGE",
            stage="livephoto",
            path=str(mov_path),
            stream_index=None,
            retryable=False,
            message="still-image-time 超出 MOV 时长",
            diagnostics={
                "still_image_time_seconds": still_image_time_seconds,
                "duration_seconds": duration,
            },
        )
    stream_time_base = streams[0].get("time_base") if streams else None
    frame_times: list[float] = []
    if isinstance(stream_time_base, str) and "/" in stream_time_base:
        try:
            num, den = stream_time_base.split("/", 1)
            time_base = Fraction(int(num), int(den))
            for frame in frames:
                raw_pts = frame.get("best_effort_timestamp", frame.get("pts"))
                if raw_pts is not None:
                    frame_times.append(float(int(raw_pts) * time_base))
        except (ValueError, ZeroDivisionError):
            frame_times = []
    if not frame_times or not any(
        abs(value - still_image_time_seconds) <= 1e-6 for value in frame_times
    ):
        raise MediaError(
            code="STILL_IMAGE_TIME_NOT_A_FRAME",
            stage="livephoto",
            path=str(mov_path),
            stream_index=None,
            retryable=False,
            message="still-image-time 未对齐到 MOV 的显示帧时间戳",
            diagnostics={
                "still_image_time_seconds": still_image_time_seconds,
                "frame_times_preview": frame_times[:8],
            },
        )
    return {
        "jpg_makernote_uuid": jpg_id,
        "mov_content_identifier": content_id,
        "mov_still_image_time_tag": still_tag,
        "mov_contains_pairing_uuid": raw_has_uuid,
        "mov_contains_still_image_time_key": raw_has_still_key,
        "timed_metadata_track": False,
        "still_image_time_seconds": still_image_time_seconds,
        "duration_seconds": duration,
        "video_frame_count": len(frames),
        "ffprobe_streams": streams,
        "compatibility_note": (
            "Local MOV/JPG metadata and decode checks passed; timed metadata "
            "track and iPhone Photos import remain unverified."
        ),
    }


def pack_live_photo(
    segment_path: str | Path,
    *,
    output_dir: str | Path,
    clip_id: str,
    base_name: str | None = None,
    pairing_uuid: str | None = None,
    cover_path: str | Path | None = None,
    still_image_time_seconds: float = 0.0,
    toolchain: Toolchain | None = None,
    token: CancellationToken | None = None,
    replace: bool = False,
) -> LivePhotoPackResult:
    """Create a JPG/MOV pair and a versioned manifest from an encoded segment.

    The MOV is copied/remuxed by FFmpeg (never loaded as a Python byte array),
    while the JPEG MakerNote is injected in a bounded still-image buffer.
    ``timed_metadata_track`` is deliberately reported false until an external
    parser/iPhone test proves the full Apple track format.
    """
    segment = Path(segment_path)
    destination = Path(output_dir)
    toolchain = toolchain or Toolchain.discover()
    token = token or CancellationToken()
    if not segment.is_file():
        raise MediaError(
            code="SOURCE_MISSING",
            stage="livephoto",
            path=str(segment),
            stream_index=None,
            retryable=False,
            message="分段 MP4 不存在",
        )
    try:
        pairing = (
            str(uuidlib.UUID(pairing_uuid)) if pairing_uuid else str(uuidlib.uuid4())
        )
    except (ValueError, AttributeError) as exc:
        raise MediaError(
            code="INVALID_UUID",
            stage="livephoto",
            path=None,
            stream_index=None,
            retryable=False,
            message="配对 UUID 格式无效",
        ) from exc
    pairing = pairing.upper()
    name = base_name or clip_id
    destination.mkdir(parents=True, exist_ok=True)
    jpg_target = destination / f"{name}.JPG"
    mov_target = destination / f"{name}.MOV"
    manifest_target = destination / f"{name}.manifest.json"
    if not replace and any(
        path.exists() for path in (jpg_target, mov_target, manifest_target)
    ):
        raise MediaError(
            code="OUTPUT_EXISTS",
            stage="livephoto",
            path=str(destination),
            stream_index=None,
            retryable=False,
            message="Live Photo 输出已存在，拒绝覆盖",
        )
    staging = destination / f".v1-livephoto-{uuidlib.uuid4().hex}"
    staging.mkdir(parents=False, exist_ok=False)
    diagnostics: list[str] = []
    try:
        if token.cancelled:
            raise MediaError(
                code="CANCELLED",
                stage="livephoto",
                path=str(segment),
                stream_index=None,
                retryable=True,
                message="Live Photo 封装已取消",
            )
        staged_jpg = staging / f"{name}.JPG"
        staged_mov = staging / f"{name}.MOV"
        staged_manifest = staging / f"{name}.manifest.json"
        if cover_path is None:
            code, _stdout, stderr = _run(
                [
                    toolchain.ffmpeg.path,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(segment),
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(staged_jpg),
                ],
                token=token,
            )
            if code != 0:
                raise MediaError(
                    code="COVER_EXTRACTION_FAILED",
                    stage="livephoto",
                    path=str(segment),
                    stream_index=None,
                    retryable=True,
                    message="无法从分段提取封面帧",
                    diagnostics={"stderr": stderr[-3000:]},
                )
        else:
            cover = Path(cover_path)
            if not cover.is_file():
                raise MediaError(
                    code="COVER_MISSING",
                    stage="livephoto",
                    path=str(cover),
                    stream_index=None,
                    retryable=False,
                    message="指定封面不存在",
                )
            shutil.copyfile(cover, staged_jpg)
        _inject_jpeg_identifier(staged_jpg, pairing)
        still_value = f"{still_image_time_seconds:.9f}".rstrip("0").rstrip(".") or "0"
        code, _stdout, stderr = _run(
            [
                toolchain.ffmpeg.path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(segment),
                "-map",
                "0",
                "-c",
                "copy",
                "-movflags",
                "+faststart+use_metadata_tags",
                "-metadata",
                f"com.apple.quicktime.content.identifier={pairing}",
                "-metadata",
                f"com.apple.quicktime.still-image-time={still_value}",
                str(staged_mov),
            ],
            token=token,
        )
        if code != 0 or not staged_mov.exists():
            raise MediaError(
                code="MOV_MUX_FAILED",
                stage="livephoto",
                path=str(segment),
                stream_index=None,
                retryable=True,
                message="无法生成带配对元数据的 MOV",
                diagnostics={"stderr": stderr[-4000:]},
            )
        validation = _validate_pair(
            staged_jpg,
            staged_mov,
            pairing,
            still_image_time_seconds,
            toolchain,
            token,
        )
        manifest = LivePhotoManifest(
            manifest_schema_version=1,
            clip_id=clip_id,
            pairing_uuid=pairing,
            still_image_time_seconds=still_image_time_seconds,
            jpg_path=str(jpg_target),
            mov_path=str(mov_target),
            jpg_sha256=_sha256(staged_jpg),
            mov_sha256=_sha256(staged_mov),
            jpg_bytes=staged_jpg.stat().st_size,
            mov_bytes=staged_mov.stat().st_size,
            duration_seconds=validation.get("duration_seconds"),
            video_frame_count=validation.get("video_frame_count"),
            validation=validation,
        )
        staged_manifest.write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # Publish only fully validated files.  replace=False is the safe default;
        # M6 can coordinate an explicit replacement transaction when needed.
        if not replace and any(
            path.exists() for path in (jpg_target, mov_target, manifest_target)
        ):
            raise MediaError(
                code="OUTPUT_EXISTS",
                stage="livephoto",
                path=str(destination),
                stream_index=None,
                retryable=False,
                message="Live Photo 输出在校验期间出现同名文件，拒绝覆盖",
            )
        os.replace(staged_jpg, jpg_target)
        os.replace(staged_mov, mov_target)
        os.replace(staged_manifest, manifest_target)
        return LivePhotoPackResult(
            status="complete",
            manifest_path=str(manifest_target),
            manifest=manifest,
            diagnostics=tuple(diagnostics),
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)


__all__ = ["LivePhotoManifest", "LivePhotoPackResult", "pack_live_photo"]
