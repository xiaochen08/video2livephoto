from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
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


_CONTAINER_BOXES = {"moov", "trak", "mdia", "minf", "stbl", "dinf", "edts", "gmhd"}
_MAX_MOOV_BYTES = 64 * 1024 * 1024
_METADATA_TRAK_TEMPLATE = Path(__file__).with_name("assets") / "apple-meta-trak.bin"


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


def _iter_atoms(data: bytes, start: int, end: int):
    """Yield ``(offset, size, type, header_size)`` for a bounded box range."""
    position = start
    while position + 8 <= end:
        size, raw_type = struct.unpack_from(">I4s", data, position)
        header_size = 8
        if size == 1:
            if position + 16 > end:
                raise ValueError("truncated extended atom header")
            size = struct.unpack_from(">Q", data, position + 8)[0]
            header_size = 16
        elif size == 0:
            size = end - position
        if size < header_size or position + size > end:
            raise ValueError("invalid atom size")
        yield position, size, raw_type.decode("latin1"), header_size
        position += size


def _walk_atoms(data: bytes, start: int, end: int):
    for offset, size, atom_type, header_size in _iter_atoms(data, start, end):
        yield offset, size, atom_type, header_size
        if atom_type in _CONTAINER_BOXES:
            yield from _walk_atoms(data, offset + header_size, offset + size)


def _read_top_atoms(path: Path) -> list[tuple[int, int, str, int]]:
    file_size = path.stat().st_size
    atoms: list[tuple[int, int, str, int]] = []
    with path.open("rb") as handle:
        offset = 0
        while offset + 8 <= file_size:
            header = handle.read(8)
            if len(header) != 8:
                break
            size, raw_type = struct.unpack(">I4s", header)
            header_size = 8
            if size == 1:
                extended = handle.read(8)
                if len(extended) != 8:
                    raise ValueError("truncated extended atom header")
                size = struct.unpack(">Q", extended)[0]
                header_size = 16
            elif size == 0:
                size = file_size - offset
            if size < header_size or offset + size > file_size:
                raise ValueError("invalid top-level atom size")
            atoms.append((offset, size, raw_type.decode("latin1"), header_size))
            offset += size
            handle.seek(offset)
    return atoms


def _read_range(path: Path, offset: int, size: int) -> bytes:
    if size > _MAX_MOOV_BYTES:
        raise MediaError(
            code="LIVEPHOTO_MOOV_TOO_LARGE",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="MOV moov 盒过大，拒绝在内存中重写",
            diagnostics={"moov_bytes": size, "limit_bytes": _MAX_MOOV_BYTES},
        )
    with path.open("rb") as handle:
        handle.seek(offset)
        payload = handle.read(size)
    if len(payload) != size:
        raise MediaError(
            code="LIVEPHOTO_INVALID",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="MOV 盒数据读取不完整",
        )
    return payload


def _copy_range(src, dst, offset: int, size: int, *, chunk_size: int = 8 * 1024 * 1024) -> None:
    src.seek(offset)
    remaining = size
    while remaining:
        chunk = src.read(min(chunk_size, remaining))
        if not chunk:
            raise OSError("unexpected EOF while copying MOV payload")
        dst.write(chunk)
        remaining -= len(chunk)


def _u32_patch(buffer: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">I", buffer, offset, value & 0xFFFFFFFF)


