from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.protocol.media import MediaError

_CONTAINER_TYPES = {
    b"moov",
    b"trak",
    b"mdia",
    b"minf",
    b"stbl",
    b"dinf",
    b"edts",
    b"udta",
    b"meta",
    b"ilst",
    b"mvex",
    b"moof",
    b"traf",
    b"mfra",
    b"tref",
    b"wave",
    b"gmhd",
    b"sinf",
    b"schi",
}
_FULL_BOX_TYPES = {b"meta"}
_MAX_DEPTH = 16
_MAX_BOXES = 2_000_000


@dataclass(frozen=True)
class FragmentStatus:
    is_fragmented: bool
    has_moof: bool
    has_mvex: bool
    top_level_boxes: tuple[bytes, ...]
    malformed: bool
    diagnostics: tuple[str, ...]


def _read_header(handle, position: int, end: int) -> tuple[bytes, int, int] | None:
    if end - position < 8:
        raise ValueError("truncated box header")
    handle.seek(position)
    raw = handle.read(8)
    if len(raw) != 8:
        raise ValueError("truncated box header")
    size = int.from_bytes(raw[:4], "big")
    box_type = raw[4:8]
    header_size = 8
    if size == 1:
        if end - position < 16:
            raise ValueError("truncated extended box header")
        extended = handle.read(8)
        if len(extended) != 8:
            raise ValueError("truncated extended box header")
        size = int.from_bytes(extended, "big")
        header_size = 16
    elif size == 0:
        size = end - position
    if size < header_size or position + size > end:
        raise ValueError("box size exceeds file boundary")
    return box_type, header_size, size


def inspect_fragments(path: str | Path) -> FragmentStatus:
    source = Path(path)
    try:
        file_size = source.stat().st_size
        top_level: list[bytes] = []
        state = {
            "has_moof": False,
            "has_mvex": False,
            "boxes": 0,
            "top_level_list": top_level,
        }
        with source.open("rb") as handle:
            _scan_region(handle, 0, file_size, 0, state, top_level=True)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise MediaError(
            code="MALFORMED_CONTAINER",
            stage="fragment_inspector",
            path=str(source),
            stream_index=None,
            retryable=False,
            message="媒体容器盒结构损坏、截断或超出文件边界",
            diagnostics={"reason": str(exc)},
        ) from exc
    return FragmentStatus(
        is_fragmented=bool(state["has_moof"] or state["has_mvex"]),
        has_moof=bool(state["has_moof"]),
        has_mvex=bool(state["has_mvex"]),
        top_level_boxes=tuple(top_level),
        malformed=False,
        diagnostics=tuple(
            item
            for item in (
                "moof detected" if state["has_moof"] else None,
                "mvex detected" if state["has_mvex"] else None,
            )
            if item
        ),
    )


def _scan_region(
    handle,
    start: int,
    end: int,
    depth: int,
    state: dict[str, object],
    *,
    top_level: bool,
) -> None:
    if depth > _MAX_DEPTH:
        raise ValueError("container nesting is too deep")
    position = start
    while position < end:
        state["boxes"] = int(state["boxes"]) + 1
        if int(state["boxes"]) > _MAX_BOXES:
            raise ValueError("too many boxes")
        parsed = _read_header(handle, position, end)
        if parsed is None:
            raise ValueError("missing box header")
        box_type, header_size, size = parsed
        if top_level:
            # The caller passes a separate list because this is part of the public summary.
            state["top_level_list"].append(box_type)
        if box_type == b"moof":
            state["has_moof"] = True
        if box_type == b"mvex":
            state["has_mvex"] = True
        child_start = position + header_size
        if box_type in _FULL_BOX_TYPES:
            if size - header_size < 4:
                raise ValueError("full box is missing version and flags")
            child_start += 4
        if box_type in _CONTAINER_TYPES and child_start < position + size:
            _scan_region(
                handle, child_start, position + size, depth + 1, state, top_level=False
            )
        position += size
    if position != end:
        raise ValueError("box scan did not terminate at region boundary")
