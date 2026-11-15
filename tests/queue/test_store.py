from __future__ import annotations

from core.queue import (
    QueueState,
    QueueStore,
    QueueTransitionError,
    compute_snapshot_hash,
)


def test_snapshot_hash_is_stable_and_queue_persists_recovery(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    snapshot = {"clip_id": "clip-1", "frames": [0, 5], "audio": True}
    assert compute_snapshot_hash(snapshot) == compute_snapshot_hash(
        {"audio": True, "frames": [0, 5], "clip_id": "clip-1"}
    )
    job = store.enqueue(clip_id="clip-1", snapshot=snapshot, retry_limit=2)
    claimed = store.claim(worker_pid=123)
    assert claimed is not None and claimed.job_id == job.job_id
    assert claimed.attempt_count == 1
    interrupted = store.mark_interrupted_for_restart()
    assert [item.job_id for item in interrupted] == [job.job_id]
    assert store.get(job.job_id).user_confirmation_required
    assert store.list(states=[QueueState.PENDING]) == []
    recovered = store.confirm_recovery([job.job_id])[0]
    assert recovered.state == QueueState.PENDING
    assert not recovered.user_confirmation_required


def test_transition_guard_retry_and_stale_snapshot(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    job = store.enqueue(clip_id="clip-1", snapshot={"version": 1}, retry_limit=1)
    try:
        store.transition(job.job_id, QueueState.SUCCEEDED)
    except QueueTransitionError:
        pass
    else:
        raise AssertionError("invalid transition was accepted")
    stale = store.mark_stale_if_snapshot_changed(job.job_id, {"version": 2})
    assert stale.state == QueueState.STALE
    assert stale.user_confirmation_required
    pending = store.transition(
        job.job_id, QueueState.PENDING, user_confirmation_required=False
    )
    assert pending.state == QueueState.PENDING


def test_failed_job_can_retry_until_limit(tmp_path):
    store = QueueStore(tmp_path / "queue.sqlite3")
    job = store.enqueue(clip_id="clip-1", snapshot={"version": 1}, retry_limit=1)
    store.claim()
    failed = store.transition(
        job.job_id, QueueState.FAILED, error_code="ENCODER_FAILED", error_message="boom"
    )
    assert failed.attempt_count == 1
    retry = store.retry(job.job_id)
    assert retry.state == QueueState.PENDING
    store.claim()
    store.transition(job.job_id, QueueState.FAILED, error_code="ENCODER_FAILED")
    try:
        store.retry(job.job_id)
    except QueueTransitionError:
        pass
    else:
        raise AssertionError("retry limit was not enforced")
