from __future__ import annotations

from dataclasses import asdict
from fractions import Fraction

from core.protocol.media import (
    FRAME_INDEX_SCHEMA_VERSION,
    MEDIA_PROTOCOL_VERSION,
    FrameRef,
    MediaError,
)


def test_frame_ref_serializes_exact_integer_timestamps() -> None:
    frame = FrameRef(
        stream_index=0,
        display_index=4,
        pts=12345,
        best_effort_pts=12345,
        time_base=Fraction(1001, 30000),
        duration=1001,
        duration_source="packet",
        keyframe=False,
        pict_type="B",
        dts=12000,
        packet_pos=4096,
        source_timeline_offset=Fraction(-1, 30000),
    )
    payload = asdict(frame)
    assert payload["pts"] == 12345
    assert payload["time_base"] == {"num": 1001, "den": 30000}
    assert payload["duration_source"] == "packet"
    assert MEDIA_PROTOCOL_VERSION == "m1.media.v1"
    assert FRAME_INDEX_SCHEMA_VERSION == 1


def test_media_error_is_structured_and_safe_to_serialize() -> None:
    error = MediaError(
        code="SOURCE_CHANGED",
        stage="identity",
        path="C:/private/video.mp4",
        stream_index=0,
        retryable=False,
        message="源文件在索引期间发生变化",
        diagnostics={"before_size": 10, "after_size": 11},
    )
    payload = error.to_dict()
    assert payload["code"] == "SOURCE_CHANGED"
    assert payload["path"] == "<redacted>"
    assert payload["retryable"] is False
