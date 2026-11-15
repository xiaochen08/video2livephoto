from __future__ import annotations

from pathlib import Path

from core.commit import (
    CommitArtifact,
    CommitError,
    CommitTransaction,
    recover_transaction,
)


def _artifact(
    tmp_path: Path, name: str, content: bytes, root: Path | None = None
) -> CommitArtifact:
    path = (root or (tmp_path / "tx")) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return CommitArtifact(str(path), name)


def test_commit_validates_and_keeps_old_file_in_backup(tmp_path):
    target = tmp_path / "output"
    target.mkdir()
    (target / "clip.mp4").write_bytes(b"old")
    tx = CommitTransaction(
        target_dir=target, transaction_root=tmp_path / "transactions"
    )
    artifact = _artifact(tmp_path, "clip.mp4", b"new", tx.work_dir)
    result = tx.commit([artifact])
    assert result.state == "committed"
    assert (target / "clip.mp4").read_bytes() == b"new"
    assert result.backup_dir is not None
    assert Path(result.backup_dir, "clip.mp4").read_bytes() == b"old"
    assert recover_transaction(result.manifest_path) == "committed"


def test_partial_output_is_rejected_without_touching_old(tmp_path):
    target = tmp_path / "output"
    target.mkdir()
    (target / "clip.mp4").write_bytes(b"old")
    tx = CommitTransaction(
        target_dir=target, transaction_root=tmp_path / "transactions"
    )
    path = tx.work_dir / "clip.mp4.partial"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"partial")
    try:
        tx.commit([CommitArtifact(str(path), "clip.mp4")])
    except CommitError as exc:
        assert exc.code == "INCOMPLETE_OUTPUT"
    else:
        raise AssertionError("partial output was committed")
    assert (target / "clip.mp4").read_bytes() == b"old"


def test_source_change_is_rejected(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    from core.media.source_identity import capture_identity

    identity = capture_identity(source)
    source.write_bytes(b"changed")
    tx = CommitTransaction(
        target_dir=tmp_path / "output",
        transaction_root=tmp_path / "transactions",
        source_path=source,
        source_identity=identity,
    )
    artifact = _artifact(tmp_path, "clip.mp4", b"new", tx.work_dir)
    try:
        tx.commit([artifact])
    except CommitError as exc:
        assert exc.code == "SOURCE_CHANGED"
    else:
        raise AssertionError("changed source was accepted")


def test_recovery_restores_backup_from_committing_journal(tmp_path):
    target = tmp_path / "output"
    target.mkdir()
    old = target / "clip.mp4"
    old.write_bytes(b"old")
    tx = CommitTransaction(
        target_dir=target, transaction_root=tmp_path / "transactions"
    )
    tx.backup_dir.mkdir(parents=True)
    backup = tx.backup_dir / "clip.mp4"
    old.replace(backup)
    record = {
        "temporary_path": str(tx.work_dir / "clip.mp4"),
        "relative_target": "clip.mp4",
        "size": 3,
        "sha256": "new-output-hash",
        "target_path": str(old),
        "backup_path": str(backup),
    }
    tx._write_journal(state="committing", artifacts=[record], files=[record])

    assert recover_transaction(tx.manifest_path) == "rolled_back"
    assert old.read_bytes() == b"old"
    assert not backup.exists()
