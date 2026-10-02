"""Unit tests for the worker protocol envelope (M0.9)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from basseparate.domain.media_job import JobStage, JobType
from basseparate.worker import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    MalformedMessageError,
    OversizedMessageError,
    decode_message,
    make_cancel,
    make_cancelled,
    make_capabilities,
    make_completed,
    make_describe,
    make_error,
    make_failed,
    make_hello,
    make_ping,
    make_pong,
    make_progress,
    make_run,
    make_shutdown,
    make_stopped,
    worker_message_adapter,
)


class TestEnvelope:
    def test_hello_roundtrip(self) -> None:
        msg = make_hello("probe")
        decoded = decode_message(msg.encode())
        assert decoded == msg
        assert decoded.type == "hello"
        assert decoded.payload.worker == "probe"
        assert decoded.payload.protocol_version == PROTOCOL_VERSION
        assert decoded.protocol_version == PROTOCOL_VERSION
        assert decoded.request_id is None

    def test_all_message_types_roundtrip(self) -> None:
        messages = [
            make_describe(),
            make_capabilities("probe"),
            make_ping("nonce-1"),
            make_pong("nonce-1"),
            make_shutdown(),
            make_stopped(0),
            make_error("TEST_CODE", "something failed"),
        ]
        for msg in messages:
            decoded = decode_message(msg.encode())
            assert decoded == msg
            assert decoded.type == msg.type

    def test_encode_is_single_line(self) -> None:
        line = make_hello("probe").encode()
        assert b"\n" not in line

    def test_request_id_carried_on_responses(self) -> None:
        ping = make_ping("n")
        pong = make_pong("n", request_id=ping.message_id)
        assert pong.request_id == ping.message_id
        decoded = decode_message(pong.encode())
        assert decoded.request_id == ping.message_id


class TestDecode:
    def test_rejects_unknown_type(self) -> None:
        raw = {
            "protocol_version": PROTOCOL_VERSION,
            "message_id": str(uuid.uuid4()),
            "request_id": None,
            "type": "nuke",
            "payload": {},
        }
        with pytest.raises(ValidationError):
            worker_message_adapter.validate_python(raw)

    def test_rejects_missing_message_id(self) -> None:
        raw = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "ping",
            "payload": {"nonce": "x"},
        }
        with pytest.raises(ValidationError):
            worker_message_adapter.validate_python(raw)

    def test_rejects_bad_payload_shape(self) -> None:
        raw = {
            "protocol_version": PROTOCOL_VERSION,
            "message_id": str(uuid.uuid4()),
            "type": "ping",
            "payload": {"wrong_field": 1},
        }
        with pytest.raises(ValidationError):
            worker_message_adapter.validate_python(raw)

    def test_rejects_non_json(self) -> None:
        with pytest.raises(MalformedMessageError):
            decode_message(b"this is not json")

    def test_rejects_non_utf8(self) -> None:
        with pytest.raises(MalformedMessageError):
            decode_message(b"\xff\xfe\x00broken")

    def test_rejects_empty(self) -> None:
        with pytest.raises(MalformedMessageError):
            decode_message(b"   ")

    def test_rejects_oversized(self) -> None:
        with pytest.raises(OversizedMessageError):
            decode_message(b"x" * (MAX_MESSAGE_BYTES + 1))

    def test_accepts_message_at_limit(self) -> None:
        # A JSON message whose total size is exactly the limit.
        base_len = len(make_error("C", "").encode())
        msg = make_error("C", "y" * (MAX_MESSAGE_BYTES - base_len))
        encoded = msg.encode()
        assert len(encoded) == MAX_MESSAGE_BYTES
        assert decode_message(encoded).type == "error"


class TestV2JobMessages:
    def test_run_roundtrip(self) -> None:
        job_id = uuid.uuid4()
        msg = make_run(
            job_id,
            JobType.PROBE,
            "/data/uploads/a.part",
            "/data/jobs/b/staging",
            max_threads=8,
            parameters={"key": "value"},
        )
        decoded = decode_message(msg.encode())
        assert decoded == msg
        assert decoded.type == "run"
        payload = decoded.payload
        assert payload.job_id == job_id
        assert payload.job_type is JobType.PROBE
        assert payload.source_path == "/data/uploads/a.part"
        assert payload.staging_dir == "/data/jobs/b/staging"
        assert payload.max_threads == 8
        assert payload.parameters == {"key": "value"}

    def test_run_requires_absolute_paths(self) -> None:
        with pytest.raises(ValidationError):
            make_run(uuid.uuid4(), JobType.PROBE, "relative/part", "/abs/staging")
        with pytest.raises(ValidationError):
            make_run(uuid.uuid4(), JobType.PROBE, "/abs/part", "relative/staging")

    def test_progress_roundtrip(self) -> None:
        msg = make_progress(uuid.uuid4(), JobStage.DECODING, fraction=0.5, detail="12s / 24s")
        decoded = decode_message(msg.encode())
        assert decoded == msg
        assert decoded.payload.stage is JobStage.DECODING
        assert decoded.payload.fraction == 0.5
        assert decoded.payload.detail == "12s / 24s"

    def test_progress_indeterminate(self) -> None:
        msg = make_progress(uuid.uuid4(), JobStage.INSPECTING)
        decoded = decode_message(msg.encode())
        assert decoded.payload.fraction is None
        assert decoded.payload.detail is None

    def test_completed_roundtrip(self) -> None:
        job_id = uuid.uuid4()
        result = {"format_name": "wav", "audio_streams": []}
        msg = make_completed(job_id, result)
        decoded = decode_message(msg.encode())
        assert decoded == msg
        assert decoded.payload.result == result

    def test_failed_roundtrip(self) -> None:
        msg = make_failed(uuid.uuid4(), "JOB_TYPE_NOT_IMPLEMENTED", "deferred")
        decoded = decode_message(msg.encode())
        assert decoded == msg
        assert decoded.payload.code == "JOB_TYPE_NOT_IMPLEMENTED"
        assert decoded.payload.message == "deferred"

    def test_cancel_roundtrip(self) -> None:
        job_id = uuid.uuid4()
        msg = make_cancel(job_id)
        decoded = decode_message(msg.encode())
        assert decoded == msg
        assert decoded.payload.job_id == job_id

    def test_cancelled_roundtrip(self) -> None:
        job_id = uuid.uuid4()
        msg = make_cancelled(job_id, staging_removed=True)
        decoded = decode_message(msg.encode())
        assert decoded == msg
        assert decoded.payload.staging_removed is True

    def test_all_v2_types_roundtrip(self) -> None:
        job_id = uuid.uuid4()
        messages = [
            make_run(job_id, JobType.WAVEFORM, "/a", "/b"),
            make_progress(job_id, JobStage.READY, fraction=1.0),
            make_completed(job_id, {}),
            make_failed(job_id, "E", "m"),
            make_cancel(job_id),
            make_cancelled(job_id),
        ]
        for msg in messages:
            assert decode_message(msg.encode()) == msg
