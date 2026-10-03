"""Unit tests for media worker job dispatch (M1.4, extended M1.8).

After M1.8 every protocol-v2 job type is implemented, so the
``JOB_TYPE_NOT_IMPLEMENTED`` branch is only reachable by a job type from a
future protocol version. These tests drive ``_execute_job`` directly with a
synthetic type to cover that defensive branch.
"""

from __future__ import annotations

import threading
import types
import uuid
from pathlib import Path
from typing import Any

import pytest

from basseparate.worker import ERR_NOT_IMPLEMENTED, FailedMessage
from basseparate.worker.media_worker import _execute_job


class _SyntheticJobType:
    """A job type value from a future protocol version (not in the enum)."""

    value = "bass_separation"


def _payload(tmp_path: Path, job_type: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        job_id=uuid.uuid4(),
        job_type=job_type,
        source_path=str(tmp_path / "source.pcm"),
        staging_dir=str(tmp_path / "staging"),
        max_threads=4,
        parameters={},
    )


class TestDispatchUnknownType:
    def test_synthetic_type_reports_not_implemented(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[Any] = []
        monkeypatch.setattr("basseparate.worker.media_worker._send", sent.append)

        payload = _payload(tmp_path, _SyntheticJobType())
        _execute_job(payload, threading.Event())

        assert len(sent) == 1
        message = sent[0]
        assert isinstance(message, FailedMessage)
        assert message.payload.job_id == payload.job_id
        assert message.payload.code == ERR_NOT_IMPLEMENTED
        assert "bass_separation" in message.payload.message
