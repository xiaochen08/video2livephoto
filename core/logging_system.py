"""Structured local logging for the Video2LivePhoto desktop stack.

The renderer never writes log files directly. Electron and the Python worker
write separate JSONL files using the same event schema so diagnostics can merge
them by ``timestamp`` and ``request_id`` without competing for one rotating
file handle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import logging.handlers
import ntpath
import os
import re
import sys
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

APP_NAME = "Video2LivePhoto"
LOGGER_NAME = "video2livephoto"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5
_configured_files: set[str] = set()

_PATH_KEYS = {
    "path",
    "source_path",
    "project_path",
    "output_dir",
    "temp_dir",
    "file_path",
    "frame_index_path",
    "cache_root",
    "log_dir",
}
_SECRET_KEYS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "api_key",
    "private_key",
}
_WINDOWS_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"']+")


def default_log_dir(app_name: str = APP_NAME) -> Path:
    override = os.environ.get("VIDEO2LIVEPHOTO_LOG_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / app_name / "logs"
        return Path.home() / "AppData" / "Local" / app_name / "logs"
    return Path.home() / ".local" / "share" / app_name / "logs"


def _path_basename(value: str) -> str:
    return ntpath.basename(value.replace("/", "\\")) or "<root>"


def safe_path(value: Any) -> str | None:
    if value is None:
        return None
    try:
        text = os.fspath(value)
    except TypeError:
        return "<invalid-path>"
    digest = hashlib.sha256(os.path.normcase(text).encode("utf-8", "replace")).hexdigest()[:12]
    drive = ntpath.splitdrive(text)[0]
    prefix = f"{drive}\\…" if drive else "…"
    return f"{prefix}\\{_path_basename(text)}#{digest}"


def _sanitize(value: Any, key: str | None = None, depth: int = 0) -> Any:
    if depth > 5:
        return "<depth-limit>"
    normalized_key = (key or "").lower()
    if normalized_key in _SECRET_KEYS or any(secret in normalized_key for secret in _SECRET_KEYS):
        return "<redacted>"
    if normalized_key in _PATH_KEYS or normalized_key.endswith("_path") or normalized_key.endswith("_dir"):
        return safe_path(value)
    if isinstance(value, Mapping):
        return {str(k): _sanitize(v, str(k), depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item, depth=depth + 1) for item in value]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, str):
        if len(value) > 4000:
            value = value[:4000] + "…<truncated>"
        return _WINDOWS_PATH_RE.sub(lambda match: safe_path(match.group(0)) or "<path>", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return repr(value)


def sanitize_fields(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    return {str(key): _sanitize(value, str(key)) for key, value in (fields or {}).items()}


class JsonlFormatter(logging.Formatter):
    def __init__(self, component: str, app_version: str | None = None) -> None:
        super().__init__()
        self.component = component
        self.app_version = app_version

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "schema_version": "video2livephoto.log.v1",
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "component": self.component,
            "event": getattr(record, "event", record.getMessage()),
            "message": _sanitize(record.getMessage()),
            "process_id": record.process,
            "thread": record.threadName,
        }
        if self.app_version:
            payload["app_version"] = self.app_version
        for key in ("session_id", "request_id", "job_id", "method", "error_code", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        fields = getattr(record, "fields", None)
        if fields:
            sanitized_fields = sanitize_fields(fields)
            payload["fields"] = sanitized_fields
            for key in ("project_id", "clip_id", "error_code", "duration_ms", "progress", "phase", "worker_limit", "job_count", "ok"):
                if key in sanitized_fields:
                    payload[key] = sanitized_fields[key]
        if record.exc_info:
            payload["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Exception",
                "message": str(record.exc_info[1]),
                "traceback": _WINDOWS_PATH_RE.sub(lambda match: safe_path(match.group(0)) or "<path>", "".join(traceback.format_exception(*record.exc_info))[-12000:]),
            }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class ContextAdapter(logging.LoggerAdapter[logging.Logger]):
    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        extra = dict(kwargs.get("extra") or {})
        fields = dict(extra.get("fields") or {})
        fields.update(self.extra.get("fields") or {})
        extra["fields"] = fields
        for key in ("session_id", "request_id", "job_id", "method"):
            if key in self.extra:
                extra[key] = self.extra[key]
        kwargs["extra"] = extra
        return msg, kwargs

    def bind(self, **context: Any) -> "ContextAdapter":
        merged = dict(self.extra)
        fields = dict(merged.get("fields") or {})
        fields.update(context.pop("fields", {}) or {})
        merged.update(context)
        merged["fields"] = fields
        return ContextAdapter(self.logger, merged)


def configure_logging(
    component: str,
    *,
    log_dir: str | os.PathLike[str] | None = None,
    level: int | str | None = None,
    app_version: str | None = None,
    file_name: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    force: bool = False,
) -> ContextAdapter:
    directory = Path(log_dir) if log_dir is not None else default_log_dir()
    target = (directory / (file_name or f"{component}.jsonl")).resolve()
    root_logger = logging.getLogger(LOGGER_NAME)
    root_logger.setLevel(level or os.environ.get("VIDEO2LIVEPHOTO_LOG_LEVEL", "INFO"))
    root_logger.propagate = False
    key = str(target)
    if force:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()
        _configured_files.clear()
    if key not in _configured_files:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            for old_handler in list(root_logger.handlers):
                if getattr(old_handler, "_video2livephoto_fallback", False):
                    root_logger.removeHandler(old_handler)
                    old_handler.close()
            handler = logging.handlers.RotatingFileHandler(
                target,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
                delay=True,
            )
            handler.setFormatter(JsonlFormatter(component, app_version))
            root_logger.addHandler(handler)
            _configured_files.add(key)
        except OSError:
            fallback = logging.StreamHandler(sys.stderr)
            fallback._video2livephoto_fallback = True
            fallback.setFormatter(JsonlFormatter(component, app_version))
            root_logger.addHandler(fallback)
    if not root_logger.handlers:
        root_logger.addHandler(logging.NullHandler())
    session_id = os.environ.get("VIDEO2LIVEPHOTO_SESSION_ID") or str(uuid.uuid4())
    return ContextAdapter(root_logger, {"session_id": session_id, "fields": {}})


def get_logger(component: str | None = None, **context: Any) -> ContextAdapter:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    fields = context.pop("fields", {})
    context["fields"] = fields
    if component:
        context["fields"] = {"component": component, **fields}
    return ContextAdapter(logger, context)


def log_event(logger: ContextAdapter, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, event, extra={"event": event, "fields": fields})


def install_uncaught_exception_logging(logger: ContextAdapter) -> None:
    def handle(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        logger.critical("process.uncaught_exception", exc_info=(exc_type, exc, tb), extra={"event": "process.uncaught_exception"})
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = handle
    if hasattr(threading, "excepthook"):
        def handle_thread(args: Any) -> None:
            logger.critical(
                "process.thread_exception",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                extra={"event": "process.thread_exception", "fields": {"thread": args.thread.name if args.thread else None}},
            )
        threading.excepthook = handle_thread


__all__ = [
    "ContextAdapter",
    "configure_logging",
    "default_log_dir",
    "get_logger",
    "install_uncaught_exception_logging",
    "log_event",
    "safe_path",
    "sanitize_fields",
]
