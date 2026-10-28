"""Piper JSON-lines host for local Vamp plugins.

Evaluation/personal-use build only. The host process and plugin directory are
explicitly configured; the application never downloads plugins or imports
native Vamp code in-process.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from basseparate.vamp.features import SUPPORTED_BPB, VampAnalysis


class VampHostUnavailable(RuntimeError):
    """The configured host or plugin directory is missing or not executable."""


class VampHostError(RuntimeError):
    """The host rejected a request or exited unexpectedly."""


@dataclass(frozen=True, slots=True)
class VampHostConfig:
    server_path: Path
    plugin_path: Path
    library_path: Path | None = None
    plugin_key: str = "qm-vamp-plugins:qm-barbeattracker"
    bpb: int = 4
    timeout_seconds: float = 300.0


def _check_config(config: VampHostConfig) -> None:
    if not config.server_path.is_file():
        raise VampHostUnavailable(f"Vamp host not found: {config.server_path}")
    if not os.access(config.server_path, os.X_OK):
        raise VampHostUnavailable(f"Vamp host is not executable: {config.server_path}")
    if not config.plugin_path.is_dir():
        raise VampHostUnavailable(f"Vamp plugin directory not found: {config.plugin_path}")
    if config.bpb not in SUPPORTED_BPB:
        raise VampHostError(f"unsupported bpb {config.bpb}")


def _send(
    process: subprocess.Popen[str], payload: dict[str, Any], deadline: float
) -> dict[str, Any]:
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise VampHostError("Vamp host timed out")
        ready, _, _ = select.select([process.stdout], [], [], remaining)
        if not ready:
            raise VampHostError("Vamp host timed out")
        line = process.stdout.readline()
        if not line:
            raise VampHostError("Vamp host closed its output")
        response = json.loads(line)
        if not isinstance(response, dict):
            raise VampHostError("Vamp host returned a non-object response")
        if "error" in response:
            message = response["error"].get("message", "unknown Vamp error")
            raise VampHostError(f"Vamp host rejected request: {message}")
        return response


def _timestamp(start: int, rate: int) -> dict[str, int]:
    return {"s": start // rate, "n": (start % rate) * 1_000_000_000 // rate}


def _read_pcm(path: Path, channels: int) -> np.ndarray:
    if channels < 1:
        raise VampHostError("PCM channel count must be positive")
    try:
        data = np.memmap(path, dtype="<f4", mode="r")
    except OSError as exc:
        raise VampHostError(f"cannot read PCM source: {path}") from exc
    if data.size == 0 or data.size % channels != 0:
        raise VampHostError("PCM source is empty or not aligned to its channel count")
    return data.reshape(-1, channels)


def analyze_pcm(
    pcm_path: Path,
    *,
    sample_rate: int,
    channels: int,
    config: VampHostConfig,
) -> VampAnalysis:
    """Run the configured bar/beat plugin over interleaved float32 PCM."""
    _check_config(config)
    frames = _read_pcm(pcm_path, channels)
    env = dict(os.environ)
    env["VAMP_PATH"] = str(config.plugin_path)
    if config.library_path is not None:
        existing = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = (
            f"{config.library_path}:{existing}" if existing else str(config.library_path)
        )
    process = subprocess.Popen(
        [str(config.server_path), "json"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    deadline = time.monotonic() + config.timeout_seconds
    try:
        loaded = _send(
            process,
            {
                "method": "load",
                "params": {"key": config.plugin_key, "inputSampleRate": sample_rate},
            },
            deadline,
        )["result"]
        configuration = loaded["defaultConfiguration"]
        parameter_values = configuration.setdefault("parameterValues", {})
        parameter_values["bpb"] = config.bpb
        configured = _send(
            process,
            {
                "method": "configure",
                "params": {"handle": loaded["handle"], "configuration": configuration},
            },
            deadline,
        )["result"]
        block_size = int(configured["framing"]["blockSize"])
        step_size = int(configured["framing"]["stepSize"])
        if block_size <= 0 or step_size <= 0:
            raise VampHostError("Vamp host returned an invalid framing")
        features: dict[str, list[dict[str, Any]]] = {}
        total_frames = len(frames)
        for start in range(0, total_frames, step_size):
            block = np.zeros(block_size, dtype=np.float32)
            available = frames[start : start + block_size]
            mono = available.mean(axis=1)
            block[: len(mono)] = mono
            response = _send(
                process,
                {
                    "method": "process",
                    "params": {
                        "handle": loaded["handle"],
                        "processInput": {
                            "inputBuffers": [block.tolist()],
                            "timestamp": _timestamp(start, sample_rate),
                        },
                    },
                },
                deadline,
            )
            for key, rows in (response.get("result", {}).get("features", {}) or {}).items():
                features.setdefault(key, []).extend(rows)
            if start + step_size >= total_frames:
                break
        finished = _send(
            process,
            {"method": "finish", "params": {"handle": loaded["handle"]}},
            deadline,
        )
        for key, rows in (finished.get("result", {}).get("features", {}) or {}).items():
            features.setdefault(key, []).extend(rows)
    except Exception:
        raise
    finally:
        process.kill()
        process.wait()

    payload: dict[str, Any] = {
        "plugin": config.plugin_key,
        "plugin_version": str(loaded.get("staticData", {}).get("version", "")),
        "sample_rate": sample_rate,
        "bpb": config.bpb,
        "features": {
            key: [
                {
                    "time_seconds": (
                        float(row.get("timestamp", {}).get("s", 0))
                        + float(row.get("timestamp", {}).get("n", 0)) / 1_000_000_000
                    ),
                    "label": row.get("label"),
                    "values": row.get("featureValues", []),
                }
                for row in rows
            ]
            for key, rows in features.items()
        },
    }
    return VampAnalysis.from_payload(payload)
