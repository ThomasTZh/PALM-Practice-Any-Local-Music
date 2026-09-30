"""Worker protocol: newline-delimited JSON message envelope (M0.9).

Transport:
- Parent sends requests through the worker's stdin.
- Worker sends protocol messages through stdout.
- Worker sends logs through stderr only.

No pickle, no shared Python objects, no large inline binary arrays.
Analysis execution and cancellation messages are reserved for the
milestone that implements real jobs.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from basseparate import WORKER_PROTOCOL_VERSION
from basseparate.domain.common import Uuid

PROTOCOL_VERSION = WORKER_PROTOCOL_VERSION

# Maximum size of a single protocol message, in bytes.
MAX_MESSAGE_BYTES = 1024 * 1024  # 1 MiB

# Structured error codes.
ERR_MALFORMED = "MALFORMED_MESSAGE"
ERR_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
ERR_UNKNOWN_TYPE = "UNKNOWN_MESSAGE_TYPE"
ERR_OVERSIZED = "OVERSIZED_MESSAGE"
ERR_INTERNAL = "WORKER_INTERNAL_ERROR"


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


WorkerMsg = Annotated[
    HelloMessage
    | DescribeMessage
    | CapabilitiesMessage
    | PingMessage
    | PongMessage
    | ShutdownMessage
    | StoppedMessage
    | ErrorMessage,
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
