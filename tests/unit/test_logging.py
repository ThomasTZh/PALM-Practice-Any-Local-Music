"""Logging module tests (M0.11)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from basseparate.logging import (
    bind_request_id,
    get_logger,
    new_request_id,
    redact_sensitive,
    setup_logging,
)


class TestRedact:
    def test_redacts_bearer_token(self) -> None:
        msg = "request with Authorization: Bearer secret123"
        result = redact_sensitive(msg)
        assert "secret123" not in result
        assert "REDACTED" in result

    def test_redacts_token_assignment(self) -> None:
        msg = "token=abc456def"
        result = redact_sensitive(msg)
        assert "abc456def" not in result
        assert "REDACTED" in result

    def test_preserves_normal_text(self) -> None:
        msg = "server started on port 8765"
        assert redact_sensitive(msg) == msg


class TestSetupLogging:
    def test_console_handler_created(self) -> None:
        setup_logging("INFO")
        root = logging.getLogger()
        assert len(root.handlers) >= 1
        root.handlers.clear()

    def test_file_handler_created(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        setup_logging("DEBUG", log_dir)
        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1
        log_file = log_dir / "basseparate.log"
        assert log_file.is_file()
        root.handlers.clear()

    def test_file_handler_rotation_config(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        setup_logging("DEBUG", log_dir)
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        handler = file_handlers[0]
        assert handler.maxBytes == 5 * 1024 * 1024
        assert handler.backupCount == 5
        root.handlers.clear()

    def test_unwritable_log_dir_does_not_crash(self, tmp_path: Path) -> None:
        setup_logging("INFO", tmp_path / "nonexistent" / "deep" / "path")
        root = logging.getLogger()
        assert len(root.handlers) >= 1
        root.handlers.clear()


class TestRequestID:
    def test_new_request_id_format(self) -> None:
        rid = new_request_id()
        assert len(rid) == 16
        assert all(c in "0123456789abcdef" for c in rid)

    def test_bind_and_get(self) -> None:
        rid = new_request_id()
        bind_request_id(rid)
        from basseparate.logging import request_id_var

        assert request_id_var.get() == rid


class TestGetLogger:
    def test_returns_adapter(self) -> None:
        logger = get_logger("test")
        assert isinstance(logger, logging.LoggerAdapter)
        logger.info("hello")

    def test_component_in_record(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = get_logger("mycomponent")
        with caplog.at_level(logging.INFO):
            logger.info("test message")
        assert any(getattr(r, "component", None) == "mycomponent" for r in caplog.records)


class TestJsonFormat:
    def test_json_output_structure(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        setup_logging("DEBUG", log_dir)
        logger = get_logger("testcomp")
        logger.info("structured test")

        log_file = log_dir / "basseparate.log"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) >= 1
        entry = json.loads(lines[-1])
        assert entry["level"] == "INFO"
        assert entry["component"] == "testcomp"
        assert entry["message"] == "structured test"
        assert "ts" in entry
        assert "request_id" in entry
        logging.getLogger().handlers.clear()
