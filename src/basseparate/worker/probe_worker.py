"""Built-in probe worker (M0.9).

A model-free diagnostic worker used to validate the subprocess
boundary. It emits ``hello``, reports a diagnostic capability,
answers ``ping``, validates message versions, rejects unknown
message types, logs only to stderr, and stops on shutdown or
stdin EOF.

It must never be listed as an available music-analysis module in
the user interface.
"""

from __future__ import annotations

import contextlib
import sys

from basseparate.worker.protocol import (
    ERR_INTERNAL,
    ERR_MALFORMED,
    ERR_OVERSIZED,
    ERR_UNKNOWN_TYPE,
    ERR_VERSION_MISMATCH,
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    Capability,
    DescribeMessage,
    MalformedMessageError,
    PingMessage,
    ShutdownMessage,
    WorkerMessage,
    decode_message,
    make_capabilities,
    make_error,
    make_hello,
    make_pong,
    make_stopped,
)

WORKER_NAME = "probe"

_DIAGNOSTIC_CAPABILITY = Capability(
    id="diagnostic.ping",
    description="Model-free responsiveness probe; validates the process boundary only.",
)


def _log(message: str) -> None:
    # Logs go to stderr only; stdout carries protocol messages exclusively.
    print(f"[probe-worker] {message}", file=sys.stderr, flush=True)


def _send(message: WorkerMessage) -> None:
    sys.stdout.buffer.write(message.encode() + b"\n")
    sys.stdout.buffer.flush()


def _handle(message: WorkerMessage) -> int | None:
    """Handle one validated, version-matched message.

    Returns a process exit code when the worker should stop,
    or None to keep running.
    """
    if isinstance(message, DescribeMessage):
        _send(
            make_capabilities(
                WORKER_NAME,
                capabilities=[_DIAGNOSTIC_CAPABILITY],
                models=[],
            )
        )
        return None
    if isinstance(message, PingMessage):
        _send(make_pong(message.payload.nonce, request_id=message.message_id))
        return None
    if isinstance(message, ShutdownMessage):
        _send(make_stopped(0, request_id=message.message_id))
        _log("shutdown requested; stopping")
        return 0
    _send(
        make_error(
            ERR_UNKNOWN_TYPE,
            f"unknown message type {message.type!r}",
            request_id=message.message_id,
        )
    )
    return None


def run() -> int:
    try:
        _send(make_hello(WORKER_NAME))
        _log(f"hello emitted (protocol v{PROTOCOL_VERSION}); awaiting stdin")
        stdin = sys.stdin.buffer
        while True:
            line = stdin.readline()
            if not line:
                _log("stdin EOF; stopping")
                return 0
            line = line.rstrip(b"\r\n")
            if not line:
                continue
            if len(line) > MAX_MESSAGE_BYTES:
                _log(f"oversized message ({len(line)} bytes); rejecting")
                _send(make_error(ERR_OVERSIZED, f"message exceeds {MAX_MESSAGE_BYTES} bytes"))
                continue
            try:
                message = decode_message(line)
            except MalformedMessageError as exc:
                _log(f"malformed message: {exc}")
                _send(make_error(ERR_MALFORMED, str(exc)))
                continue
            if message.protocol_version != PROTOCOL_VERSION:
                _log(f"version mismatch: got {message.protocol_version}, want {PROTOCOL_VERSION}")
                _send(
                    make_error(
                        ERR_VERSION_MISMATCH,
                        f"protocol version {message.protocol_version} is not supported",
                        request_id=message.message_id,
                    )
                )
                continue
            exit_code = _handle(message)
            if exit_code is not None:
                return exit_code
    except Exception as exc:  # noqa: BLE001 - last-resort guard: log, structured error, exit 1
        _log(f"unexpected worker exception: {exc!r}")
        with contextlib.suppress(Exception):
            _send(make_error(ERR_INTERNAL, f"worker failed: {exc!r}"))
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
