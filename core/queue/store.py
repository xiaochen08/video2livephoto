from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1


class QueueState(StrEnum):
    PENDING = "pending"  # 待执行
    PROCESSING = "processing"  # 处理中
    VALIDATING = "validating"  # 校验中
    COMMITTING = "committing"  # 提交中
    SUCCEEDED = "succeeded"  # 成功
    FAILED = "failed"  # 失败
    SKIPPED = "skipped"  # 已跳过
    STALE = "stale"  # 待更新
    INTERRUPTED = "interrupted"  # 已中断，需要用户确认


STATE_LABELS = {
    QueueState.PENDING: "待执行",
    QueueState.PROCESSING: "处理中",
    QueueState.VALIDATING: "校验中",
    QueueState.COMMITTING: "提交中",
    QueueState.SUCCEEDED: "成功",
    QueueState.FAILED: "失败",
    QueueState.SKIPPED: "已跳过",
    QueueState.STALE: "待更新",
    QueueState.INTERRUPTED: "已中断",
}


class QueueTransitionError(RuntimeError):
    """Raised when a persisted task transition would violate the state machine."""


class QueueRecoveryRequired(RuntimeError):
    """Raised if callers try to resume interrupted work without confirmation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_snapshot_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QueueJob:
    job_id: str
    clip_id: str
    state: QueueState
    snapshot: dict[str, Any]
    snapshot_hash: str
    progress: float
    phase: str | None
    attempt_count: int
    retry_limit: int
    temp_dir: str | None
    output_dir: str | None
    source_identity: dict[str, Any] | None
    worker_pid: int | None
    error_code: str | None
    error_message: str | None
    result: dict[str, Any] | None
    user_confirmation_required: bool
    transaction_id: str | None
    created_at: str
    updated_at: str


_TRANSITIONS: dict[QueueState, set[QueueState]] = {
    QueueState.PENDING: {
        QueueState.PROCESSING,
        QueueState.SKIPPED,
        QueueState.STALE,
        QueueState.INTERRUPTED,
    },
    QueueState.PROCESSING: {
        QueueState.VALIDATING,
        QueueState.FAILED,
        QueueState.INTERRUPTED,
        QueueState.SKIPPED,
    },
    QueueState.VALIDATING: {
        QueueState.COMMITTING,
        QueueState.FAILED,
        QueueState.INTERRUPTED,
    },
    QueueState.COMMITTING: {
        QueueState.SUCCEEDED,
        QueueState.FAILED,
        QueueState.INTERRUPTED,
    },
    QueueState.FAILED: {
        QueueState.PENDING,
        QueueState.SKIPPED,
        QueueState.STALE,
    },
    QueueState.INTERRUPTED: {
        QueueState.PENDING,
        QueueState.SKIPPED,
        QueueState.STALE,
    },
    QueueState.STALE: {QueueState.PENDING, QueueState.SKIPPED},
    QueueState.SUCCEEDED: {QueueState.STALE},
    QueueState.SKIPPED: {QueueState.PENDING},
}


class QueueStore:
    """SQLite-backed queue store.

    Every operation opens its own connection.  This keeps the store safe when
    workers run in separate threads or processes and avoids sharing a SQLite
    connection across a worker boundary.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS queue_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS queue_jobs (
                    job_id TEXT PRIMARY KEY,
                    clip_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    snapshot_hash TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    phase TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    retry_limit INTEGER NOT NULL DEFAULT 2,
                    temp_dir TEXT,
                    output_dir TEXT,
                    source_identity_json TEXT,
                    worker_pid INTEGER,
                    error_code TEXT,
                    error_message TEXT,
                    result_json TEXT,
                    user_confirmation_required INTEGER NOT NULL DEFAULT 0,
                    transaction_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_queue_jobs_state ON queue_jobs(state, created_at);
                CREATE INDEX IF NOT EXISTS idx_queue_jobs_clip ON queue_jobs(clip_id);
                """
            )
            db.execute(
                "INSERT OR IGNORE INTO queue_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def enqueue(
        self,
        *,
        clip_id: str,
        snapshot: dict[str, Any],
        source_identity: dict[str, Any] | None = None,
        temp_dir: str | None = None,
        output_dir: str | None = None,
        retry_limit: int = 2,
        job_id: str | None = None,
    ) -> QueueJob:
        if retry_limit < 0:
            raise ValueError("retry_limit must be non-negative")
        job_id = job_id or str(uuid.uuid4())
        stamp = _now()
        snapshot_hash = compute_snapshot_hash(snapshot)
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO queue_jobs(
                    job_id, clip_id, state, snapshot_json, snapshot_hash,
                    progress, retry_limit, temp_dir, output_dir,
                    source_identity_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    clip_id,
                    QueueState.PENDING.value,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    snapshot_hash,
                    retry_limit,
                    temp_dir,
                    output_dir,
                    json.dumps(source_identity, ensure_ascii=False, sort_keys=True)
                    if source_identity is not None
                    else None,
                    stamp,
                    stamp,
                ),
            )
        return self.get(job_id)

    def _row_to_job(self, row: sqlite3.Row) -> QueueJob:
        return QueueJob(
            job_id=row["job_id"],
            clip_id=row["clip_id"],
            state=QueueState(row["state"]),
            snapshot=json.loads(row["snapshot_json"]),
            snapshot_hash=row["snapshot_hash"],
            progress=float(row["progress"]),
            phase=row["phase"],
            attempt_count=int(row["attempt_count"]),
            retry_limit=int(row["retry_limit"]),
            temp_dir=row["temp_dir"],
            output_dir=row["output_dir"],
            source_identity=json.loads(row["source_identity_json"])
            if row["source_identity_json"]
            else None,
            worker_pid=row["worker_pid"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            user_confirmation_required=bool(row["user_confirmation_required"]),
            transaction_id=row["transaction_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get(self, job_id: str) -> QueueJob:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM queue_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._row_to_job(row)

    def list(self, states: Iterable[QueueState] | None = None) -> list[QueueJob]:
        with self._connect() as db:
            if states:
                values = [QueueState(s).value for s in states]
                marks = ",".join("?" for _ in values)
                rows = db.execute(
                    f"SELECT * FROM queue_jobs WHERE state IN ({marks}) ORDER BY created_at",
                    values,
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM queue_jobs ORDER BY created_at"
                ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def transition(
        self,
        job_id: str,
        state: QueueState,
        *,
        phase: str | None = None,
        progress: float | None = None,
        attempt_count: int | None = None,
        worker_pid: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        result: dict[str, Any] | None = None,
        user_confirmation_required: bool | None = None,
        transaction_id: str | None = None,
        clear_error: bool = False,
    ) -> QueueJob:
        state = QueueState(state)
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM queue_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            current = QueueState(row["state"])
            if state != current and state not in _TRANSITIONS[current]:
                raise QueueTransitionError(
                    f"{current.value} -> {state.value} is not allowed"
                )
            fields: dict[str, Any] = {"state": state.value, "updated_at": _now()}
            if phase is not None:
                fields["phase"] = phase
            if progress is not None:
                fields["progress"] = max(0.0, min(1.0, float(progress)))
            if attempt_count is not None:
                fields["attempt_count"] = int(attempt_count)
            if worker_pid is not None:
                fields["worker_pid"] = worker_pid
            elif state in {
                QueueState.SUCCEEDED,
                QueueState.FAILED,
                QueueState.SKIPPED,
                QueueState.INTERRUPTED,
            }:
                fields["worker_pid"] = None
            if error_code is not None:
                fields["error_code"] = error_code
            if error_message is not None:
                fields["error_message"] = error_message
            if clear_error:
                fields["error_code"] = None
                fields["error_message"] = None
            if result is not None:
                fields["result_json"] = json.dumps(
                    result, ensure_ascii=False, sort_keys=True
                )
            if user_confirmation_required is not None:
                fields["user_confirmation_required"] = int(user_confirmation_required)
            if transaction_id is not None:
                fields["transaction_id"] = transaction_id
            assignments = ", ".join(f"{name}=?" for name in fields)
            db.execute(
                f"UPDATE queue_jobs SET {assignments} WHERE job_id=?",
                [*fields.values(), job_id],
            )
        return self.get(job_id)

    def update_progress(
        self, job_id: str, progress: float, phase: str | None = None
    ) -> QueueJob:
        return self.transition(
            job_id, self.get(job_id).state, progress=progress, phase=phase
        )

    def claim(self, *, worker_pid: int | None = None) -> QueueJob | None:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM queue_jobs WHERE state=? ORDER BY created_at LIMIT 1",
                (QueueState.PENDING.value,),
            ).fetchone()
            if row is None:
                return None
            now = _now()
            db.execute(
                "UPDATE queue_jobs SET state=?, attempt_count=attempt_count+1, worker_pid=?, updated_at=? WHERE job_id=?",
                (QueueState.PROCESSING.value, worker_pid, now, row["job_id"]),
            )
        return self.get(row["job_id"])

    def mark_interrupted_for_restart(self) -> list[QueueJob]:
        """Mark active work interrupted; never starts workers automatically."""
        with self._lock, self._connect() as db:
            stamp = _now()
            rows = db.execute(
                "SELECT job_id FROM queue_jobs WHERE state IN (?, ?, ?)",
                (
                    QueueState.PROCESSING.value,
                    QueueState.VALIDATING.value,
                    QueueState.COMMITTING.value,
                ),
            ).fetchall()
            if rows:
                db.execute(
                    """
                    UPDATE queue_jobs
                    SET state=?, user_confirmation_required=1,
                        error_code='PROCESS_INTERRUPTED',
                        error_message='程序退出后需要用户确认才能继续',
                        worker_pid=NULL, updated_at=?
                    WHERE state IN (?, ?, ?)
                    """,
                    (
                        QueueState.INTERRUPTED.value,
                        stamp,
                        QueueState.PROCESSING.value,
                        QueueState.VALIDATING.value,
                        QueueState.COMMITTING.value,
                    ),
                )
        return [self.get(row["job_id"]) for row in rows]

    def confirm_recovery(self, job_ids: Iterable[str]) -> list[QueueJob]:
        recovered: list[QueueJob] = []
        for job_id in job_ids:
            job = self.get(job_id)
            if job.state != QueueState.INTERRUPTED:
                raise QueueTransitionError(f"{job_id} is not interrupted")
            recovered.append(
                self.transition(
                    job_id,
                    QueueState.PENDING,
                    progress=0.0,
                    phase="recovery-confirmed",
                    user_confirmation_required=False,
                    error_code=None,
                    error_message=None,
                    clear_error=True,
                )
            )
        return recovered

    def retry(self, job_id: str) -> QueueJob:
        job = self.get(job_id)
        if job.state not in {QueueState.FAILED, QueueState.INTERRUPTED}:
            raise QueueTransitionError("only failed or interrupted jobs can be retried")
        if job.attempt_count >= job.retry_limit + 1:
            raise QueueTransitionError("retry limit reached")
        return self.transition(
            job_id,
            QueueState.PENDING,
            progress=0.0,
            phase="retry-pending",
            error_code=None,
            error_message=None,
            user_confirmation_required=False,
            clear_error=True,
        )

    def mark_stale_if_snapshot_changed(
        self, job_id: str, snapshot: dict[str, Any]
    ) -> QueueJob:
        job = self.get(job_id)
        expected = compute_snapshot_hash(snapshot)
        if expected == job.snapshot_hash:
            return job
        return self.transition(
            job_id,
            QueueState.STALE,
            phase="snapshot-changed",
            error_code="SNAPSHOT_CHANGED",
            error_message="导出快照已变化，需要重新确认",
            user_confirmation_required=True,
        )
