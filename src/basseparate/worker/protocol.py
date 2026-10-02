"""Worker protocol: newline-delimited JSON message envelope (M0.9/M1.4).

Transport:
- Parent sends requests through the worker's stdin.
- Worker sends protocol messages through stdout.
- Worker sends logs through stderr only.

No pickle, no shared Python objects, no large inline binary arrays.

Protocol version 2 (M1.4) adds the durable-job messages: ``run``,
``progress``, ``completed``, ``failed``, ``cancel``, ``cancelled``.
Version negotiation is explicit: ``hello`` carries the worker's protocol
version and every message carries one; peers reject mismatches.
"""

from __future__ import annotations

from pathlib import PurePath
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from basseparate import WORKER_PROTOCOL_VERSION
from basseparate.domain.common import Uuid
from basseparate.domain.media_job import JobStage, JobType

PROTOCOL_VERSION = WORKER_PROTOCOL_VERSION

# Maximum size of a single protocol message, in bytes.
MAX_MESSAGE_BYTES = 1024 * 1024  # 1 MiB

# Structured error codes.
ERR_MALFORMED = "MALFORMED_MESSAGE"
ERR_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
ERR_UNKNOWN_TYPE = "UNKNOWN_MESSAGE_TYPE"
ERR_OVERSIZED = "OVERSIZED_MESSAGE"
ERR_INTERNAL = "WORKER_INTERNAL_ERROR"
ERR_NOT_IMPLEMENTED = "JOB_TYPE_NOT_IMPLEMENTED"


class WorkerProtocolError(Exception):
    """Base class for protocol-level failures."""


class MalformedMessageError(WorkerProtocolError):
    """A message that is not valid size-bounded UTF-8 JSON schema data."""


class OversizedMessageError(WorkerProtocolError):
    """A message larger than MAX_MESSAGE_BYTES."""


class HelloPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    worker: str
    protocol_version: int


class DescribePayload(BaseModel):
    model_config = ConfigDict(frozen=True)


class Capability(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    description: str


class CapabilitiesPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    worker: str
    capabilities: list[Capability] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)


class PingPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    nonce: str


class PongPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    nonce: str


class ShutdownPayload(BaseModel):
    model_config = ConfigDict(frozen=True)


class StoppedPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    exit_code: int = 0


class ErrorPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    request_id: Uuid | None = None


def _validate_absolute_path(value: str) -> str:
    if not PurePath(value).is_absolute():
        raise ValueError("path must be absolute; workers only receive validated paths")
    return value


class RunPayload(BaseModel):
    """Request to execute one media job (backend → worker)."""

    model_config = ConfigDict(frozen=True)

    job_id: Uuid
    job_type: JobType
    source_path: str = Field(min_length=1)
    staging_dir: str = Field(min_length=1)
    max_threads: int = Field(default=4, ge=1, le=32)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_path", "staging_dir")
    @classmethod
    def _check_paths(cls, v: str) -> str:
        return _validate_absolute_path(v)


class ProgressPayload(BaseModel):
    """A progress report for a running job (worker → backend)."""

    model_config = ConfigDict(frozen=True)

    job_id: Uuid
    stage: JobStage
    #: Determinate fraction in [0, 1]; None means indeterminate.
    fraction: float | None = Field(default=None, ge=0, le=1)
    detail: str | None = Field(default=None, max_length=512)


class CompletedPayload(BaseModel):
    """A job finished successfully (worker → backend)."""

    model_config = ConfigDict(frozen=True)

    job_id: Uuid
    result: dict[str, Any]


class FailedPayload(BaseModel):
    """A job failed (worker → backend)."""

    model_config = ConfigDict(frozen=True)

    job_id: Uuid
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(max_length=2000)


class CancelPayload(BaseModel):
    """Request to cancel a running job (backend → worker)."""

    model_config = ConfigDict(frozen=True)

    job_id: Uuid


class CancelledPayload(BaseModel):
    """Confirmation that a job was cancelled (worker → backend)."""

    model_config = ConfigDict(frozen=True)

    job_id: Uuid
    staging_removed: bool


class WorkerMessage(BaseModel):
    """Base envelope. Use the typed subclasses in practice."""

    model_config = ConfigDict(frozen=True)

    protocol_version: int = PROTOCOL_VERSION
    message_id: Uuid
    request_id: Uuid | None = None
    type: str
    payload: Any

    def encode(self) -> bytes:
        return self.model_dump_json().encode("utf-8")


class HelloMessage(WorkerMessage):
    type: Literal["hello"] = "hello"
    payload: HelloPayload


class DescribeMessage(WorkerMessage):
    type: Literal["describe"] = "describe"
    payload: DescribePayload


class CapabilitiesMessage(WorkerMessage):
    type: Literal["capabilities"] = "capabilities"
    payload: CapabilitiesPayload


class PingMessage(WorkerMessage):
    type: Literal["ping"] = "ping"
    payload: PingPayload


class PongMessage(WorkerMessage):
    type: Literal["pong"] = "pong"
    payload: PongPayload


class ShutdownMessage(WorkerMessage):
    type: Literal["shutdown"] = "shutdown"
    payload: ShutdownPayload


class StoppedMessage(WorkerMessage):
    type: Literal["stopped"] = "stopped"
    payload: StoppedPayload


class ErrorMessage(WorkerMessage):
    type: Literal["error"] = "error"
    payload: ErrorPayload


