from __future__ import annotations

import hashlib
import os
from pathlib import Path

from core.protocol.media import MediaError, SourceIdentity

_SAMPLE_SIZE = 64 * 1024


def _sampled_fingerprint(path: Path) -> str:
    size = path.stat().st_size
    offsets = sorted(
        {0, max(0, (size - _SAMPLE_SIZE) // 2), max(0, size - _SAMPLE_SIZE)}
    )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for offset in offsets:
            handle.seek(offset)
            chunk = handle.read(min(_SAMPLE_SIZE, max(0, size - offset)))
            digest.update(offset.to_bytes(8, "big"))
            digest.update(len(chunk).to_bytes(8, "big"))
            digest.update(chunk)
    return digest.hexdigest()


def _full_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _physical_file_id(path: Path) -> str | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if stat.st_ino:
        return f"{stat.st_dev}:{stat.st_ino}"
    return None


def capture_identity(
    path: str | os.PathLike[str], *, include_full_sha256: bool = False
) -> SourceIdentity:
    try:
        canonical = Path(path).resolve(strict=True)
        stat = canonical.stat()
    except (FileNotFoundError, OSError) as exc:
        raise MediaError(
            code="SOURCE_NOT_FOUND",
            stage="identity",
            path=str(path),
            stream_index=None,
            retryable=False,
            message="源文件不存在或无法读取",
        ) from exc
    if not canonical.is_file():
        raise MediaError(
            code="SOURCE_NOT_FILE",
            stage="identity",
            path=str(canonical),
            stream_index=None,
            retryable=False,
            message="输入路径不是普通文件",
        )
    return SourceIdentity(
        canonical_path=str(canonical),
        physical_file_id=_physical_file_id(canonical),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sampled_fingerprint=_sampled_fingerprint(canonical),
        full_sha256=_full_sha256(canonical) if include_full_sha256 else None,
    )


def identities_match(before: SourceIdentity, after: SourceIdentity) -> bool:
    return (
        before.canonical_path == after.canonical_path
        and before.size == after.size
        and before.mtime_ns == after.mtime_ns
        and before.sampled_fingerprint == after.sampled_fingerprint
        and (
            before.physical_file_id is None
            or after.physical_file_id is None
            or before.physical_file_id == after.physical_file_id
        )
    )


def paths_refer_same_file(
    left: str | os.PathLike[str], right: str | os.PathLike[str]
) -> bool:
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError):
        try:
            return Path(left).resolve(strict=False) == Path(right).resolve(strict=False)
        except OSError:
            return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
                os.path.abspath(str(right))
            )
