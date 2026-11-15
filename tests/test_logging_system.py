from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from core.logging_system import configure_logging, log_event, safe_path
from desktop.ipc_server import JsonlIpcServer


def _flush(logger) -> None:
    for handler in logger.logger.handlers:
        handler.flush()


def test_structured_log_redacts_paths_and_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("VIDEO2LIVEPHOTO_SESSION_ID", "session-test")
    logger = configure_logging("test", log_dir=tmp_path, file_name="test.jsonl", force=True)
    request_logger = logger.bind(request_id="request-1", job_id="job-1")
    source = tmp_path / "private source.mp4"
    log_event(
        request_logger,
        "test.event",
        source_path=str(source),
        token="do-not-write",
        duration_ms=12.5,
    )
    _flush(logger)
    record = json.loads((tmp_path / "test.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert record["schema_version"] == "video2livephoto.log.v1"
    assert record["session_id"] == "session-test"
    assert record["request_id"] == "request-1"
    assert record["job_id"] == "job-1"
    assert record["duration_ms"] == 12.5
    assert "private source.mp4" in record["fields"]["source_path"]
    assert str(source) not in json.dumps(record, ensure_ascii=False)
    assert record["fields"]["token"] == "<redacted>"
    assert safe_path({}) == "<invalid-path>"


def test_structured_log_rotates(tmp_path: Path) -> None:
    logger = configure_logging(
        "rotation",
        log_dir=tmp_path,
        file_name="rotation.jsonl",
        max_bytes=250,
        backup_count=2,
        force=True,
    )
    for index in range(20):
        log_event(logger, "rotation.event", index=index, payload="x" * 80)
    _flush(logger)
    assert (tmp_path / "rotation.jsonl").is_file()
    assert (tmp_path / "rotation.jsonl.1").is_file()


def test_ipc_logging_keeps_stdout_jsonl_and_correlates_request(
    tmp_path: Path, monkeypatch
) -> None:
    logger = configure_logging("python-ipc", log_dir=tmp_path, file_name="python.jsonl", force=True)
    stdin = io.StringIO('{"id":"renderer-logging","protocol":"m3.ipc.v1","method":"ping"}\n')
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    assert JsonlIpcServer(logger=logger).run() == 0
    response = json.loads(stdout.getvalue())
    assert response["id"] == "renderer-logging"
    assert response["ok"] is True
    _flush(logger)
    records = [json.loads(line) for line in (tmp_path / "python.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(item["event"] == "ipc.request.start" and item["request_id"] == "renderer-logging" for item in records)
    assert any(item["event"] == "ipc.request.end" and item["request_id"] == "renderer-logging" for item in records)
