#!/usr/bin/env python3
"""Run MSST SCNet/RoFormer separation and write project-rate stems.

This worker mirrors ``analysis/separate_track.py`` for the MSST engines. It runs
only in ``analysis-models/.venv`` and is launched by the application as a child
process; the application environment never imports torch or msst.

Contract:
* read interleaved float32 PCM at the project rate and convert it to
  channels-first float32;
* construct ``msst.inference.Separator`` for the requested registry model,
  forcing CPU when CUDA is unavailable;
* validate ``separator.instruments`` against ``analysis/models.json``;
* resample every output stem back to the project rate, then trim/pad each stem
  to the source frame count;
* write interleaved f32 stems atomically and write ``meta.json`` last;
* emit JSONL progress on stdout; library chatter goes to stderr;
* cancellation is by killing this child; a SIGTERM handler removes the
  staging directory so no partial final stem set appears;
* failures exit non-zero with the reason on stderr (the parent keeps a tail).

Progress is deliberately stage-based when MSST does not expose callbacks:
loading, separating, resampling, writing. A tqdm line, if MSST emits one, is
mirrored as a progress event by the parent's stderr tail rather than parsed
here because the library owns that stream.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import resource
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from basseparate.model_registry import (  # noqa: E402
    ModelEntry,
    ModelRegistryError,
    load_registry,
    model_directory,
)

MSST_MODEL_TYPES = {
    "scnet-xl-ihf": "scnet",
    "bs-roformer-sw": "bs_roformer",
}
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CANCELLED = 2


class MsstError(RuntimeError):
    """A clear, user-facing MSST worker failure."""


class Terminated(Exception):
    """SIGTERM/SIGINT arrived while the model was running."""


def emit(event: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(event, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def resolve_device(requested: str, *, cuda_available: bool) -> str:
    if requested == "auto":
        return "cuda" if cuda_available else "cpu"
    if requested == "cuda":
        if not cuda_available:
            raise MsstError("cuda was requested but torch reports CUDA unavailable")
        return "cuda"
    if requested == "cpu":
        return "cpu"
    raise MsstError(f"unknown device {requested!r}; choose auto, cpu or cuda")


def cuda_available() -> bool:
    try:
        import torch
    except Exception:  # noqa: BLE001 - main environment may not have torch
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def resample_audio(samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Resample ``(channels, frames)`` to the project rate.

    The production environment uses librosa's soxr-backed resampler. The numpy
    band-limited-enough linear fallback keeps the worker testable in the main
    environment, which deliberately has neither librosa nor scipy.
    """
    if from_rate == to_rate:
        return samples
    if from_rate <= 0 or to_rate <= 0:
        raise MsstError("sample rates must be positive")
    try:
        import librosa

        return np.asarray(
            librosa.resample(samples, orig_sr=from_rate, target_sr=to_rate, axis=-1),
            dtype=np.float32,
        )
    except ImportError:
        old_frames = int(samples.shape[-1])
        new_frames = max(1, int(round(old_frames * to_rate / from_rate)))
        old_positions = np.arange(old_frames, dtype=np.float64)
        new_positions = np.linspace(0.0, old_frames - 1.0, new_frames, dtype=np.float64)
        return np.asarray(
            [np.interp(new_positions, old_positions, row) for row in samples],
            dtype=np.float32,
        )


def fit_frames(samples: np.ndarray, frames: int) -> np.ndarray:
    """Trim or zero-pad ``(channels, frames)`` to the source frame count."""
    current = int(samples.shape[-1])
    if current == frames:
        return np.ascontiguousarray(samples, dtype=np.float32)
    if current > frames:
        return np.ascontiguousarray(samples[:, :frames], dtype=np.float32)
    pad = frames - current
    return np.ascontiguousarray(np.pad(samples, ((0, 0), (0, pad))), dtype=np.float32)


def validate_instruments(entry: ModelEntry, instruments: tuple[str, ...]) -> None:
    expected = tuple(entry.labels)
    if tuple(instruments) != expected:
        raise MsstError(
            f"{entry.id}: separator.instruments {tuple(instruments)!r} does not match "
            f"analysis/models.json labels {expected!r}"
        )


def _interleaved(stem: np.ndarray) -> bytes:
    if stem.ndim != 2:
        raise MsstError(f"stem has shape {stem.shape}; expected (channels, frames)")
    return np.ascontiguousarray(stem.T, dtype="<f4").tobytes()


def _write_stem(path: Path, stem: np.ndarray) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as handle:
        handle.write(_interleaved(stem))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _model_files(entry: ModelEntry, models_root: Path) -> tuple[Path, Path]:
    model_dir = model_directory(entry, models_root)
    checkpoint: Path | None = None
    config: Path | None = None
    for item in entry.files:
        path = model_dir / item.name
        if not path.is_file():
            raise MsstError(f"{entry.id}: installed file is missing: {path}")
        if item.role == "checkpoint":
            checkpoint = path
        elif item.role in {"config", "yaml"}:
            config = path
    if checkpoint is None or config is None:
        raise MsstError(f"{entry.id}: registry lacks a checkpoint/config pair")
    return checkpoint, config


