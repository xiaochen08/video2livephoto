from __future__ import annotations

import threading
import time

from core.queue import QueueRunner, QueueState, QueueStore, WorkerCancelled


def test_runner_respects_pause_and_completes_successfully(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    first = store.enqueue(clip_id="a", snapshot={"n": 1})
    second = store.enqueue(clip_id="b", snapshot={"n": 2})
    started = threading.Event()

    def worker(job, cancel, report):
        started.set()
        report(0.5, "encoding")
        return {"job": job.job_id}

    runner = QueueRunner(store, worker, max_workers=1)
    runner.pause()
    assert runner.pump() == ()
    assert store.get(first.job_id).state == QueueState.PENDING
    runner.resume()
    runner.wait(timeout=5)
    assert store.get(first.job_id).state == QueueState.SUCCEEDED
    assert store.get(second.job_id).state == QueueState.SUCCEEDED
    runner.close(cancel_running=False)


def test_runner_cancellation_is_persisted_without_success(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    job = store.enqueue(clip_id="a", snapshot={"n": 1})
    started = threading.Event()

    def worker(_job, cancel, report):
        started.set()
        while not cancel.is_set():
            report(0.2, "encoding")
            time.sleep(0.01)
        raise WorkerCancelled("user cancelled")

    runner = QueueRunner(store, worker, max_workers=1)
    runner.pump()
    assert started.wait(2)
    assert runner.cancel(job.job_id)
    runner.wait(timeout=5)
    assert store.get(job.job_id).state == QueueState.INTERRUPTED
    assert store.get(job.job_id).error_code == "CANCELLED"
    runner.close(cancel_running=False)


def test_runner_never_exceeds_two_workers(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    jobs = [store.enqueue(clip_id=str(i), snapshot={"n": i}) for i in range(4)]
    lock = threading.Lock()
    active = 0
    peak = 0

    def worker(_job, _cancel, report):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        report(0.5, "encoding")
        time.sleep(0.03)
        with lock:
            active -= 1
        return {}

    runner = QueueRunner(store, worker, max_workers=2)
    runner.pump()
    runner.wait(timeout=5)
    assert peak == 2
    assert all(store.get(job.job_id).state == QueueState.SUCCEEDED for job in jobs)
    runner.close(cancel_running=False)


def test_runner_can_promote_from_one_to_two_after_success(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    jobs = [store.enqueue(clip_id=str(i), snapshot={"n": i}) for i in range(3)]
    active = 0
    peak = 0
    lock = threading.Lock()

    def worker(_job, _cancel, report):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        report(0.5, "encoding")
        time.sleep(0.03)
        with lock:
            active -= 1
        return {}

    def promote(_job, _result):
        return 2

    runner = QueueRunner(
        store,
        worker,
        max_workers=2,
        initial_workers=1,
        on_job_succeeded=promote,
    )
    assert runner.worker_limit == 1
    runner.pump()
    runner.wait(timeout=5)
    assert runner.worker_limit == 2
    assert peak == 2
    assert all(store.get(job.job_id).state == QueueState.SUCCEEDED for job in jobs)
    runner.close(cancel_running=False)


def test_runner_does_not_promote_after_failed_worker(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    job = store.enqueue(clip_id="failed", snapshot={"n": 1})
    seen: list[object] = []

    def worker(_job, _cancel, _report):
        raise RuntimeError("boom")

    runner = QueueRunner(
        store,
        worker,
        max_workers=2,
        initial_workers=1,
        on_job_succeeded=lambda item, result: seen.append((item.job_id, result)) or 2,
    )
    runner.pump()
    runner.wait(timeout=5)
    assert store.get(job.job_id).state == QueueState.FAILED
    assert seen == []
    assert runner.worker_limit == 1
    runner.close(cancel_running=False)


def test_runner_does_not_commit_success_after_worker_failure(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    job = store.enqueue(clip_id="failed", snapshot={"n": 1})

    def worker(_job, _cancel, _report):
        raise RuntimeError("unknown color metadata")

    runner = QueueRunner(store, worker, max_workers=1)
    runner.pump()
    runner.wait(timeout=5)

    persisted = store.get(job.job_id)
    assert persisted.state == QueueState.FAILED
    assert persisted.error_message == "unknown color metadata"
    runner.close(cancel_running=False)
