from __future__ import annotations

from typing import Any


COLOR_OVERRIDES = {
    "sdr_rec709": {
        "range": "tv",
        "space": "bt709",
        "transfer": "bt709",
        "primaries": "bt709",
        "hdr_present": False,
        "dolby_vision_present": False,
        "log_like_present": False,
    },
    "hdr_pq": {
        "range": "tv",
        "space": "bt2020nc",
        "transfer": "smpte2084",
        "primaries": "bt2020",
        "hdr_present": True,
        "dolby_vision_present": False,
        "log_like_present": False,
    },
    "hdr_hlg": {
        "range": "tv",
        "space": "bt2020nc",
        "transfer": "arib-std-b67",
        "primaries": "bt2020",
        "hdr_present": True,
        "dolby_vision_present": False,
        "log_like_present": False,
    },
}


def color_override_metadata(selection: str | None) -> dict[str, Any] | None:
    if selection is None:
        return None
    metadata = COLOR_OVERRIDES.get(str(selection))
    return dict(metadata) if metadata is not None else None
