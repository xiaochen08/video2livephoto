"""Conversion helpers for the renderer-facing V2LP adapter contract.

The M3 service remains the source of truth for media, timeline and queue
operations.  This module only translates its persisted values to the
renderer contract; it deliberately does not invent media capabilities or
success states that the backend cannot prove.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.media.color import color_override_metadata

from .models import M3ProjectError, ProjectSnapshot


def _rational(value: Any, default: tuple[int, int] = (1, 1)) -> dict[str, int]:
    if isinstance(value, dict):
        try:
            num, den = int(value.get("num", default[0])), int(value.get("den", default[1]))
            if den:
                return {"num": num, "den": den}
        except (TypeError, ValueError):
            pass
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            num, den = int(value[0]), int(value[1])
            if den:
                return {"num": num, "den": den}
        except (TypeError, ValueError):
            pass
    return {"num": default[0], "den": default[1]}


def _pts(value: Any) -> str | None:
    return None if value is None else str(int(value))


def source_identity(snapshot: ProjectSnapshot) -> dict[str, Any]:
    raw = snapshot.source_identity or {}
    path = str(raw.get("canonical_path") or snapshot.source_path)
    return {
        "path_display": path,
        "file_name": Path(path).name,
        "size_bytes": str(raw.get("size", "0")),
        "modified_at": str(raw.get("mtime_ns", "")),
        "fingerprint": raw.get("full_sha256") or raw.get("sampled_fingerprint"),
        "status": "ok",
    }


def _color(raw: dict[str, Any]) -> dict[str, Any]:
    transfer = str(raw.get("transfer") or "unknown").lower()
    transfer = {
        "smpte2084": "pq",
        "arib-std-b67": "hlg",
    }.get(transfer, transfer)
    if transfer not in {"bt709", "pq", "hlg", "log", "unknown"}:
        transfer = "unknown"
    primaries = str(raw.get("primaries") or "unknown").lower()
    if primaries not in {"bt709", "bt2020", "unknown"}:
        primaries = "unknown"
    return {
        "transfer": transfer,
        "primaries": primaries,
        "dolby_vision": bool(raw.get("dolby_vision_present", False)),
        "log_profile": None,
        "bit_depth": None,
    }


def _detect_vfr(snapshot: ProjectSnapshot, stream: dict[str, Any], frame_at=None) -> bool:
    """Detect variable frame spacing from the indexed display PTS values.

    Container frame-rate hints are not authoritative for VFR media.  Sampling
    short adjacent windows from the persisted frame index keeps project-open
    responses bounded while still switching the renderer to PTS durations when
    the actual timeline has non-uniform spacing.
    """
    if frame_at is None or int(stream.get("index", -1)) != int((snapshot.probe or {}).get("selected_video_stream", -2)):
        return False
    count = int(snapshot.frame_count)
    if count < 4:
        return False
    points: list[int] = []
    for center in {0, count // 2, count - 1}:
        points.extend(range(max(0, center - 2), min(count, center + 3)))
    timestamps: list[tuple[int, int]] = []
    for index in sorted(set(points)):
        try:
            item = frame_at(index)
            value = item.best_effort_pts if item.best_effort_pts is not None else item.pts
            if value is not None:
                timestamps.append((index, int(value)))
        except Exception:
            continue
    deltas = [
        (right_pts - left_pts) / (right_index - left_index)
        for (left_index, left_pts), (right_index, right_pts) in zip(timestamps, timestamps[1:])
        if right_index > left_index and right_pts >= left_pts
    ]
    if len(deltas) < 3:
        return False
    smallest, largest = min(deltas), max(deltas)
    return largest - smallest > max(1.0, largest * 0.01)


def media_info(snapshot: ProjectSnapshot, frame_at=None) -> dict[str, Any]:
    probe = snapshot.probe or {}
    streams = list(probe.get("streams") or [])
    selected = int(probe.get("selected_video_stream", -1))
    container = probe.get("container") or {}
    duration_seconds = container.get("duration_seconds")
    try:
        duration_us = int(round(float(duration_seconds or 0) * 1_000_000))
    except (TypeError, ValueError):
        duration_us = 0

    videos: list[dict[str, Any]] = []
    audios: list[dict[str, Any]] = []
    for stream in streams:
        kind = stream.get("codec_type")
        if kind == "video":
            fps = _rational(stream.get("avg_frame_rate_hint") or stream.get("frame_rate_hint"))
            time_base = _rational(stream.get("time_base"))
            aspect = _rational(stream.get("display_aspect_ratio"))
            rotation = int(stream.get("rotation") or 0) % 360
            if rotation not in {0, 90, 180, 270}:
                rotation = 0
            stream_index = int(stream.get("index", -1))
            color = dict(stream.get("color") or {})
            color_override = getattr(snapshot, "color_override", None)
            if stream_index == selected and color_override:
                override = color_override_metadata(color_override)
                if override is not None:
                    color.update(override)
            videos.append(
                {
                    "stream_index": stream_index,
                    "codec": str(stream.get("codec_name") or "unknown"),
                    "width": int(stream.get("width") or 0),
                    "height": int(stream.get("height") or 0),
                    "display_aspect": aspect,
                    "rotation_deg": rotation,
                    "frame_rate": fps,
                    "vfr": _detect_vfr(snapshot, stream, frame_at),
                    "frame_count": snapshot.frame_count if stream_index == selected else 0,
                    "time_base": time_base,
                    "duration_us": int(round(float(stream.get("duration_seconds") or duration_seconds or 0) * 1_000_000)),
                    "color": _color(color),
                    "is_default": bool((stream.get("disposition") or {}).get("default", 0)),
                    "title": (stream.get("tags") or {}).get("title"),
                }
            )
        elif kind == "audio":
            audios.append(
                {
                    "stream_index": int(stream.get("index", -1)),
                    "codec": str(stream.get("codec_name") or "unknown"),
                    "channels": int(stream.get("channels") or 0),
                    "sample_rate": int(stream.get("sample_rate") or 0),
                    "is_mixed_main": None,
                }
            )
    return {
        "container": str((container.get("format_names") or ["unknown"])[0]),
        "size_bytes": str((probe.get("source_identity") or {}).get("size", "0")),
        "duration_us": duration_us,
        "video_streams": videos,
        "audio_streams": audios,
        "selected_video_stream": selected if selected >= 0 else None,
    }


def frame(snapshot: ProjectSnapshot, display_index: int, frame_at) -> dict[str, Any]:
    item = frame_at(display_index)
    return {
        "display_index": int(item.display_index),
        "pts": _pts(item.pts),
        "best_effort_pts": _pts(item.best_effort_pts),
        "duration": None if item.duration is None else int(item.duration),
        "time_base_num": int(item.time_base_num),
        "time_base_den": int(item.time_base_den),
        "pict_type": item.pict_type,
        "keyframe": item.keyframe,
    }


def _timeline(snapshot: ProjectSnapshot, frame_at) -> dict[str, Any]:
    cuts = []
    for cut in sorted(snapshot.cuts, key=lambda value: value.boundary_index):
        pts = None
        try:
            marker = frame_at(cut.boundary_index)
            pts = _pts(marker.best_effort_pts if marker.best_effort_pts is not None else marker.pts)
        except Exception:
            # A malformed/partial cache must never turn into fabricated PTS.
            pts = None
        kind = cut.kind if cut.kind in {"hard", "dissolve", "flash_candidate", "fast_motion_candidate", "manual"} else "manual"
        cuts.append(
            {
                "cut_id": cut.cut_id,
                "frame": int(cut.boundary_index),
                "pts": pts,
                "kind": kind,
                "transition": None,
                "review": "pending" if cut.needs_review and not cut.checked else "confirmed",
                "confirmed_by": "analysis" if cut.origin == "detector" and cut.checked else ("user" if cut.checked else None),
                "skipped": False,
                "origin": "analysis" if cut.origin == "detector" else "user",
                "reason": cut.reason,
                "confidence": cut.confidence,
            }
        )
    clips = []
    for segment in sorted(snapshot.segments, key=lambda value: value.start_index):
        start_pts = end_pts = None
        try:
            start = frame_at(segment.start_index)
            start_pts = _pts(start.best_effort_pts if start.best_effort_pts is not None else start.pts)
            if segment.end_index < snapshot.frame_count:
                end = frame_at(segment.end_index)
                end_pts = _pts(end.best_effort_pts if end.best_effort_pts is not None else end.pts)
            elif snapshot.frame_count > 0:
                last = frame_at(snapshot.frame_count - 1)
                last_pts = last.best_effort_pts if last.best_effort_pts is not None else last.pts
                if last_pts is not None and last.duration is not None:
                    end_pts = _pts(last_pts + last.duration)
        except Exception:
            pass
        cover = segment.cover_frame_index if segment.cover_frame_index is not None else segment.start_index
        clips.append(
            {
                "clip_id": segment.clip_id,
                "start_frame": int(segment.start_index),
                "end_frame": int(segment.end_index),
                "start_pts": start_pts,
                "end_pts": end_pts,
                "display_index": int(segment.output_number),
                "name": segment.name,
                "name_origin": "user" if segment.name else "default",
                "export_selected": bool(segment.selected_for_export),
                "audio": "source" if segment.audio_enabled else "muted",
                "cover": {
                    "frame": int(cover),
                    "origin": "user" if segment.cover_frame_index is not None else "auto",
                    "status": "valid" if segment.start_index <= cover < segment.end_index else "out_of_range",
                },
            }
        )
    return {"frame_count": snapshot.frame_count, "cuts": cuts, "clips": clips}


def project(snapshot: ProjectSnapshot, service) -> dict[str, Any]:
    timeline = _timeline(snapshot, service.frame_at)
    revision = int(getattr(snapshot, "saved_revision", 0))
    return {
        "project_id": snapshot.project_id,
        "schema_version": 1,
        "name": Path(snapshot.source_path).stem,
        "source": source_identity(snapshot),
        "media": media_info(snapshot, service.frame_at),
        "analysis_version": 1,
        "edit_version": revision,
        "saved_edit_version": revision,
        "timeline": timeline,
        "history": {
            "can_undo": bool(getattr(service, "_undo", [])),
            "can_redo": bool(getattr(service, "_redo", [])),
            "undo_label": "上一步编辑" if getattr(service, "_undo", []) else None,
            "redo_label": "下一步编辑" if getattr(service, "_redo", []) else None,
        },
        "export_settings": {
            "output_dir": str(Path(snapshot.source_path).parent / "导出"),
            "quality": "source",
            "color": "sdr_rec709",
            "name_base": Path(snapshot.source_path).stem,
        },
        "recovery_pending": False,
        "outdated_clip_ids": [],
    }


def error_payload(exc: Exception, *, scope: dict[str, Any] | None = None) -> dict[str, Any]:
    code = getattr(exc, "code", "IPC_ERROR")
    message = str(exc)
    details = getattr(exc, "details", {}) or {}
    return {
        "code": code,
        "message": message,
        "scope": scope or {},
        "preserved": "已确认的项目与源文件保持不变。" if code not in {"IPC_ERROR"} else None,
        "actions": ["retry"] if getattr(exc, "retryable", False) else [],
        "detail": details,
        "retryable": bool(getattr(exc, "retryable", False)),
        "details": details,
    }


class AdapterContractError(M3ProjectError):
    """Error used when the proposed contract asks for an unsupported action."""

