"""Analysis worker: protocol-v2 adapter around the bounded Demucs runner.

Runs in the isolated analysis environment (``analysis/.venv/bin/python``),
never in the application environment (spec §4.1.7). It speaks the M1
newline-delimited JSON protocol (version 2) on stdin/stdout and executes
``analysis/separate.py`` for each separation job:

- ``hello`` on startup, ``capabilities`` on ``describe`` (declares the
  ``analysis.separation.v1`` parameter/result schema).
- ``run`` spawns the separator with the explicit interpreter, relays its
  JSON-lines progress as protocol ``progress`` messages (stage
  ``separating``), and streams the separator's stderr to its own stderr.
- ``cancel`` writes the separator's cancel flag file; the separator exits
  with its cancelled status and the worker reports ``cancelled``.
- Completion reads ``run-record.json`` and reports the attempt directory,
  stem labels, and the record through ``completed``; failures report the
  record's error (or the last stderr lines) through ``failed``.

Only the standard library is used here: no torch/numpy import at startup,
so ``--describe`` and protocol tests run in any Python 3.11 environment.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 2
WORKER_NAME = "analysis"
MAX_MESSAGE_BYTES = 1024 * 1024

EXIT_OK = 0
EXIT_CANCELLED = 2
EXIT_MEMORY = 3

DEFAULT_SEGMENT_SECONDS = 7.5
DEFAULT_WINDOW_SECONDS = 120.0
DEFAULT_OVERLAP_SECONDS = 8.0

_CAPABILITIES = [
    {
        "id": "analysis.separation.v1",
        "description": (
            "Bounded windowed Demucs separation (schema v1): parameters "
            "{input_path, profile_path, out_dir, device, seed, "
            "segment_seconds, window_seconds, overlap_seconds, bundle_dir}; "
            "result {status, attempt_dir, record_path, stem_labels, frames, "
            "device, elapsed_seconds, record}"
        ),
    }
]
_MODELS = ["htdemucs_ft"]
_MESSAGE_JOIN_SECONDS = 10.0


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _send(message_type: str, payload: dict[str, Any]) -> None:
    message = {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": str(uuid.uuid4()),
        "request_id": None,
        "type": message_type,
        "payload": payload,
    }
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _ActiveJob:
    """State of the single in-flight job (the manager serializes jobs)."""

    def __init__(self) -> None:
        self.job_id: str | None = None
        self.thread: threading.Thread | None = None
        self.process: subprocess.Popen[str] | None = None
        self.cancel_path: Path | None = None
        self.cancel_requested = False
        self.lock = threading.Lock()

    def request_cancel(self) -> None:
        with self.lock:
            self.cancel_requested = True
            path = self.cancel_path
            process = self.process
        if path is not None:
            with contextlib.suppress(OSError):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("cancel\n", encoding="utf-8")
        if process is not None and process.poll() is not None:
            return


_active = _ActiveJob()


def _number(parameters: dict[str, Any], name: str, default: float | None) -> float:
    value = parameters.get(name, default)
    if value is None:
        raise ValueError(f"missing parameter {name!r}")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"parameter {name!r} must be a number") from exc


def _path(parameters: dict[str, Any], name: str) -> Path:
    value = parameters.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing parameter {name!r}")
    return Path(value)


def _run_separation(payload: dict[str, Any], args: argparse.Namespace) -> None:
    job_id = str(payload["job_id"])
    parameters = payload.get("parameters") or {}
    result: dict[str, Any] | None = None
    failure: tuple[str, str] | None = None
    cancelled = False
    stderr_tail: list[str] = []

    try:
        input_path = _path(parameters, "input_path")
        profile_path = _path(parameters, "profile_path")
        out_dir = _path(parameters, "out_dir")
        bundle_dir = _path(parameters, "bundle_dir")
        device = str(parameters.get("device") or "cpu")
        seed = int(parameters.get("seed", 0))
        segment = _number(parameters, "segment_seconds", DEFAULT_SEGMENT_SECONDS)
        window = _number(parameters, "window_seconds", DEFAULT_WINDOW_SECONDS)
        overlap = _number(parameters, "overlap_seconds", DEFAULT_OVERLAP_SECONDS)
        for path, what in (
            (input_path, "prepared input"),
            (profile_path, "normalization profile"),
            (bundle_dir, "model bundle"),
        ):
            if not path.exists():
                raise ValueError(f"{what} does not exist: {path}")
        out_dir.mkdir(parents=True, exist_ok=True)
        cancel_path = out_dir / "cancel.flag"
        with _active.lock:
            _active.cancel_path = cancel_path
            cancel_already_requested = _active.cancel_requested
        if cancel_already_requested:
            cancel_path.write_text("cancel\n", encoding="utf-8")
        command = [
            args.python,
            str(args.separate_script),
            "--input",
            str(input_path),
            "--profile",
            str(profile_path),
            "--bundle-dir",
            str(bundle_dir),
            "--device",
            device,
            "--out",
            str(out_dir),
            "--seed",
            str(seed),
            "--cancel",
            str(cancel_path),
            "--segment",
            str(segment),
            "--window-seconds",
            str(window),
            "--overlap-seconds",
            str(overlap),
        ]
        with _active.lock:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            _active.process = process

        def _forward_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                text = line.rstrip()
                if text:
                    stderr_tail.append(text)
                    del stderr_tail[:-20]
                    _log(f"separator: {text}")

        stderr_thread = threading.Thread(
            target=_forward_stderr, name=f"separator-stderr-{job_id[:8]}", daemon=True
        )
        stderr_thread.start()

        assert process.stdout is not None
        for line in process.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                _log(f"separator: {text}")
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "segment":
                fraction = event.get("fraction")
                detail = (
                    f"window {event.get('window')}/{event.get('window_count')} · "
                    f"segment {event.get('completed_units')}/{event.get('total_units')}"
                )
                _send(
                    "progress",
                    {
                        "job_id": job_id,
                        "stage": "separating",
                        "fraction": fraction if isinstance(fraction, (int, float)) else None,
                        "detail": _truncate(detail, 512),
                    },
                )
            elif kind == "window":
                total_frames = event.get("total_frames") or 0
                frames = event.get("frames") or 0
                fraction = (frames / total_frames) if total_frames else None
                _send(
                    "progress",
                    {
                        "job_id": job_id,
                        "stage": "separating",
                        "fraction": fraction,
                        "detail": _truncate(
                            f"window {event.get('window')}/{event.get('window_count')}", 512
                        ),
                    },
                )

        exit_code = process.wait()
        stderr_thread.join(timeout=_MESSAGE_JOIN_SECONDS)
        record_path = out_dir / "run-record.json"
        record: dict[str, Any] = {}
        if record_path.is_file():
            with contextlib.suppress(OSError, json.JSONDecodeError):
                loaded = json.loads(record_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    record = loaded
        status = record.get("status")
        if exit_code == EXIT_CANCELLED or status == "cancelled":
            cancelled = True
        elif exit_code == EXIT_OK and status in ("complete", "complete_silence"):
            result = {
                "status": status,
                "attempt_dir": record.get("outputs"),
                "record_path": str(record_path),
                "stem_labels": list(record.get("labels") or []),
                "frames": record.get("frames"),
                "device": record.get("device"),
                "elapsed_seconds": (record.get("timings") or {}).get("seconds"),
                "record": record,
            }
        else:
            error = record.get("error")
            if not isinstance(error, str) or not error:
                error = (
                    stderr_tail[-1]
                    if stderr_tail
                    else f"separator exited with code {exit_code}"
                )
            code = "SEPARATION_OUT_OF_MEMORY" if exit_code == EXIT_MEMORY else "SEPARATION_FAILED"
            failure = (code, _truncate(error, 2000))
    except Exception as exc:  # noqa: BLE001 - report any failure as a job failure
        failure = ("SEPARATION_FAILED", _truncate(f"analysis worker failed: {exc!r}", 2000))
    finally:
        with _active.lock:
            _active.process = None
            _active.cancel_path = None
            _active.cancel_requested = False

    if cancelled:
        _send("cancelled", {"job_id": job_id, "staging_removed": True})
    elif failure is not None:
        _send("failed", {"job_id": job_id, "code": failure[0], "message": failure[1]})
    else:
        _send("completed", {"job_id": job_id, "result": result or {}})
    _log(f"job {job_id} finished")


def _handle_run(payload: dict[str, Any], args: argparse.Namespace) -> None:
    if _active.thread is not None and _active.thread.is_alive():
        _send(
            "error",
            {
                "code": "WORKER_BUSY",
                "message": "a job is already running; the manager must serialize jobs",
                "request_id": None,
            },
        )
        return
    if payload.get("job_type") != "separation":
        _send(
            "failed",
            {
                "job_id": str(payload.get("job_id", "")),
                "code": "JOB_TYPE_NOT_IMPLEMENTED",
                "message": f"the analysis worker does not implement {payload.get('job_type')!r}",
            },
        )
        return
    _active.job_id = str(payload["job_id"])
    _active.thread = threading.Thread(
        target=_run_separation,
        args=(payload, args),
        name=f"analysis-job-{_active.job_id[:8]}",
        daemon=True,
    )
    _active.thread.start()
    _log(f"job {_active.job_id} (separation) started")


def _handle(message: dict[str, Any], args: argparse.Namespace) -> int | None:
    message_type = message.get("type")
    payload = message.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    if message_type == "ping":
        _send("pong", {"nonce": payload.get("nonce", "")})
        return None
    if message_type == "describe":
        _send(
            "capabilities",
            {
                "worker": WORKER_NAME,
                "capabilities": _CAPABILITIES,
                "models": _MODELS,
            },
        )
        return None
    if message_type == "run":
        _handle_run(payload, args)
        return None
    if message_type == "cancel":
        _log(f"cancel requested for job {payload.get('job_id')}")
        _active.request_cancel()
        return None
    if message_type == "shutdown":
        _active.request_cancel()
        thread = _active.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=_MESSAGE_JOIN_SECONDS)
        _send("stopped", {"exit_code": 0})
        _log("shutdown requested; stopping")
        return 0
    _send(
        "error",
        {
            "code": "UNKNOWN_MESSAGE_TYPE",
            "message": f"unknown message type {message_type!r}",
            "request_id": None,
        },
    )
    return None


def run(args: argparse.Namespace) -> int:
    _send("hello", {"worker": WORKER_NAME, "protocol_version": PROTOCOL_VERSION})
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
            _send(
                "error",
                {
                    "code": "OVERSIZED_MESSAGE",
                    "message": f"message exceeds {MAX_MESSAGE_BYTES} bytes",
                    "request_id": None,
                },
            )
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _send(
                "error",
                {"code": "MALFORMED_MESSAGE", "message": str(exc), "request_id": None},
            )
            continue
        if not isinstance(message, dict):
            _send(
                "error",
                {
                    "code": "MALFORMED_MESSAGE",
                    "message": "message is not an object",
                    "request_id": None,
                },
            )
            continue
        if message.get("protocol_version") != PROTOCOL_VERSION:
            _send(
                "error",
                {
                    "code": "PROTOCOL_VERSION_MISMATCH",
                    "message": (
                        f"protocol version {message.get('protocol_version')} is not "
                        f"supported"
                    ),
                    "request_id": None,
                },
            )
            continue
        exit_code = _handle(message, args)
        if exit_code is not None:
            return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="basseparate-analysis-worker")
    parser.add_argument(
        "--separate-script",
        type=Path,
        default=Path(__file__).with_name("separate.py"),
        help="path to the bounded separation runner (default: analysis/separate.py)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="interpreter for the separator (default: this interpreter)",
    )
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001 - last-resort guard: structured error, exit 1
        _log(f"unexpected worker exception: {exc!r}")
        with contextlib.suppress(Exception):
            _send(
                "error",
                {"code": "WORKER_INTERNAL_ERROR", "message": str(exc), "request_id": None},
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