def _metadata_sample(width: int, height: int) -> bytes:
    # Apple uses three boxed records. The first one is the still marker and is
    # deliberately a signed int8 -1; the other two are optional transform and
    # reference dimensions carried by genuine iPhone files.
    first = struct.pack(">IIb", 9, 1, -1)
    transform = struct.pack(">II", 80, 2) + struct.pack(">9d", 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    dimensions = struct.pack(">II", 16, 3) + struct.pack(">2f", float(width), float(height))
    sample = first + transform + dimensions
    if len(sample) != 105:
        raise AssertionError("unexpected Apple metadata sample size")
    return sample


def _parse_edit_list(data: bytes, offset: int, size: int) -> tuple[int, list[tuple[int, int]]]:
    version = data[offset + 8]
    count = struct.unpack_from(">I", data, offset + 12)[0]
    entries: list[tuple[int, int]] = []
    position = offset + 16
    for _ in range(count):
        if version == 1:
            segment_duration = struct.unpack_from(">Q", data, position)[0]
            media_time = struct.unpack_from(">q", data, position + 8)[0]
            position += 20
        else:
            segment_duration = struct.unpack_from(">I", data, position)[0]
            media_time = struct.unpack_from(">i", data, position + 4)[0]
            position += 12
        entries.append((segment_duration, media_time))
    return version, entries


def _patch_metadata_trak(
    template: bytes,
    *,
    track_id: int,
    still_units: int,
    sample_offset: int,
    sample: bytes,
    movie_timescale: int,
    movie_created: int,
) -> bytes:
    trak = bytearray(template)
    boxes = list(_walk_atoms(template, 0, len(template)))
    by_type: dict[str, list[tuple[int, int, int]]] = {}
    for offset, size, atom_type, header_size in boxes:
        by_type.setdefault(atom_type, []).append((offset, size, header_size))

    tkhd_offset, _, _ = by_type["tkhd"][0]
    tkhd_version = template[tkhd_offset + 8]
    track_id_offset = tkhd_offset + (28 if tkhd_version == 1 else 20)
    duration_offset = tkhd_offset + (36 if tkhd_version == 1 else 28)
    _u32_patch(trak, track_id_offset, track_id)
    if tkhd_version == 1:
        struct.pack_into(">QQ", trak, tkhd_offset + 12, movie_created, movie_created)
        struct.pack_into(">Q", trak, duration_offset, still_units + 1)
    else:
        struct.pack_into(">II", trak, tkhd_offset + 12, movie_created & 0xFFFFFFFF, movie_created & 0xFFFFFFFF)
        _u32_patch(trak, duration_offset, still_units + 1)

    elst_offset, elst_size, _ = by_type["elst"][0]
    version, entries = _parse_edit_list(template, elst_offset, elst_size)
    if version != 0 or len(entries) < 2:
        raise ValueError("Apple metadata track template has an unsupported edit list")
    struct.pack_into(">I", trak, elst_offset + 16, still_units)
    struct.pack_into(">i", trak, elst_offset + 20, -1)
    struct.pack_into(">I", trak, elst_offset + 28, 1)
    struct.pack_into(">i", trak, elst_offset + 32, 0)

    mdhd_offset, _, _ = by_type["mdhd"][0]
    mdhd_version = template[mdhd_offset + 8]
    timescale_offset = mdhd_offset + (28 if mdhd_version == 1 else 20)
    mdhd_duration_offset = mdhd_offset + (32 if mdhd_version == 1 else 24)
    _u32_patch(trak, timescale_offset, movie_timescale)
    if mdhd_version == 1:
        struct.pack_into(">QQ", trak, mdhd_offset + 12, movie_created, movie_created)
        struct.pack_into(">Q", trak, mdhd_duration_offset, 1)
    else:
        struct.pack_into(">II", trak, mdhd_offset + 12, movie_created & 0xFFFFFFFF, movie_created & 0xFFFFFFFF)
        _u32_patch(trak, mdhd_duration_offset, 1)

    stsz_offset, _, _ = by_type["stsz"][0]
    _u32_patch(trak, stsz_offset + 12, len(sample))
    _u32_patch(trak, stsz_offset + 16, 1)
    if "stco" in by_type:
        stco_offset, _, _ = by_type["stco"][0]
        _u32_patch(trak, stco_offset + 12, 1)
        _u32_patch(trak, stco_offset + 16, sample_offset)
    elif "co64" in by_type:
        co64_offset, _, _ = by_type["co64"][0]
        _u32_patch(trak, co64_offset + 12, 1)
        struct.pack_into(">Q", trak, co64_offset + 16, sample_offset)
    else:
        raise ValueError("Apple metadata track template has no chunk offset box")
    return bytes(trak)


def _shift_chunk_offsets(moov: bytearray, delta: int) -> None:
    for offset, size, atom_type, _header_size in list(_walk_atoms(bytes(moov), 0, len(moov))):
        if atom_type == "stco":
            count = struct.unpack_from(">I", moov, offset + 12)[0]
            for index in range(count):
                entry_offset = offset + 16 + 4 * index
                value = struct.unpack_from(">I", moov, entry_offset)[0] + delta
                if value < 0:
                    raise ValueError("chunk offset underflow while rewriting MOV")
                _u32_patch(moov, entry_offset, value)
        elif atom_type == "co64":
            count = struct.unpack_from(">I", moov, offset + 12)[0]
            for index in range(count):
                entry_offset = offset + 16 + 8 * index
                value = struct.unpack_from(">Q", moov, entry_offset)[0] + delta
                if value < 0:
                    raise ValueError("chunk offset underflow while rewriting MOV")
                struct.pack_into(">Q", moov, entry_offset, value)


def _movie_info(moov: bytes) -> tuple[int, int, int, int, int]:
    mvhd = next((item for item in _walk_atoms(moov, 8, len(moov)) if item[2] == "mvhd"), None)
    if mvhd is None:
        raise ValueError("MOV moov has no mvhd")
    mvhd_offset, _, _atom_type, _header_size = mvhd
    version = moov[mvhd_offset + 8]
    if version == 1:
        created = struct.unpack_from(">Q", moov, mvhd_offset + 12)[0]
        timescale = struct.unpack_from(">I", moov, mvhd_offset + 28)[0]
        duration = struct.unpack_from(">Q", moov, mvhd_offset + 32)[0]
    else:
        created = struct.unpack_from(">I", moov, mvhd_offset + 12)[0]
        timescale = struct.unpack_from(">I", moov, mvhd_offset + 20)[0]
        duration = struct.unpack_from(">I", moov, mvhd_offset + 24)[0]
    max_track_id = 0
    video_width = video_height = 0
    for offset, size, atom_type, header_size in _iter_atoms(moov, 8, len(moov)):
        if atom_type != "trak":
            continue
        track_id_box = next((item for item in _walk_atoms(moov, offset + header_size, offset + size) if item[2] == "tkhd"), None)
        if track_id_box is not None:
            track_id_offset = track_id_box[0]
            version_tkhd = moov[track_id_offset + 8]
            max_track_id = max(max_track_id, struct.unpack_from(">I", moov, track_id_offset + (28 if version_tkhd == 1 else 20))[0])
        handler_box = next((item for item in _walk_atoms(moov, offset + header_size, offset + size) if item[2] == "hdlr"), None)
        if handler_box is None or moov[handler_box[0] + 16:handler_box[0] + 20] != b"vide":
            continue
        stsd = next((item for item in _walk_atoms(moov, offset + header_size, offset + size) if item[2] == "stsd"), None)
        if stsd is None:
            continue
        entry_offset = stsd[0] + 16
        if entry_offset + 36 <= stsd[0] + stsd[1]:
            video_width, video_height = struct.unpack_from(">HH", moov, entry_offset + 32)
            break
    if not timescale or not video_width or not video_height:
        raise ValueError("MOV moov lacks usable movie timescale or video dimensions")
    return timescale, duration, created, max_track_id, (video_width << 16) | video_height


def _metadata_children_from_moov(moov: bytes) -> tuple[bytes, list[bytes]]:
    """Extract FFmpeg's mdta children and preserve unrelated udta children."""
    meta_children: bytes | None = None
    kept: list[bytes] = []
    for offset, size, atom_type, header_size in _iter_atoms(moov, 8, len(moov)):
        if atom_type == "meta":
            body_start = offset + header_size
            # A top-level FFmpeg meta is normally a FullBox; a QuickTime-style
            # plain meta starts with the hdlr size. Detect and strip flags only
            # when the first child is not a valid box.
            body_end = offset + size
            candidate_is_box = False
            if body_start + 8 <= body_end:
                candidate_size = struct.unpack_from(">I", moov, body_start)[0]
                candidate_type = moov[body_start + 4:body_start + 8]
                candidate_is_box = (
                    candidate_size >= 8
                    and body_start + candidate_size <= body_end
                    and all(32 <= value < 127 for value in candidate_type)
                )
            meta_children = moov[body_start if candidate_is_box else body_start + 4:body_end]
            continue
        if atom_type != "udta":
            kept.append(moov[offset:offset + size])
            continue
        udta_children: list[bytes] = []
        for child_offset, child_size, child_type, child_header in _iter_atoms(moov, offset + header_size, offset + size):
            if child_type != "meta":
                udta_children.append(moov[child_offset:child_offset + child_size])
                continue
            body_start = child_offset + child_header + 4
            meta_children = moov[body_start:child_offset + child_size]
        if udta_children:
            udta = struct.pack(">I4s", 8 + sum(len(item) for item in udta_children), b"udta") + b"".join(udta_children)
            kept.append(udta)
    if meta_children is None:
        raise ValueError("MOV does not contain FFmpeg mdta metadata")
    return b"".join(kept), meta_children


def _inject_timed_metadata_track(src: Path, dst: Path, still_time: float) -> dict[str, Any]:
    """Append Apple's mebx still-image-time track without loading mdat."""
    atoms = _read_top_atoms(src)
    moovs = [item for item in atoms if item[2] == "moov"]
    mdats = [item for item in atoms if item[2] == "mdat"]
    if len(moovs) != 1 or len(mdats) != 1:
        raise MediaError(
            code="LIVEPHOTO_UNSUPPORTED_LAYOUT",
            stage="livephoto",
            path=str(src),
            stream_index=None,
            retryable=False,
            message="MOV 需要单一 moov 和单一 mdat 才能安全注入 timed metadata 轨",
            diagnostics={"moov_count": len(moovs), "mdat_count": len(mdats)},
        )
    moov_offset, moov_size, _, _ = moovs[0]
    mdat_offset, mdat_size, _, mdat_header_size = mdats[0]
    moov = _read_range(src, moov_offset, moov_size)
    try:
        movie_timescale, movie_duration, movie_created, max_track_id, packed_dimensions = _movie_info(moov)
        kept_children, metadata_children = _metadata_children_from_moov(moov)
        width, height = packed_dimensions >> 16, packed_dimensions & 0xFFFF
        still_units = round(still_time * movie_timescale)
        if still_units < 0 or (movie_duration and still_units >= movie_duration):
            raise MediaError(
                code="STILL_IMAGE_TIME_OUT_OF_RANGE",
                stage="livephoto",
                path=str(src),
                stream_index=None,
                retryable=False,
                message="still-image-time 超出 MOV 时长",
                diagnostics={"still_units": still_units, "movie_duration_units": movie_duration},
            )
        sample = _metadata_sample(width, height)
        template = _METADATA_TRAK_TEMPLATE.read_bytes()
    except MediaError:
        raise
    except (OSError, ValueError, struct.error) as exc:
        raise MediaError(
            code="LIVEPHOTO_METADATA_INJECTION_FAILED",
            stage="livephoto",
            path=str(src),
            stream_index=None,
            retryable=False,
            message="MOV timed metadata 轨结构解析失败",
            diagnostics={"error": str(exc)},
        ) from exc

    prefix_atoms = [item for item in atoms if item[2] not in {"moov", "mdat"}]
    prefix_size = sum(item[1] for item in prefix_atoms)
    mdat_payload_size = mdat_size - mdat_header_size
    output_mdat_header_size = 16 if mdat_header_size == 16 or mdat_payload_size + len(sample) + 8 > 0xFFFFFFFF else 8
    new_mdat_data_offset = prefix_size + output_mdat_header_size
    old_mdat_data_offset = mdat_offset + mdat_header_size
    delta = new_mdat_data_offset - old_mdat_data_offset
    sample_offset = new_mdat_data_offset + mdat_payload_size
    metadata_trak = _patch_metadata_trak(
        template,
        track_id=max_track_id + 1,
        still_units=still_units,
        sample_offset=sample_offset,
        sample=sample,
        movie_timescale=movie_timescale,
        movie_created=movie_created,
    )
    # Shift inherited video/audio chunk offsets before adding the metadata
    # track. Its stco already points at the new sample location and must not be
    # shifted a second time.
    inherited_moov = bytearray(
        struct.pack(">I4s", 0, b"moov")
        + kept_children
        + struct.pack(">I4s", 8 + len(metadata_children), b"meta")
        + metadata_children
    )
    _u32_patch(inherited_moov, 0, len(inherited_moov))
    _shift_chunk_offsets(inherited_moov, delta)
    new_moov = bytearray(struct.pack(">I4s", 0, b"moov") + inherited_moov[8:])
    # Insert the new trak immediately before the movie-level metadata box.
    metadata_box_offset = 8 + len(kept_children)
    new_moov = bytearray(
        struct.pack(">I4s", 0, b"moov")
        + inherited_moov[8:metadata_box_offset]
        + metadata_trak
        + inherited_moov[metadata_box_offset:]
    )
    _u32_patch(new_moov, 0, len(new_moov))
    # mvhd.nextTrackID is at a fixed offset for the standard version 0/1 box.
    mvhd = next(item for item in _iter_atoms(bytes(new_moov), 8, len(new_moov)) if item[2] == "mvhd")
    mvhd_offset = mvhd[0]
    mvhd_version = new_moov[mvhd_offset + 8]
    next_track_offset = mvhd_offset + (116 if mvhd_version == 1 else 104)
    current_next = struct.unpack_from(">I", new_moov, next_track_offset)[0]
    _u32_patch(new_moov, next_track_offset, max(current_next, max_track_id + 2))

    mdat_total_size = output_mdat_header_size + mdat_payload_size + len(sample)
    if output_mdat_header_size == 16:
        mdat_header = struct.pack(">I4sQ", 1, b"mdat", mdat_total_size)
    else:
        mdat_header = struct.pack(">I4s", mdat_total_size, b"mdat")
    with src.open("rb") as source, dst.open("wb") as target:
        for offset, size, _atom_type, _header_size in prefix_atoms:
            _copy_range(source, target, offset, size)
        target.write(mdat_header)
        _copy_range(source, target, mdat_offset + mdat_header_size, mdat_payload_size)
        target.write(sample)
        target.write(new_moov)
    return {
        "track_id": max_track_id + 1,
        "sample_bytes": len(sample),
        "sample_offset": sample_offset,
        "movie_timescale": movie_timescale,
        "still_units": still_units,
        "chunk_offset_delta": delta,
        "output_mdat_header_size": output_mdat_header_size,
    }


def _validate_timed_metadata_track(path: Path, still_time: float) -> dict[str, Any]:
    atoms = _read_top_atoms(path)
    moovs = [item for item in atoms if item[2] == "moov"]
    if len(moovs) != 1:
        raise MediaError(
            code="LIVEPHOTO_TIMED_METADATA_MISSING",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="MOV 缺少唯一 moov，无法验证 timed metadata 轨",
        )
    moov_offset, moov_size, _, _ = moovs[0]
    moov = _read_range(path, moov_offset, moov_size)
    metadata_trak = None
    for offset, size, atom_type, header_size in _iter_atoms(moov, 8, len(moov)):
        if atom_type != "trak":
            continue
        handler = next((item for item in _walk_atoms(moov, offset + header_size, offset + size) if item[2] == "hdlr"), None)
        if handler is not None and moov[handler[0] + 16:handler[0] + 20] == b"meta":
            stsd = next((item for item in _walk_atoms(moov, offset + header_size, offset + size) if item[2] == "stsd"), None)
            if stsd is not None and moov[stsd[0] + 20:stsd[0] + 24] == b"mebx":
                metadata_trak = (offset, size, header_size, stsd)
                break
    if metadata_trak is None:
        raise MediaError(
            code="LIVEPHOTO_TIMED_METADATA_MISSING",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="MOV 缺少 mebx timed metadata 轨",
        )
    trak_offset, trak_size, trak_header_size, stsd = metadata_trak
    stsz = next((item for item in _walk_atoms(moov, trak_offset + trak_header_size, trak_offset + trak_size) if item[2] == "stsz"), None)
    stco = next((item for item in _walk_atoms(moov, trak_offset + trak_header_size, trak_offset + trak_size) if item[2] in {"stco", "co64"}), None)
    elst = next((item for item in _walk_atoms(moov, trak_offset + trak_header_size, trak_offset + trak_size) if item[2] == "elst"), None)
    mvhd = next(item for item in _walk_atoms(moov, 8, len(moov)) if item[2] == "mvhd")
    mvhd_version = moov[mvhd[0] + 8]
    movie_timescale = struct.unpack_from(">I", moov, mvhd[0] + (28 if mvhd_version == 1 else 20))[0]
    if stsz is None or stco is None or elst is None:
        raise MediaError(
            code="LIVEPHOTO_TIMED_METADATA_INVALID",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="mebx 轨缺少样本大小、偏移或编辑列表",
        )
    sample_size = struct.unpack_from(">I", moov, stsz[0] + 12)[0]
    sample_count = struct.unpack_from(">I", moov, stsz[0] + 16)[0]
    if sample_count != 1 or sample_size < 9:
        raise MediaError(
            code="LIVEPHOTO_TIMED_METADATA_INVALID",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="mebx still-image-time 样本数量或长度错误",
            diagnostics={"sample_count": sample_count, "sample_size": sample_size},
        )
    if stco[2] == "stco":
        sample_offset = struct.unpack_from(">I", moov, stco[0] + 16)[0]
    else:
        sample_offset = struct.unpack_from(">Q", moov, stco[0] + 16)[0]
    with path.open("rb") as handle:
        handle.seek(sample_offset)
        sample = handle.read(sample_size)
    if len(sample) != sample_size or struct.unpack_from(">I", sample, 0)[0] != 9 or struct.unpack_from(">I", sample, 4)[0] != 1 or sample[8] != 0xFF:
        raise MediaError(
            code="LIVEPHOTO_TIMED_METADATA_INVALID",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="still-image-time 样本值不是 Apple int8 -1 标记",
        )
    _version, entries = _parse_edit_list(moov, elst[0], elst[1])
    expected_units = round(still_time * movie_timescale)
    if len(entries) < 2 or entries[0] != (expected_units, -1) or entries[1] != (1, 0):
        raise MediaError(
            code="LIVEPHOTO_TIMED_METADATA_INVALID",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="still-image-time 编辑列表与目标显示时间不一致",
            diagnostics={"entries": entries, "expected_units": expected_units, "movie_timescale": movie_timescale},
        )
    stsd_entry_end = stsd[0] + stsd[1]
    stsd_bytes = moov[stsd[0]:stsd_entry_end]
    key_name = b"com.apple.quicktime.still-image-time"
    if key_name not in stsd_bytes or b"mebx" not in stsd_bytes:
        raise MediaError(
            code="LIVEPHOTO_TIMED_METADATA_INVALID",
            stage="livephoto",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="mebx sample description 未声明 still-image-time key",
        )
    return {
        "timed_metadata_track": True,
        "timed_metadata_codec": "mebx",
        "timed_metadata_sample_size": sample_size,
        "timed_metadata_sample_offset": sample_offset,
        "timed_metadata_movie_timescale": movie_timescale,
        "timed_metadata_still_units": expected_units,
        "timed_metadata_edit_list": entries,
        "timed_metadata_sample_marker": -1,
    }


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
    timed_metadata = _validate_timed_metadata_track(mov_path, still_image_time_seconds)
    return {
        "jpg_makernote_uuid": jpg_id,
        "mov_content_identifier": content_id,
        "mov_still_image_time_tag": still_tag,
        "mov_contains_pairing_uuid": raw_has_uuid,
        "mov_contains_still_image_time_key": raw_has_still_key,
        **timed_metadata,
        "still_image_time_seconds": still_image_time_seconds,
        "duration_seconds": duration,
        "video_frame_count": len(frames),
        "ffprobe_streams": streams,
        "compatibility_note": (
            "Local MOV/JPG metadata, mebx timed metadata, and decode checks "
            "passed; iPhone Photos import remains unverified."
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

    The MOV is copied/remuxed by FFmpeg and then rewritten with a bounded
    ``moov`` parser plus chunked ``mdat`` copy. The output carries Apple's
    ``mebx`` still-image-time track and is locally validated with the same box
    structure before publication. iPhone Photos import remains unverified.
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
        staged_mov_raw = staging / f"{name}.raw.MOV"
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
                str(staged_mov_raw),
            ],
            token=token,
        )
        if code != 0 or not staged_mov_raw.exists():
            raise MediaError(
                code="MOV_MUX_FAILED",
                stage="livephoto",
                path=str(segment),
                stream_index=None,
                retryable=True,
                message="无法生成带配对元数据的 MOV",
                diagnostics={"stderr": stderr[-4000:]},
            )
        try:
            injection = _inject_timed_metadata_track(
                staged_mov_raw,
                staged_mov,
                still_image_time_seconds,
            )
        except MediaError:
            raise
        except (OSError, ValueError, struct.error) as exc:
            raise MediaError(
                code="LIVEPHOTO_METADATA_INJECTION_FAILED",
                stage="livephoto",
                path=str(staged_mov_raw),
                stream_index=None,
                retryable=False,
                message="无法生成 mebx timed metadata 轨",
                diagnostics={"error": str(exc)},
            ) from exc
        diagnostics.append(
            "timed_metadata_track:"
            + json.dumps(injection, ensure_ascii=False, sort_keys=True)
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