class RunMessage(WorkerMessage):
    type: Literal["run"] = "run"
    payload: RunPayload


class ProgressMessage(WorkerMessage):
    type: Literal["progress"] = "progress"
    payload: ProgressPayload


class CompletedMessage(WorkerMessage):
    type: Literal["completed"] = "completed"
    payload: CompletedPayload


class FailedMessage(WorkerMessage):
    type: Literal["failed"] = "failed"
    payload: FailedPayload


class CancelMessage(WorkerMessage):
    type: Literal["cancel"] = "cancel"
    payload: CancelPayload


class CancelledMessage(WorkerMessage):
    type: Literal["cancelled"] = "cancelled"
    payload: CancelledPayload


WorkerMsg = Annotated[
    HelloMessage
    | DescribeMessage
    | CapabilitiesMessage
    | PingMessage
    | PongMessage
    | ShutdownMessage
    | StoppedMessage
    | ErrorMessage
    | RunMessage
    | ProgressMessage
    | CompletedMessage
    | FailedMessage
    | CancelMessage
    | CancelledMessage,
    Field(discriminator="type"),
]

worker_message_adapter: TypeAdapter[WorkerMsg] = TypeAdapter(WorkerMsg)


def decode_message(line: bytes) -> WorkerMessage:
    """Decode one newline-terminated protocol message.

    Enforces the size limit, UTF-8, JSON, and the discriminated schema.
    Raises MalformedMessageError / OversizedMessageError on failure.
    """
    if len(line) > MAX_MESSAGE_BYTES:
        raise OversizedMessageError(f"message is {len(line)} bytes (limit {MAX_MESSAGE_BYTES})")
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MalformedMessageError(f"message is not valid UTF-8: {exc}") from exc
    text = text.strip()
    if not text:
        raise MalformedMessageError("message is empty")
    try:
        return worker_message_adapter.validate_json(text)
    except ValidationError as exc:
        raise MalformedMessageError(f"message failed schema validation: {exc}") from exc


def make_hello(worker: str) -> HelloMessage:
    return HelloMessage(
        message_id=uuid4(),
        payload=HelloPayload(worker=worker, protocol_version=PROTOCOL_VERSION),
    )


def make_describe() -> DescribeMessage:
    return DescribeMessage(message_id=uuid4(), payload=DescribePayload())


def make_capabilities(
    worker: str,
    capabilities: list[Capability] | None = None,
    models: list[str] | None = None,
) -> CapabilitiesMessage:
    return CapabilitiesMessage(
        message_id=uuid4(),
        payload=CapabilitiesPayload(
            worker=worker,
            capabilities=capabilities or [],
            models=models or [],
        ),
    )


def make_ping(nonce: str, request_id: Uuid | None = None) -> PingMessage:
    return PingMessage(
        message_id=uuid4(),
        request_id=request_id,
        payload=PingPayload(nonce=nonce),
    )


def make_pong(nonce: str, request_id: Uuid | None = None) -> PongMessage:
    return PongMessage(
        message_id=uuid4(),
        request_id=request_id,
        payload=PongPayload(nonce=nonce),
    )


def make_shutdown() -> ShutdownMessage:
    return ShutdownMessage(message_id=uuid4(), payload=ShutdownPayload())


def make_stopped(exit_code: int = 0, request_id: Uuid | None = None) -> StoppedMessage:
    return StoppedMessage(
        message_id=uuid4(),
        request_id=request_id,
        payload=StoppedPayload(exit_code=exit_code),
    )


def make_error(
    code: str,
    message: str,
    request_id: Uuid | None = None,
) -> ErrorMessage:
    return ErrorMessage(
        message_id=uuid4(),
        request_id=request_id,
        payload=ErrorPayload(code=code, message=message),
    )


def make_run(
    job_id: Uuid,
    job_type: JobType,
    source_path: str,
    staging_dir: str,
    max_threads: int = 4,
    parameters: dict[str, Any] | None = None,
) -> RunMessage:
    return RunMessage(
        message_id=uuid4(),
        payload=RunPayload(
            job_id=job_id,
            job_type=job_type,
            source_path=source_path,
            staging_dir=staging_dir,
            max_threads=max_threads,
            parameters=parameters or {},
        ),
    )


def make_progress(
    job_id: Uuid,
    stage: JobStage,
    fraction: float | None = None,
    detail: str | None = None,
) -> ProgressMessage:
    return ProgressMessage(
        message_id=uuid4(),
        payload=ProgressPayload(job_id=job_id, stage=stage, fraction=fraction, detail=detail),
    )


def make_completed(job_id: Uuid, result: dict[str, Any]) -> CompletedMessage:
    return CompletedMessage(
        message_id=uuid4(),
        payload=CompletedPayload(job_id=job_id, result=result),
    )


def make_failed(
    job_id: Uuid,
    code: str,
    message: str,
) -> FailedMessage:
    return FailedMessage(
        message_id=uuid4(),
        payload=FailedPayload(job_id=job_id, code=code, message=message),
    )


def make_cancel(job_id: Uuid) -> CancelMessage:
    return CancelMessage(message_id=uuid4(), payload=CancelPayload(job_id=job_id))


def make_cancelled(job_id: Uuid, staging_removed: bool = True) -> CancelledMessage:
    return CancelledMessage(
        message_id=uuid4(),
        payload=CancelledPayload(job_id=job_id, staging_removed=staging_removed),
    )
