from __future__ import annotations

import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

from .store import QueueJob, QueueState, QueueStore


class WorkerCancelled(RuntimeError):
    """Worker stopped because the user cancelled the current task."""


@dataclass
class _Running:
    job: QueueJob
    cancel: threading.Event
    future: Future[Any]


Worker = Callable[
    [QueueJob, threading.Event, Callable[[float, str | None], None]],
    dict[str, Any] | None,
]


class QueueRunner:
    """Small durable scheduler with a hard upper bound of two workers."""

    def __init__(
        self,
        store: QueueStore,
        worker: Worker,
        *,
        max_workers: int = 1,
        initial_workers: int | None = None,
        on_job_succeeded: Callable[[QueueJob, dict[str, Any] | None], int | None]
        | None = None,
    ):
        if max_workers not in (1, 2):
            raise ValueError("M6 allows one or two concurrent export workers")
        if initial_workers is None:
            initial_workers = max_workers
        if initial_workers not in (1, 2) or initial_workers > max_workers:
            raise ValueError("initial_workers must be between one and max_workers")
        self.store = store
        self.worker = worker
        self.max_workers = max_workers
        self._worker_limit = initial_workers
        self._on_job_succeeded = on_job_succeeded
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="v1-export"
        )
        self._running: dict[str, _Running] = {}
        self._lock = threading.RLock()
        self._paused = False
        self._closed = False

    @property
    def running_job_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._running)

    @property
    def worker_limit(self) -> int:
        with self._lock:
            return self._worker_limit

    def set_worker_limit(self, worker_limit: int) -> int:
        if worker_limit not in (1, 2) or worker_limit > self.max_workers:
            raise ValueError("worker_limit must be between one and max_workers")
        with self._lock:
            self._worker_limit = worker_limit
        self.pump()
        return worker_limit

    def _report(self, job_id: str, progress: float, phase: str | None) -> None:
        try:
            self.store.update_progress(job_id, progress, phase)
        except (KeyError, RuntimeError):
            pass

    def _run_one(self, job: QueueJob, cancel: threading.Event) -> dict[str, Any] | None:
        def report(progress: float, phase: str | None = None) -> None:
            if cancel.is_set():
                raise WorkerCancelled("cancelled")
            self._report(job.job_id, progress, phase)

        try:
            result = self.worker(job, cancel, report)
            if cancel.is_set():
                raise WorkerCancelled("cancelled")
            self.store.transition(
                job.job_id, QueueState.VALIDATING, progress=0.9, phase="validating"
            )
            self.store.transition(
                job.job_id, QueueState.COMMITTING, progress=0.97, phase="committing"
            )
            return result
        except WorkerCancelled as exc:
            self.store.transition(
                job.job_id,
                QueueState.INTERRUPTED,
                phase="cancelled",
                error_code="CANCELLED",
                error_message=str(exc),
                user_confirmation_required=False,
            )
            return None
        except Exception as exc:  # worker errors are persisted, not lost in a thread
            self.store.transition(
                job.job_id,
                QueueState.FAILED,
                phase="failed",
                error_code=getattr(exc, "code", "WORKER_FAILED"),
                error_message=str(exc),
            )
            return None

    def _done(self, job: QueueJob, future: Future[Any]) -> None:
        with self._lock:
            self._running.pop(job.job_id, None)
        try:
            result = future.result()
        except Exception:
            return
        try:
            self.store.transition(
                job.job_id,
                QueueState.SUCCEEDED,
                progress=1.0,
                phase="succeeded",
                result=result or {},
            )
        except Exception:
            # A missing/invalid transition must leave a durable failure rather than
            # making a half-committed result look successful.
            try:
                self.store.transition(
                    job.job_id,
                    QueueState.FAILED,
                    error_code="STATE_COMMIT_FAILED",
                    error_message="无法提交任务状态",
                )
            except Exception:
                pass
        if self._on_job_succeeded is not None:
            try:
                new_limit = self._on_job_succeeded(job, result)
                if new_limit is not None:
                    self.set_worker_limit(new_limit)
            except Exception:
                # A capacity probe must never turn a completed export into a
                # failed queue state.
                pass
        self.pump()

    def pump(self) -> tuple[str, ...]:
        with self._lock:
            if self._paused or self._closed:
                return self.running_job_ids
            while len(self._running) < self._worker_limit:
                job = self.store.claim(worker_pid=os.getpid())
                if job is None:
                    break
                cancel = threading.Event()
                future = self._executor.submit(self._run_one, job, cancel)
                self._running[job.job_id] = _Running(job, cancel, future)
                future.add_done_callback(lambda f, j=job: self._done(j, f))
            return self.running_job_ids

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> tuple[str, ...]:
        with self._lock:
            self._paused = False
        return self.pump()

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            running = self._running.get(job_id)
            if running:
                running.cancel.set()
                return True
        job = self.store.get(job_id)
        if job.state == QueueState.PENDING:
            self.store.transition(
                job_id,
                QueueState.SKIPPED,
                phase="cancelled",
                error_code="CANCELLED",
                error_message="用户取消",
            )
            return True
        return False

    def cancel_all(self) -> None:
        for job_id in self.running_job_ids:
            self.cancel(job_id)

    def wait(self, timeout: float | None = None) -> None:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                futures = [item.future for item in self._running.values()]
                running = bool(self._running)
            for future in futures:
                remaining = (
                    None if deadline is None else max(0.0, deadline - time.monotonic())
                )
                future.result(timeout=remaining)
            if not running:
                return
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("queue runner did not become idle")
            time.sleep(0.005)

    def close(self, *, cancel_running: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if cancel_running:
            self.cancel_all()
        self._executor.shutdown(wait=True, cancel_futures=False)
