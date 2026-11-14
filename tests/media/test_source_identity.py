from __future__ import annotations

from pathlib import Path
import os

from core.media.source_identity import (
    capture_identity,
    identities_match,
    paths_refer_same_file,
)


def test_identity_uses_unicode_path_and_sampled_fingerprint(tmp_path: Path) -> None:
    source = tmp_path / "中文 文件.mp4"
    source.write_bytes(b"header" + bytes(range(256)) * 32 + b"tail")
    identity = capture_identity(source)
    assert identity.canonical_path == str(source.resolve())
    assert identity.size == source.stat().st_size
    assert identity.mtime_ns == source.stat().st_mtime_ns
    assert identity.sampled_fingerprint
    assert identity.full_sha256 is None
    assert identities_match(identity, capture_identity(source))


def test_identity_detects_source_change(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"before")
    before = capture_identity(source)
    source.write_bytes(b"after with a different size")
    after = capture_identity(source)
    assert not identities_match(before, after)


def test_hardlink_alias_is_detected_as_the_same_physical_file(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    alias = tmp_path / "alias.mp4"
    source.write_bytes(b"same physical file")
    try:
        os.link(source, alias)
    except (OSError, NotImplementedError):
        return
    assert paths_refer_same_file(source, alias)
