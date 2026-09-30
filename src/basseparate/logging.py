"""Structured logging for basseparate.

Console output is human-readable. File logs are structured (one JSON object
per line) and rotate at approximately 5 MiB, retaining five rotated files.
Tokens and authorization headers are redacted. User media contents and
request bodies are never recorded.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_LOG_FORMAT_CONSOLE = "%(asctime)s %(levelname)-8s [%(component)s] %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"

_MAX_BYTES = 5 * 1024 * 1024  # 5 MiB
_BACKUP_COUNT = 5

_token_pattern = re.compile(
    r"(?i)("
    r"authorization\s*[:=]\s*bearer\s+"
    r"|token\s*[:=]\s*"
    r"|bearer\s+"
    r")(\S+)"
)

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def redact_sensitive(message: str) -> str:
    """Replace token and authorization values with a redaction marker."""
    return _token_pattern.sub(r"\1***REDACTED***", message)


class _StructuringFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.component = getattr(record, "component", "app")
        record.request_id = request_id_var.get()
        record.msg = redact_sensitive(record.getMessage())
        record.args = None
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record, _LOG_DATE_FORMAT),
            "level": record.levelname,
            "component": getattr(record, "component", "app"),
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class _ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return super().format(record)


def setup_logging(log_level: str, log_dir: Path | None = None) -> None:
    """Configure root logger with console and optional file handlers.

    Console: human-readable, respects log_level.
    File: JSON-structured, rotates at 5 MiB, 5 backups. Only created when
    log_dir is provided and writable.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    root.handlers.clear()

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(_ConsoleFormatter(_LOG_FORMAT_CONSOLE, datefmt=_LOG_DATE_FORMAT))
    console.addFilter(_StructuringFilter())
    root.addHandler(console)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_dir / "basseparate.log",
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(_JsonFormatter())
            file_handler.addFilter(_StructuringFilter())
            root.addHandler(file_handler)
        except OSError:
            root.warning("cannot create log directory %s; file logging disabled", log_dir)

    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)
    logging.getLogger("fastapi").setLevel(level)


def get_logger(component: str) -> logging.LoggerAdapter[logging.Logger]:
    """Return a logger adapter bound to a component name."""
    logger = logging.getLogger(f"basseparate.{component}")
    return logging.LoggerAdapter(logger, {"component": component})


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def bind_request_id(request_id: str) -> None:
    request_id_var.set(request_id)
