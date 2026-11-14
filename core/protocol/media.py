from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any

MEDIA_PROTOCOL_VERSION = "m1.media.v1"
FRAME_INDEX_SCHEMA_VERSION = 1
CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Rational:
    num: int
    den: int

    def __post_init__(self) -> None:
        if self.den == 0:
            raise ValueError("rational denominator cannot be zero")

    @classmethod
    def from_value(
        cls, value: Fraction | Rational | tuple[int, int] | None
    ) -> Rational | None:
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, Fraction):
            return cls(value.numerator, value.denominator)
        return cls(int(value[0]), int(value[1]))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SourceIdentity:
    canonical_path: str
    physical_file_id: str | None
    size: int
    mtime_ns: int
    sampled_fingerprint: str
    full_sha256: str | None = None
    captured_at_utc: str = field(default_factory=_utc_now)


@dataclass(frozen=True)
class FrameRef:
    stream_index: int
    display_index: int
    pts: int | None
    best_effort_pts: int | None
    time_base: Rational
    duration: int | None
    duration_source: str
    keyframe: bool | None
    pict_type: str | None
    dts: int | None = None
    packet_pos: int | None = None
    source_timeline_offset: Rational | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_base", Rational.from_value(self.time_base))
        object.__setattr__(
            self,
            "source_timeline_offset",
            Rational.from_value(self.source_timeline_offset),
        )


@dataclass(frozen=True)
class ContainerSummary:
    format_names: tuple[str, ...]
    duration_seconds: float | None
    start_time_seconds: float | None
    bit_rate: int | None
    tags: dict[str, str]


@dataclass(frozen=True)
class ColorSummary:
    range: str | None
    space: str | None
    transfer: str | None
    primaries: str | None
    chroma_location: str | None
    hdr_present: bool
    dolby_vision_present: bool
    log_like_present: bool


@dataclass(frozen=True)
class StreamSummary:
    index: int
    codec_type: str
    codec_name: str | None
    profile: str | None
    level: int | None
    width: int | None
    height: int | None
    coded_width: int | None
    coded_height: int | None
    pixel_format: str | None
    bits_per_raw_sample: int | None
    sample_aspect_ratio: Rational | None
    display_aspect_ratio: Rational | None
    time_base: Rational | None
    start_time: int | None
    duration: int | None
    duration_seconds: float | None
    frame_rate_hint: Rational | None
    avg_frame_rate_hint: Rational | None
    rotation: int | None
    color: ColorSummary
    sample_rate: int | None
    channels: int | None
    channel_layout: str | None
    sample_format: str | None
    disposition: dict[str, int]
    tags: dict[str, str]
    side_data_types: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "sample_aspect_ratio",
            "display_aspect_ratio",
            "time_base",
            "frame_rate_hint",
            "avg_frame_rate_hint",
        ):
            object.__setattr__(self, name, Rational.from_value(getattr(self, name)))


@dataclass(frozen=True)
class FragmentSummary:
    is_fragmented: bool
    has_moof: bool
    has_mvex: bool
    top_level_boxes: tuple[bytes, ...]
    malformed: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class MediaProbeResult:
    schema_version: str
    source_identity: SourceIdentity
    container: ContainerSummary
    streams: tuple[StreamSummary, ...]
    selected_video_stream: int
    selected_video_reason: str
    video_stream: StreamSummary
    audio_streams: tuple[StreamSummary, ...]
    subtitle_and_data_streams: tuple[StreamSummary, ...]
    color: ColorSummary
    fragment: FragmentSummary
    diagnostics: tuple[str, ...]
    toolchain: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fragment"]["top_level_boxes"] = [
            item.decode("latin1") for item in self.fragment.top_level_boxes
        ]
        return payload


@dataclass(frozen=True)
class FrameIndexReport:
    schema_version: int
    status: str
    source_identity: SourceIdentity
    stream_index: int
    frame_count: int
    first_pts: int | None
    last_pts: int | None
    time_base: Rational
    index_path: str | None
    incomplete_reason: str | None
    timestamp_diagnostics: tuple[str, ...]
    resource_stats: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "time_base", Rational.from_value(self.time_base))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalizedMediaRef:
    status: str
    source_identity: SourceIdentity
    normalized_path: str | None
    reason: str
    source_timeline: dict[str, Any]
    validation: dict[str, Any]
    cache_key: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MediaError(Exception):
    code: str
    stage: str
    path: str | None
    stream_index: int | None
    retryable: bool
    message: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload.get("path"):
            payload["path"] = "<redacted>"
        return payload
