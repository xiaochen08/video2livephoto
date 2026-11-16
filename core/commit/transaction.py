from __future__ import annotations

import errno
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from core.media.source_identity import capture_identity, identities_match
from core.protocol.media import SourceIdentity


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class CommitArtifact:
    """A validated file produced under a job's private temporary directory."""

    temporary_path: str
    relative_target: str
    expected_sha256: str | None = None
    expected_size: int | None = None


@dataclass(frozen=True)
class CommitResult:
    transaction_id: str
    state: str
    target_paths: tuple[str, ...]
    backup_dir: str | None
    manifest_path: str
    file_hashes: dict[str, str]


class CommitError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        diagnostics: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.diagnostics = diagnostics or {}


def _safe_relative_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not relative:
        raise CommitError("INVALID_TARGET", f"非法输出相对路径: {relative}")
    return path


def _is_disk_full(exc: OSError) -> bool:
    return exc.errno in {errno.ENOSPC, errno.EDQUOT, 112, 39}


class CommitTransaction:
    """Commit a complete MP4/LIVP set with a recoverable journal.

    Outputs are written to a private temporary directory by the encoder.  This
    class verifies every file and the source identity before moving anything;
    old outputs are moved to a same-volume backup before new files are
    published.  A journal is fsynced before the first replace operation.
    """

    def __init__(
        self,
        *,
        target_dir: str | os.PathLike[str],
        transaction_root: str | os.PathLike[str],
        source_path: str | os.PathLike[str] | None = None,
        source_identity: SourceIdentity | None = None,
        transaction_id: str | None = None,
    ):
        self.target_dir = Path(target_dir).resolve()
        self.transaction_root = Path(transaction_root).resolve()
        self.transaction_id = transaction_id or uuid.uuid4().hex
        self.source_path = Path(source_path).resolve() if source_path else None
        self.source_identity = source_identity
        self.work_dir = self.transaction_root / self.transaction_id
        self.backup_dir = self.work_dir / "backup"
        self.manifest_path = self.work_dir / "transaction.json"
        self._state = "new"

    def _write_journal(
        self,
        *,
        state: str,
        artifacts: list[dict[str, Any]],
        files: list[dict[str, Any]] | None = None,
    ) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "transaction_id": self.transaction_id,
            "state": state,
            "target_dir": str(self.target_dir),
            "backup_dir": str(self.backup_dir),
            "source_path": str(self.source_path) if self.source_path else None,
            "artifacts": artifacts,
            "files": files or [],
            "updated_at": _now(),
        }
        temporary = self.manifest_path.with_suffix(".partial.json")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.manifest_path)
        except OSError as exc:
            raise CommitError(
                "TRANSACTION_JOURNAL_FAILED",
                "无法写入提交事务日志",
                retryable=_is_disk_full(exc),
            ) from exc
        self._state = state

    def _verify_source(self) -> None:
        if not self.source_path or not self.source_identity:
            return
        current = capture_identity(self.source_path)
        if not identities_match(self.source_identity, current):
            raise CommitError(
                "SOURCE_CHANGED",
                "源文件在导出期间发生变化",
                diagnostics={"path": str(self.source_path)},
            )

    def _verify_artifacts(
        self, artifacts: Iterable[CommitArtifact]
    ) -> list[dict[str, Any]]:
        self._verify_source()
        root = self.work_dir.resolve()
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for artifact in artifacts:
            temporary = Path(artifact.temporary_path).resolve()
            relative = _safe_relative_path(artifact.relative_target)
            if str(relative).replace("\\", "/") in seen:
                raise CommitError("DUPLICATE_TARGET", f"重复输出目标: {relative}")
            seen.add(str(relative).replace("\\", "/"))
            try:
                temporary.relative_to(root)
            except ValueError as exc:
                raise CommitError(
                    "TEMP_PATH_ESCAPE", "临时文件不在任务私有目录内"
                ) from exc
            if not temporary.is_file() or temporary.name.endswith(".partial"):
                raise CommitError("INCOMPLETE_OUTPUT", f"输出尚未完成: {temporary}")
            try:
                size = temporary.stat().st_size
                digest = _sha256(temporary)
            except OSError as exc:
                raise CommitError(
                    "OUTPUT_READ_FAILED", "无法读取待提交输出", retryable=True
                ) from exc
            if artifact.expected_size is not None and size != artifact.expected_size:
                raise CommitError("OUTPUT_SIZE_MISMATCH", f"输出大小不匹配: {relative}")
            if (
                artifact.expected_sha256
                and digest.lower() != artifact.expected_sha256.lower()
            ):
                raise CommitError("OUTPUT_HASH_MISMATCH", f"输出哈希不匹配: {relative}")
            records.append(
                {
                    "temporary_path": str(temporary),
                    "relative_target": str(relative),
                    "size": size,
                    "sha256": digest,
                }
            )
        if not records:
            raise CommitError("NO_OUTPUTS", "没有可提交的输出文件")
        return records

    def commit(
        self,
        artifacts: Iterable[CommitArtifact],
        *,
        validator: Callable[[list[dict[str, Any]]], Any] | None = None,
    ) -> CommitResult:
        records = self._verify_artifacts(artifacts)
        if validator is not None:
            try:
                valid = validator(records)
            except CommitError:
                raise
            except Exception as exc:
                raise CommitError(
                    "OUTPUT_VALIDATION_FAILED", "输出校验异常", retryable=True
                ) from exc
            if valid is False:
                raise CommitError("OUTPUT_VALIDATION_FAILED", "输出校验未通过")
        self._write_journal(state="verified", artifacts=records)
        committed: list[dict[str, Any]] = []
        try:
            self.target_dir.mkdir(parents=True, exist_ok=True)
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            planned: list[dict[str, Any]] = []
            for record in records:
                relative = Path(record["relative_target"])
                target = self.target_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                backup = self.backup_dir / relative
                planned.append(
                    {
                        **record,
                        "target_path": str(target),
                        "backup_path": str(backup) if target.exists() else None,
                    }
                )
            # Persist the complete recovery plan before moving the first old
            # output.  A crash between the first backup move and this journal
            # write would otherwise leave a ``verified`` journal with no file
            # records and make recovery unable to restore the old output.
            self._write_journal(state="committing", artifacts=records, files=planned)
            for record in planned:
                target = Path(record["target_path"])
                backup_name = record.get("backup_path")
                backup = Path(backup_name) if backup_name else None
                if backup and target.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, backup)
                committed.append(record)
            for record in committed:
                os.replace(record["temporary_path"], record["target_path"])
            self._verify_source()
            self._write_journal(state="committed", artifacts=records, files=committed)
            return CommitResult(
                transaction_id=self.transaction_id,
                state="committed",
                target_paths=tuple(record["target_path"] for record in committed),
                backup_dir=str(self.backup_dir)
                if any(record["backup_path"] for record in committed)
                else None,
                manifest_path=str(self.manifest_path),
                file_hashes={
                    record["target_path"]: record["sha256"] for record in committed
                },
            )
        except CommitError:
            self._rollback(committed)
            raise
        except OSError as exc:
            self._rollback(committed)
            if _is_disk_full(exc):
                raise CommitError(
                    "DISK_FULL", "磁盘空间不足，旧版输出已恢复", retryable=True
                ) from exc
            raise CommitError(
                "OUTPUT_LOCKED",
                "输出文件被占用或无法替换，旧版输出已恢复",
                retryable=True,
            ) from exc
        except Exception as exc:
            self._rollback(committed)
            raise CommitError(
                "COMMIT_FAILED", "提交失败，旧版输出已恢复", retryable=True
            ) from exc

    def _rollback(self, files: list[dict[str, Any]]) -> None:
        for record in reversed(files):
            target = Path(record["target_path"])
            backup = Path(record["backup_path"]) if record.get("backup_path") else None
            try:
                if target.exists():
                    target.unlink()
            except OSError:
                pass
            if backup and backup.exists():
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, target)
                except OSError:
                    pass
        try:
            self._write_journal(state="rolled_back", artifacts=[], files=files)
        except CommitError:
            pass


def recover_transaction(manifest_path: str | os.PathLike[str]) -> str:
    """Recover a transaction after process death.

    Returns ``committed`` when every published file hashes as recorded,
    ``rolled_back`` when backups can be restored, and raises a structured
    ``CommitError`` if neither complete state is available.
    """
    manifest = Path(manifest_path)
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CommitError("TRANSACTION_LOG_INVALID", "提交事务日志损坏") from exc
    state = payload.get("state")
    files = payload.get("files") or []
    if state == "committed":
        for record in files:
            target = Path(record["target_path"])
            if not target.is_file() or _sha256(target) != record["sha256"]:
                raise CommitError(
                    "COMMITTED_OUTPUT_MISSING", "已提交输出不完整，需要人工处理"
                )
        return "committed"
    if state not in {"committing", "verified"}:
        return str(state or "unknown")
    for record in reversed(files):
        target = Path(record["target_path"])
        backup_name = record.get("backup_path")
        backup = Path(backup_name) if backup_name else None
        try:
            if target.exists() and backup and backup.exists():
                target.unlink()
            if backup and backup.exists() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)
        except OSError as exc:
            raise CommitError(
                "RECOVERY_FAILED", "无法恢复旧版输出", retryable=True
            ) from exc
    return "rolled_back"
