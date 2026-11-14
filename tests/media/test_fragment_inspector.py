from __future__ import annotations

from pathlib import Path

import pytest

from core.media.errors import MediaError
from core.media.fragment_inspector import inspect_fragments


def test_fragment_inspector_detects_moof_and_mvex(fragmented_mp4: Path) -> None:
    status = inspect_fragments(fragmented_mp4)
    assert status.has_moof is True
    assert status.has_mvex is True
    assert status.is_fragmented is True
    assert b"moov" in status.top_level_boxes


def test_fragment_inspector_rejects_truncated_box(tmp_path: Path) -> None:
    path = tmp_path / "truncated.mp4"
    path.write_bytes(b"\x00\x00\x00\x20ftyp\x00\x00")
    with pytest.raises(MediaError) as exc:
        inspect_fragments(path)
    assert exc.value.code == "MALFORMED_CONTAINER"


def test_fragment_inspector_does_not_use_mvex_as_the_only_signal(
    fragmented_mp4: Path, tmp_path: Path
) -> None:
    payload = fragmented_mp4.read_bytes()
    assert b"mvex" in payload
    malformed_variant = tmp_path / "moof-without-mvex.mp4"
    malformed_variant.write_bytes(payload.replace(b"mvex", b"free", 1))
    status = inspect_fragments(malformed_variant)
    assert status.has_moof is True
    assert status.has_mvex is False
    assert status.is_fragmented is True
