#!/usr/bin/env python3
"""Offline qualification for one installed Beat This! checkpoint (M3.2 §4.5).

Runs in the isolated rhythm environment with an explicit local checkpoint
path, so no network access or implicit download can occur:

    rhythm/.venv/bin/python rhythm/qualify.py \
        --model-id beat_this_final0 --checkpoint <path> --device cpu

The script records finite outputs, frame geometry, determinism, runtime,
and memory in a JSON report. Exit code 0 means the model/device pair is
qualified; any failure exits non-zero without claiming success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import sys
import time
from pathlib import Path
from typing import Any

# Offline guarantees must be set before torch or beat_this is imported.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

MODEL_SAMPLE_RATE = 22_050
FRAME_HOP = 441
EXPECTED_FRAME_RATE = 50.0
DEFAULT_THREADS = 4


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _fixture(sample_rate: int = 44_100, seconds: float = 5.0) -> Any:
    import numpy as np

    frames = int(round(sample_rate * seconds))
    times = np.arange(frames, dtype=np.float64) / sample_rate
    signal = 0.05 * np.sin(2.0 * np.pi * 220.0 * times)
    # A click every 0.5 s (120 bpm) plus a stronger click every 2 s.
    for beat in range(int(seconds / 0.5)):
        start = int(round(beat * 0.5 * sample_rate))
        length = min(int(0.02 * sample_rate), frames - start)
        accent = 0.8 if beat % 4 == 0 else 0.4
        envelope = np.exp(-np.arange(length) / (0.004 * sample_rate))
        signal[start : start + length] += accent * envelope
    return signal.astype(np.float32)


def _model_version() -> str:
    try:
        from importlib.metadata import version

        return version("beat-this")
    except Exception:
        return "unknown"


def _tensor_summary(value: Any) -> dict[str, Any]:
    import torch

    return {
        "shape": list(value.shape),
        "dtype": str(value.dtype),
        "finite": bool(torch.isfinite(value).all().item()),
        "min": float(value.min().item()) if value.numel() else None,
        "max": float(value.max().item()) if value.numel() else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    parser.add_argument("--float16", action="store_true")
    parser.add_argument("--out", type=Path, default=None, help="JSON report path")
    args = parser.parse_args(argv)

    checkpoint = args.checkpoint.expanduser().resolve()
    if not checkpoint.is_file():
        print(f"error: checkpoint not found: {checkpoint}", file=sys.stderr)
        return 1

    import torch
    from beat_this.inference import Audio2Frames

    torch.set_num_threads(max(1, args.threads))
    device = torch.device(args.device)
    cuda_available = bool(torch.cuda.is_available())
    if device.type == "cuda" and not cuda_available:
        print("error: cuda requested but torch.cuda.is_available() is false", file=sys.stderr)
        return 1

    signal = _fixture()
    started = time.perf_counter()
    load_started = time.perf_counter()
    frames_model = Audio2Frames(
        checkpoint_path=str(checkpoint), device=str(device), float16=args.float16
    )
    load_seconds = time.perf_counter() - load_started

    first_started = time.perf_counter()
    beat_a, downbeat_a = frames_model(signal, 44_100)
    first_seconds = time.perf_counter() - first_started

    second_started = time.perf_counter()
    beat_b, downbeat_b = frames_model(signal, 44_100)
    second_seconds = time.perf_counter() - second_started
    total_seconds = time.perf_counter() - started

    deterministic = bool(torch.equal(beat_a, beat_b) and torch.equal(downbeat_a, downbeat_b))
    frame_count = int(beat_a.numel())
    duration = len(signal) / 44_100
    observed_rate = frame_count / duration if duration else 0.0
    geometry_ok = (
        beat_a.numel() == downbeat_a.numel()
        and frame_count > 0
        and abs(observed_rate - EXPECTED_FRAME_RATE) <= 1.0
    )
    finite_ok = bool(
        torch.isfinite(beat_a).all().item() and torch.isfinite(downbeat_a).all().item()
    )

    report: dict[str, Any] = {
        "status": "pass" if (deterministic and geometry_ok and finite_ok) else "fail",
        "model_id": args.model_id,
        "checkpoint": {
            "path": str(checkpoint),
            "sha256": _sha256(checkpoint),
            "size_bytes": checkpoint.stat().st_size,
        },
        "package": {"beat-this": _model_version()},
        "torch": torch.__version__,
        "device": str(device),
        "torch_cuda_available": cuda_available,
        "threads": torch.get_num_threads(),
        "float16": args.float16,
        "network": "HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 before torch import",
        "input": {
            "sample_rate": 44_100,
            "duration_seconds": duration,
            "samples": int(signal.size),
            "fixture": "220 Hz tone + 120 bpm clicks, deterministic",
        },
        "geometry": {
            "model_sample_rate": MODEL_SAMPLE_RATE,
            "frame_hop": FRAME_HOP,
            "frame_count": frame_count,
            "frames_per_second": observed_rate,
            "expected_frames_per_second": EXPECTED_FRAME_RATE,
            "ok": geometry_ok,
        },
        "outputs": {
            "beat": _tensor_summary(beat_a),
            "downbeat": _tensor_summary(downbeat_a),
        },
        "deterministic": deterministic,
        "finite_outputs": finite_ok,
        "timings": {
            "model_load_seconds": load_seconds,
            "first_inference_seconds": first_seconds,
            "second_inference_seconds": second_seconds,
            "total_seconds": total_seconds,
            "real_time_factor": total_seconds / duration if duration else None,
        },
        "memory": {
            "peak_host_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
    }

    out = args.out or checkpoint.parent / f"qualification-{args.device}.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "model_id",
                    "device",
                    "geometry",
                    "deterministic",
                    "finite_outputs",
                    "timings",
                )
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(f"report: {out}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
