from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


M3_PROTOCOL_VERSION = "m3.desktop.v1"


class M3ProjectError(RuntimeError):
    """A user-facing project or timeline operation error."""

    def __init__(
        self, code: str, message: str, *, details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class AudioConflictError(M3ProjectError):
    """Raised when merging segments with different audio choices."""

    def __init__(self, left: bool, right: bool):
        super().__init__(
            "AUDIO_CONFLICT",
            "相邻片段的音频设置不同，需要用户确认后才能合并。",
            details={"left_audio_enabled": left, "right_audio_enabled": right},
        )


@dataclass(frozen=True)
class TimelineFrame:
    display_index: int
    pts: int | None
    best_effort_pts: int | None
    duration: int | None
    time_base_num: int
    time_base_den: int
    pict_type: str | None
    keyframe: bool | None


@dataclass
class CutPoint:
    cut_id: str
    boundary_index: int
    kind: str = "manual"
    confidence: float | None = None
    needs_review: bool = False
    checked: bool = False
    origin: str = "manual"
    reason: str | None = None


@dataclass
class Segment:
    clip_id: str
    start_index: int
    end_index: int
    audio_enabled: bool = True
    selected_for_export: bool = True
    cover_frame_index: int | None = None
    output_number: int = 1
    name: str | None = None

    @property
    def frame_count(self) -> int:
        return self.end_index - self.start_index


@dataclass
class ProjectSnapshot:
    project_id: str
    source_path: str
    schema_version: str
    source_identity: dict[str, Any]
    probe: dict[str, Any]
    frame_index_path: str
    frame_count: int
    cuts: list[CutPoint] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    detector_status: str = "not_connected"
    detector_version: str | None = None
    color_override: str | None = None
    saved_revision: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectSnapshot":
        return cls(
            project_id=str(payload["project_id"]),
            source_path=str(payload["source_path"]),
            schema_version=str(payload.get("schema_version", M3_PROTOCOL_VERSION)),
            source_identity=dict(payload.get("source_identity") or {}),
            probe=dict(payload.get("probe") or {}),
            frame_index_path=str(payload["frame_index_path"]),
            frame_count=int(payload["frame_count"]),
            cuts=[CutPoint(**item) for item in payload.get("cuts", [])],
            segments=[Segment(**item) for item in payload.get("segments", [])],
            detector_status=str(payload.get("detector_status", "not_connected")),
            detector_version=payload.get("detector_version"),
            color_override=payload.get("color_override"),
            saved_revision=int(payload.get("saved_revision", 0)),
        )
