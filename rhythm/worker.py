"""Rhythm worker: Beat This! framewise activation inference (M3.4).

Runs in the isolated rhythm environment (``rhythm/.venv/bin/python``) and
speaks the newline-delimited JSON protocol v2 on stdin/stdout. It is
launched with an explicit local checkpoint path and prepared 22,050 Hz
stereo PCM; it never downloads models and never touches the database.

The main thread handles ``describe``/``ping``/``cancel``/``shutdown``;
one job thread runs inference and writes only ``beat.npy`` and
``downbeat.npy`` into its assigned staging directory. The backend
validates and publishes the artifact atomically, so a cancelled or failed
run never becomes a complete activation artifact.

Only the standard library is imported at startup; torch/numpy are
imported inside the job thread.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 2
WORKER_NAME = "rhythm"
MAX_MESSAGE_BYTES = 1024 * 1024
_JOB_JOIN_SECONDS = 10.0

ACTIVATION_SCHEMA_VERSION = 1
BEAT_FILE = "beat.npy"
DOWNBEAT_FILE = "downbeat.npy"
MODEL_SAMPLE_RATE = 22_050
FRAME_HOP = 441
FRAME_RATE = 50.0

_CAPABILITIES = [
    {
        "id": "rhythm.activation.v1",
        "description": (
            "Beat This! framewise beat and downbeat activations (raw logits). "
            "Input: prepared 22,050 Hz stereo f32le PCM. Output: beat.npy and "
            "downbeat.npy (float32, one value per model frame) plus run metrics. "
            "The backend validates and publishes the artifact."
        ),
        "module_version": "1.0.0",
        "input_roles": ["original_mix", "drum_stem"],
        "models": ["beat_this_final0", "beat_this_small0"],
        "devices": ["cpu", "cuda"],
        "expected_memory_class": (
            "final0: about 0.7 GiB host RSS on CPU; about 1-2 GiB device memory "
            "when qualified on a GPU; small0 is smaller"
        ),
        "cancellation": (
            "checked before model load and after inference; a cancelled job "
            "removes its staged arrays and never completes"
        ),
        "determinism": (
            "CPU inference is deterministic for the pinned package; GPU results "
            "may vary with cuDNN kernels unless deterministic algorithms are "
            "forced"
        ),
        "output_schema": {
            "activation_schema_version": ACTIVATION_SCHEMA_VERSION,
            "files": [BEAT_FILE, DOWNBEAT_FILE],
            "dtype": "float32",
            "frame_rate": FRAME_RATE,
            "frame_hop": FRAME_HOP,
            "model_sample_rate": MODEL_SAMPLE_RATE,
            "semantics": "raw framewise logits; uncalibrated model scores",
        },
        "confidence": (
            "raw logits are stored as uncalibrated model scores; later pulse "
            "confidence must use kind=heuristic and calibrated=false until "
            "independent calibration evidence exists"
        ),
        "license": (
            "Beat This! code and published weights are MIT licensed; see "
            "src/basseparate/models/rhythm_registry.py for provenance and notices"
        ),
    }
]
_MODELS = ["beat_this_final0", "beat_this_small0"]


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


def _progress(
    job_id: str, stage: str, detail: str | None = None, fraction: float | None = None
) -> None:
    _send(
        "progress",
        {"job_id": job_id, "stage": stage, "fraction": fraction, "detail": detail},
    )


class _ActiveJob:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.job_id: str | None = None
        self.thread: threading.Thread | None = None
        self.cancel_event = threading.Event()

    def begin(self) -> threading.Event:
        with self.lock:
            self.cancel_event = threading.Event()
            return self.cancel_event

    def request_cancel(self) -> None:
        with self.lock:
            self.cancel_event.set()

    @property
    def running(self) -> bool:
        with self.lock:
            return self.thread is not None and self.thread.is_alive()


_active = _ActiveJob()


def _cleanup(staging: Path) -> bool:
    removed = False
    for name in (BEAT_FILE, DOWNBEAT_FILE):
        path = staging / name
        with contextlib.suppress(OSError):
            path.unlink()
            removed = True
    return removed


def _failure(job_id: str, code: str, message: str, staging: Path) -> None:
    _cleanup(staging)
    _send(
        "failed",
        {"job_id": job_id, "code": code, "message": message[:2000]},
    )


def _run_activation(payload: dict[str, Any]) -> None:
    job_id = str(payload["job_id"])
    parameters = payload.get("parameters") or {}
    staging = Path(str(payload["staging_dir"]))
    source = Path(str(payload["source_path"]))
    checkpoint = Path(str(parameters.get("checkpoint_path", "")))
    device = str(parameters.get("device") or "cpu")
    float16 = bool(parameters.get("float16", False))
    threads = int(payload.get("max_threads") or 4)
    cancel_event = _active.begin()

    try:
        if not source.is_file():
            _failure(job_id, "RHYTHM_INPUT_MISSING", f"prepared input missing: {source}", staging)
            return
        if not checkpoint.is_file():
            _failure(
                job_id,
                "MODEL_NOT_INSTALLED",
                f"checkpoint not installed: {checkpoint}",
                staging,
            )
            return
        _progress(job_id, "preparing_input", "reading prepared 22,050 Hz PCM")
        import numpy as np

        samples = np.fromfile(source, dtype="<f4")
        if samples.size == 0 or samples.size % 2 != 0:
            _failure(
                job_id,
                "RHYTHM_INPUT_INVALID",
                "prepared input must be a non-empty stereo f32le file",
                staging,
            )
            return
        signal = samples.reshape(-1, 2)

        # Offline guarantees are set before torch or beat_this is imported.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        _progress(job_id, "loading_model", f"loading {parameters.get('model_id')} on {device}")
        import torch
        from beat_this.inference import Audio2Frames

        torch.set_num_threads(max(1, min(threads, 32)))
        load_started = time.perf_counter()
        model = Audio2Frames(checkpoint_path=str(checkpoint), device=device, float16=float16)
        load_seconds = time.perf_counter() - load_started
        if cancel_event.is_set():
            removed = _cleanup(staging)
            _send("cancelled", {"job_id": job_id, "staging_removed": removed})
            return

        _progress(job_id, "running_inference", "running Beat This! inference")
        inference_started = time.perf_counter()
        beat, downbeat = model(signal, MODEL_SAMPLE_RATE)
        inference_seconds = time.perf_counter() - inference_started

        if cancel_event.is_set():
            removed = _cleanup(staging)
            _send("cancelled", {"job_id": job_id, "staging_removed": removed})
            return

        _progress(job_id, "writing_activations", "writing beat/downbeat arrays")
        staging.mkdir(parents=True, exist_ok=True)
        beat_np = beat.detach().to("cpu", torch.float32).numpy()
        downbeat_np = downbeat.detach().to("cpu", torch.float32).numpy()
        np.save(staging / BEAT_FILE, beat_np)
        np.save(staging / DOWNBEAT_FILE, downbeat_np)

        _progress(job_id, "validating_artifact", "checking shapes and finite values")
        frame_count = int(beat_np.size)
        valid = (
            frame_count > 0
            and int(downbeat_np.size) == frame_count
            and bool(np.isfinite(beat_np).all())
            and bool(np.isfinite(downbeat_np).all())
        )
        if not valid:
            _failure(
                job_id,
                "ACTIVATION_INVALID",
                "activation arrays are empty, mismatched, or non-finite",
                staging,
            )
            return

        try:
            from importlib.metadata import version as _version

            beat_this_version = _version("beat-this")
        except Exception:
            beat_this_version = "unknown"
        import resource

        peak_host_rss_kib = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        peak_device_memory_bytes: int | None = None
        if str(device).startswith("cuda"):
            with contextlib.suppress(Exception):
                peak_device_memory_bytes = int(torch.cuda.max_memory_allocated())

        _send(
            "completed",
            {
                "job_id": job_id,
                "result": {
                    "status": "complete",
                    "beat_file": BEAT_FILE,
                    "downbeat_file": DOWNBEAT_FILE,
                    "frame_count": frame_count,
                    "frames_per_second": FRAME_RATE,
                    "model_sample_rate": MODEL_SAMPLE_RATE,
                    "frame_hop": FRAME_HOP,
                    "dtype": "float32",
                    "device": str(device),
                    "float16": float16,
                    "torch_version": torch.__version__,
                    "beat_this_version": beat_this_version,
                    "load_seconds": load_seconds,
                    "inference_seconds": inference_seconds,
                    "beat_min": float(beat_np.min()),
                    "beat_max": float(beat_np.max()),
                    "downbeat_min": float(downbeat_np.min()),
                    "downbeat_max": float(downbeat_np.max()),
                    "peak_host_rss_kib": peak_host_rss_kib,
                    "peak_device_memory_bytes": peak_device_memory_bytes,
                    "deterministic": str(device) == "cpu",
                },
            },
        )
        _log(f"job {job_id} completed: {frame_count} frames on {device}")
    except Exception as exc:  # noqa: BLE001 - job boundary: report, never crash the worker
        _log(f"job {job_id} failed: {exc!r}")
        _failure(job_id, "RHYTHM_INFERENCE_FAILED", str(exc), staging)


def _handle_run(payload: dict[str, Any]) -> None:
    if _active.running:
        _send(
            "error",
            {
                "code": "WORKER_BUSY",
                "message": "a job is already running; rhythm jobs are serialized",
                "request_id": None,
            },
        )
        return
    if payload.get("job_type") != "rhythm_activation":
        _send(
            "failed",
            {
                "job_id": str(payload.get("job_id", "")),
                "code": "JOB_TYPE_NOT_IMPLEMENTED",
                "message": (
                    "the rhythm worker only implements 'rhythm_activation', got "
                    f"{payload.get('job_type')!r}"
                ),
            },
        )
        return
    job_id = str(payload["job_id"])
    thread = threading.Thread(
        target=_run_activation,
        args=(payload,),
        name=f"rhythm-job-{job_id[:8]}",
        daemon=True,
    )
    with _active.lock:
        _active.job_id = job_id
        _active.thread = thread
    thread.start()
    _log(f"job {job_id} (rhythm_activation) started")


def _handle(message: dict[str, Any]) -> int | None:
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
            {"worker": WORKER_NAME, "capabilities": _CAPABILITIES, "models": _MODELS},
        )
        return None
    if message_type == "run":
        _handle_run(payload)
        return None
    if message_type == "cancel":
        _log(f"cancel requested for job {payload.get('job_id')}")
        _active.request_cancel()
        return None
    if message_type == "shutdown":
        _active.request_cancel()
        with _active.lock:
            thread = _active.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=_JOB_JOIN_SECONDS)
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


def run() -> int:
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
                        f"protocol version {message.get('protocol_version')} is not supported"
                    ),
                    "request_id": None,
                },
            )
            continue
        exit_code = _handle(message)
        if exit_code is not None:
            return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="basseparate-rhythm-worker")
    parser.parse_args(argv)
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 - last-resort structured failure
        _log(f"unexpected worker exception: {exc!r}")
        with contextlib.suppress(Exception):
            _send(
                "error",
                {"code": "WORKER_INTERNAL_ERROR", "message": str(exc), "request_id": None},
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