def _entry(model_id: str, registry_path: Path) -> ModelEntry:
    try:
        registry = load_registry(registry_path)
    except ModelRegistryError as error:
        raise MsstError(str(error)) from error
    entry = registry.get(model_id)
    if entry.engine != "msst":
        raise MsstError(f"{model_id} uses engine {entry.engine!r}, not msst")
    return entry


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MSST SCNet/RoFormer separation worker")
    parser.add_argument("--input", type=Path, required=True, help="interleaved f32le PCM")
    parser.add_argument("--out", type=Path, required=True, help="staging output directory")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--sample-rate", type=int, required=True)
    parser.add_argument("--channels", type=int, required=True)
    parser.add_argument(
        "--models-root",
        type=Path,
        default=ROOT,
        help="repository root containing models/ (default: repo root)",
    )
    parser.add_argument("--registry", type=Path, default=ROOT / "analysis" / "models.json")
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    out_dir = Path(args.out)
    stage = out_dir / f".msst-stage-{os.getpid()}"
    started = time.monotonic()

    def _terminate(signum: int, frame: object) -> None:
        raise Terminated(f"signal {signum}")

    old_term = signal.signal(signal.SIGTERM, _terminate)
    old_int = signal.signal(signal.SIGINT, _terminate)
    try:
        entry = _entry(args.model_id, args.registry)
        model_type = MSST_MODEL_TYPES.get(entry.id)
        if model_type is None:
            raise MsstError(f"{entry.id}: no MSST model_type mapping")
        checkpoint, config = _model_files(entry, args.models_root)
        if args.sample_rate <= 0 or args.channels not in (1, 2):
            raise MsstError(
                f"invalid project layout: {args.sample_rate} Hz, {args.channels} channels"
            )
        input_path = Path(args.input)
        if not input_path.is_file():
            raise MsstError(f"input PCM is missing: {input_path}")
        raw = np.fromfile(input_path, dtype="<f4")
        if raw.size == 0 or raw.size % args.channels:
            raise MsstError(f"input PCM is empty or not aligned to {args.channels} channels")
        audio = raw.reshape(-1, args.channels).T.astype(np.float32, copy=False)
        source_frames = int(audio.shape[-1])
        device = resolve_device(args.device, cuda_available=cuda_available())
        emit({"type": "progress", "stage": "loading", "fraction": 0.05, "model_id": entry.id})

        try:
            from msst.inference import Separator
        except ImportError as error:
            raise MsstError(
                "msst is not importable; run `uv sync --directory analysis-models --offline`"
            ) from error

        # MSST prints model-load chatter on stdout; keep stdout JSONL-only.
        with contextlib.redirect_stdout(sys.stderr):
            separator = Separator(
                config_path=config,
                checkpoint_path=checkpoint,
                model_type=model_type,
                force_cpu=device == "cpu",
                detailed_progress=False,
            )
        try:
            instruments = tuple(separator.instruments)
            validate_instruments(entry, instruments)
            emit(
                {
                    "type": "progress",
                    "stage": "separating",
                    "fraction": 0.2,
                    "model_id": entry.id,
                    "device": device,
                }
            )
            with contextlib.redirect_stdout(sys.stderr):
                outputs = separator.separate(
                    audio,
                    sample_rate=args.sample_rate,
                    channels_first=True,
                )
            emit({"type": "progress", "stage": "resampling", "fraction": 0.85})
            stems: dict[str, np.ndarray] = {}
            for label in entry.labels:
                if label not in outputs:
                    raise MsstError(
                        f"{entry.id}: separator returned {sorted(outputs)} but no {label!r} stem"
                    )
                stem = np.asarray(outputs[label], dtype=np.float32)
                if stem.ndim == 1:
                    stem = stem[None, :]
                if stem.shape[0] == 1:
                    stem = np.repeat(stem, 2, axis=0)
                if stem.shape[0] != 2:
                    raise MsstError(f"{label}: expected stereo output, got shape {stem.shape}")
                stem = resample_audio(stem, separator.sample_rate, args.sample_rate)
                stems[label] = fit_frames(stem, source_frames)
            stage.mkdir(parents=True, exist_ok=True)
            emit({"type": "progress", "stage": "writing", "fraction": 0.9})
            for label, stem in stems.items():
                _write_stem(stage / f"{label}.f32", stem)
            elapsed = time.monotonic() - started
            peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            meta = {
                "status": "complete",
                "model_id": entry.id,
                "labels": list(entry.labels),
                "frames": source_frames,
                "sample_rate": args.sample_rate,
                "channels": 2,
                "device": device,
                "elapsed_seconds": round(elapsed, 3),
                "peak_rss_kb": peak_rss_kb,
                "engine": "msst",
                "model_type": model_type,
            }
            (stage / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            out_dir.mkdir(parents=True, exist_ok=True)
            for label in entry.labels:
                (stage / f"{label}.f32").replace(out_dir / f"{label}.f32")
            (stage / "meta.json").replace(out_dir / "meta.json")
            stage.rmdir()
            emit({"type": "done", **meta})
            return EXIT_OK
        finally:
            with contextlib.suppress(Exception):
                separator.close()
    except Terminated as error:
        with contextlib.suppress(Exception):
            import shutil

            shutil.rmtree(stage, ignore_errors=True)
        print(f"separation cancelled: {error}", file=sys.stderr, flush=True)
        emit({"type": "cancelled"})
        return EXIT_CANCELLED
    except Exception as error:  # noqa: BLE001 - the worker reports, never crashes bare
        with contextlib.suppress(Exception):
            import shutil

            shutil.rmtree(stage, ignore_errors=True)
        traceback.print_exc()
        emit({"type": "failed", "error": f"{type(error).__name__}: {error}"})
        return EXIT_ERROR
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)


if __name__ == "__main__":
    raise SystemExit(main())
