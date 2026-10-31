#!/usr/bin/env python3
"""Windowed Demucs htdemucs_ft separation for the local studio.

This worker runs in the isolated analysis environment only:

    analysis/.venv/bin/python analysis/separate_track.py \
        --input preparsed.pcm --sample-rate 48000 --channels 2 \
        --out staging/ --device auto --cancel staging/cancel.flag

It is launched as a child process by ``src/basseparate/stems.py``. The main
environment never imports torch or demucs.

Order of operations matters:

1. The four checkpoint SHA-256 values in ``analysis/checkpoints.json`` are
   verified against the local model bundle **before torch/demucs are imported
   and before any model is loaded**. A tampered or missing checkpoint exits 1
   with the name and expected/actual digest on stderr.
2. Offline environment flags are set before the torch import.
3. The input is mono/stereo f32le PCM at the project rate. It is converted to
   the model's 44.1 kHz stereo input with Demucs' bundled Julius resampler.
4. Inference runs in 120 s outer windows with an 8 s overlap. Each window is
   passed to ``apply_model`` with ``shifts=0`` by default and the internal
   segment from the OOM ladder (7.5 s, then 5 s, then 3 s). Raised-cosine
   overlap weights are accumulated, then normalised.
5. Stems are resampled back to the project rate and trimmed/padded to the
   original frame count, so all four share one frame count and align with the
   source PCM.
6. Progress is newline-delimited JSON on stdout. The cancel file is checked
   before each window and on every completed internal segment; cancellation
   removes the staged output and exits 2. OOM retries down the ladder and
   exits 3 only when every segment failed.

Exit codes: 0 complete, 2 cancelled, 3 OOM ladder exhausted, 1 any other
failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "checkpoints.json"
DEFAULT_BUNDLE = REPO_ROOT / "models" / "htdemucs_ft"
PRESET = "htdemucs_ft"
MODEL_SAMPLE_RATE = 44_100
MODEL_CHANNELS = 2
DEFAULT_WINDOW_SECONDS = 120.0
DEFAULT_OVERLAP_SECONDS = 8.0
DEFAULT_SEGMENT_SECONDS = 7.5
RETRY_SEGMENTS_SECONDS = (5.0, 3.0)
INTERNAL_OVERLAP = 0.25
DEFAULT_SHIFTS = 0

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CANCELLED = 2
EXIT_MEMORY = 3


class Cancelled(Exception):
    """The cancel file appeared."""


class OomFailure(Exception):
    """An attempt ran out of memory."""


def emit(event: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(event, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Read the checkpoint manifest; a missing/invalid file is a hard error."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read checkpoint manifest {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"checkpoint manifest {path} is not a JSON object")
    checkpoints = payload.get("checkpoints")
    if not isinstance(checkpoints, dict) or len(checkpoints) != 4:
        raise ValueError(f"checkpoint manifest {path} must list exactly four checkpoints")
    for name, spec in checkpoints.items():
        if not isinstance(spec, dict):
            raise ValueError(f"checkpoint {name} has no size/hash entry")
        if not isinstance(spec.get("sha256"), str) or not isinstance(spec.get("size_bytes"), int):
            raise ValueError(f"checkpoint {name} needs sha256 and size_bytes")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_bundle(bundle: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Verify every declared checkpoint and reject unexpected/missing files."""
    bundle = Path(bundle)
    checkpoints: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    if not bundle.is_dir():
        return {"ok": False, "checkpoints": {}, "problems": [f"bundle directory missing: {bundle}"]}
    expected = manifest["checkpoints"]
    for name, spec in sorted(expected.items()):
        path = bundle / name
        if not path.is_file():
            checkpoints[name] = {"ok": False, "error": "missing"}
            problems.append(f"missing checkpoint {name}")
            continue
        size = path.stat().st_size
        actual = sha256_file(path)
        ok = size == spec["size_bytes"] and actual == spec["sha256"]
        checkpoints[name] = {
            "ok": ok,
            "sha256": actual,
            "size_bytes": size,
        }
        if not ok:
            problems.append(
                f"checkpoint hash mismatch for {name}: "
                f"expected {spec['sha256']} ({spec['size_bytes']} bytes), "
                f"got {actual} ({size} bytes)"
            )
    unexpected = sorted(path.name for path in bundle.glob("*.th") if path.name not in expected)
    if unexpected:
        problems.append(f"unexpected checkpoint files: {', '.join(unexpected)}")
    config_name = f"{manifest.get('preset', PRESET)}.yaml"
    if not (bundle / config_name).is_file():
        problems.append(f"model config missing: {bundle / config_name}")
    return {"ok": not problems, "checkpoints": checkpoints, "problems": problems}


def resolve_device(requested: str, *, cuda_available: bool) -> str:
    """Map ``auto/cpu/cuda`` to a usable device without silently faking GPU."""
    if requested == "auto":
        return "cuda" if cuda_available else "cpu"
    if requested == "cuda":
        if not cuda_available:
            raise ValueError(
                "cuda was requested but torch reports CUDA unavailable; use --device cpu or auto"
            )
        return "cuda"
    if requested == "cpu":
        return "cpu"
    raise ValueError(f"unknown device {requested!r}; choose auto, cpu or cuda")


def window_schedule(
    total_frames: int, window_frames: int, overlap_frames: int
) -> list[tuple[int, int]]:
    """Cover ``total_frames`` with overlapping windows, ending exactly at the end."""
    if total_frames <= 0:
        return []
    if window_frames <= 0:
        raise ValueError("window_frames must be positive")
    if overlap_frames < 0 or overlap_frames >= window_frames:
        raise ValueError("overlap_frames must be in [0, window_frames)")
    schedule: list[tuple[int, int]] = []
    offset = 0
    while offset < total_frames:
        length = min(window_frames, total_frames - offset)
        schedule.append((offset, length))
        if offset + length >= total_frames:
            break
        offset += window_frames - overlap_frames
    return schedule


def edge_weight(length: int, overlap: int, *, first: bool, last: bool) -> Any:
    """Raised-cosine weights for one window (numpy is imported by the caller)."""
    import numpy as np

    weight = np.ones(length, dtype=np.float32)
    fade = min(overlap, length // 2)
    if fade > 0:
        if not first:
            ramp = np.linspace(0.0, 1.0, fade, endpoint=False, dtype=np.float32)
            weight[:fade] *= 0.5 - 0.5 * np.cos(np.pi * ramp)
        if not last:
            ramp = np.linspace(1.0, 0.0, fade, endpoint=False, dtype=np.float32)
            weight[-fade:] *= 0.5 - 0.5 * np.cos(np.pi * ramp)
    return weight


def _is_oom(error: BaseException, torch_module: Any) -> bool:
    if isinstance(error, (MemoryError,)):
        return True
    oom_type = getattr(torch_module, "OutOfMemoryError", None)
    if isinstance(oom_type, type) and isinstance(error, oom_type):
        return True
    text = str(error).lower()
    return (
        "out of memory" in text
        or "cannot allocate memory" in text
        or "can't allocate memory" in text
    )


def _check_cancel(cancel_path: Path | None) -> None:
    if cancel_path is not None and cancel_path.exists():
        raise Cancelled()


def _write_stem(path: Path, stem: Any) -> None:
    """Write one ``(channels, frames)`` float tensor as interleaved f32le."""
    import numpy as np

    pcm = np.ascontiguousarray(stem.detach().cpu().numpy().T, dtype="<f4")
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as handle:
        handle.write(pcm.tobytes())
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="windowed Demucs htdemucs_ft separation")
    parser.add_argument("--input", type=Path, required=True, help="interleaved f32le PCM")
    parser.add_argument("--out", type=Path, required=True, help="staging output directory")
    parser.add_argument("--bundle-dir", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"])
    parser.add_argument("--sample-rate", type=int, required=True, help="project sample rate")
    parser.add_argument("--channels", type=int, required=True, help="project channel count")
    parser.add_argument("--window-seconds", type=float, default=DEFAULT_WINDOW_SECONDS)
    parser.add_argument("--overlap-seconds", type=float, default=DEFAULT_OVERLAP_SECONDS)
    parser.add_argument("--segments", type=float, default=DEFAULT_SEGMENT_SECONDS)
    parser.add_argument("--shifts", type=int, default=DEFAULT_SHIFTS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--cancel", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # No network path may open after this point.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"

    started = time.monotonic()
    try:
        manifest = load_manifest(args.manifest)
        verification = verify_bundle(args.bundle_dir, manifest)
        if not verification["ok"]:
            for problem in verification["problems"]:
                print(f"checkpoint verification failed: {problem}", file=sys.stderr, flush=True)
            emit(
                {"type": "failed", "stage": "verify", "error": "; ".join(verification["problems"])}
            )
            return EXIT_ERROR
        emit(
            {
                "type": "verified",
                "checkpoints": {
                    name: entry.get("sha256") for name, entry in verification["checkpoints"].items()
                },
            }
        )

        import demucs.pretrained
        import numpy as np
        import torch
        from demucs.audio import convert_audio, convert_audio_channels

        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False

        device_name = resolve_device(args.device, cuda_available=torch.cuda.is_available())
        device = torch.device(device_name)

        channels = int(args.channels)
        sample_rate = int(args.sample_rate)
        if channels not in (1, 2):
            raise ValueError(f"unsupported channel count {channels}")
        if sample_rate <= 0:
            raise ValueError("sample rate must be positive")
        if args.shifts < 0:
            raise ValueError("shifts must not be negative")
        if args.window_seconds <= 0 or args.overlap_seconds < 0:
            raise ValueError("window must be positive and overlap non-negative")
        if args.overlap_seconds >= args.window_seconds:
            raise ValueError("overlap must be shorter than the window")

        input_path = Path(args.input)
        if not input_path.is_file():
            raise ValueError(f"input PCM does not exist: {input_path}")
        raw = np.fromfile(input_path, dtype="<f4")
        if raw.size == 0 or raw.size % channels:
            raise ValueError(f"input PCM is empty or not aligned to {channels} channels")
        pcm = raw.reshape(-1, channels)
        source_frames = int(pcm.shape[0])

        # Convert the whole track once: one consistent resampler phase, then
        # window scheduling on the model-rate timeline.
        track = torch.from_numpy(np.ascontiguousarray(pcm.T.astype("float32", copy=False)))
        if sample_rate == MODEL_SAMPLE_RATE:
            track = convert_audio_channels(track, MODEL_CHANNELS)
        else:
            track = convert_audio(track, sample_rate, MODEL_SAMPLE_RATE, MODEL_CHANNELS)
        model_frames = int(track.shape[-1])
        window_frames = max(1, int(round(args.window_seconds * MODEL_SAMPLE_RATE)))
        overlap_frames = max(0, int(round(args.overlap_seconds * MODEL_SAMPLE_RATE)))
        schedule = window_schedule(model_frames, window_frames, overlap_frames)

        model = demucs.pretrained.get_model(PRESET, repo=args.bundle_dir)
        model.eval()
        labels = list(getattr(model, "sources", ()))
        if labels != list(manifest["labels"]):
            raise ValueError(
                f"model sources {labels} do not match checkpoint manifest "
                f"labels {manifest['labels']}"
            )

        ladder: list[float] = [float(args.segments)]
        for candidate in RETRY_SEGMENTS_SECONDS:
            if candidate < ladder[0] and candidate not in ladder:
                ladder.append(candidate)
        last_oom: str | None = None
        for attempt_index, segment in enumerate(ladder, start=1):
            _check_cancel(args.cancel)
            emit(
                {
                    "type": "attempt",
                    "attempt": attempt_index,
                    "segments": len(ladder),
                    "segment_seconds": segment,
                    "device": device_name,
                }
            )
            try:
                frames = _run_attempt(
                    model=model,
                    track=track,
                    schedule=schedule,
                    labels=labels,
                    source_frames=source_frames,
                    sample_rate=sample_rate,
                    out_dir=args.out,
                    device=device,
                    segment=segment,
                    shifts=args.shifts,
                    seed=args.seed,
                    cancel_path=args.cancel,
                    attempt_index=attempt_index,
                    attempt_count=len(ladder),
                    overlap_frames=overlap_frames,
                )
            except OomFailure as error:
                last_oom = str(error)
                emit({"type": "oom", "attempt": attempt_index, "error": last_oom})
                shutil.rmtree(args.out, ignore_errors=True)
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                continue
            elapsed = time.monotonic() - started
            meta = {
                "version": 1,
                "status": "complete",
                "preset": PRESET,
                "labels": labels,
                "frames": frames,
                "source_frames": source_frames,
                "sample_rate": sample_rate,
                "channels": MODEL_CHANNELS,
                "device": device_name,
                "elapsed_seconds": round(elapsed, 3),
                "quality": {
                    "window_seconds": args.window_seconds,
                    "overlap_seconds": args.overlap_seconds,
                    "shifts": args.shifts,
                    "segment_seconds": segment,
                },
                "checkpoints": {
                    name: entry.get("sha256") for name, entry in verification["checkpoints"].items()
                },
            }
            (args.out / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            emit(
                {
                    "type": "done",
                    **{
                        key: meta[key] for key in ("frames", "device", "elapsed_seconds", "quality")
                    },
                }
            )
            return EXIT_OK

        emit({"type": "failed", "stage": "memory", "error": last_oom or "OOM ladder exhausted"})
        print(f"separation failed after the OOM ladder: {last_oom}", file=sys.stderr, flush=True)
        return EXIT_MEMORY
    except Cancelled:
        shutil.rmtree(args.out, ignore_errors=True)
        emit({"type": "cancelled"})
        return EXIT_CANCELLED
    except Exception as error:  # noqa: BLE001 - worker reports, never crashes bare
        shutil.rmtree(args.out, ignore_errors=True)
        traceback.print_exc()
        emit({"type": "failed", "stage": "error", "error": f"{type(error).__name__}: {error}"})
        return EXIT_ERROR


def _run_attempt(
    *,
    model: Any,
    track: Any,
    schedule: list[tuple[int, int]],
    labels: list[str],
    source_frames: int,
    sample_rate: int,
    out_dir: Path,
    device: Any,
    segment: float,
    shifts: int,
    seed: int,
    cancel_path: Path | None,
    attempt_index: int,
    attempt_count: int,
    overlap_frames: int,
) -> int:
    import torch
    from demucs.apply import apply_model
    from demucs.audio import convert_audio

    model_frames = int(track.shape[-1])
    segment_frames = max(1, int(round(segment * MODEL_SAMPLE_RATE)))
    stride = max(1, int(round((1 - INTERNAL_OVERLAP) * segment_frames)))
    models = len(getattr(model, "models", [model]))
    total_units = sum(len(range(0, length, stride)) * models for _, length in schedule)
    completed = 0
    accumulator = torch.zeros((len(labels), MODEL_CHANNELS, model_frames), dtype=torch.float32)
    weights = torch.zeros(model_frames, dtype=torch.float32)

    def on_segment(info: dict[str, Any]) -> None:
        nonlocal completed
        _check_cancel(cancel_path)
        if info.get("state") != "end":
            return
        completed += 1
        fraction = completed / total_units if total_units else 1.0
        emit(
            {
                "type": "progress",
                "stage": "separating",
                "fraction": min(1.0, fraction),
                "attempt": attempt_index,
                "attempts": attempt_count,
                "segment_seconds": segment,
                "window": None,
            }
        )

    for window_index, (offset, length) in enumerate(schedule):
        _check_cancel(cancel_path)
        random.seed(seed + window_index)
        torch.manual_seed(seed + window_index)
        chunk = track[:, offset : offset + length].unsqueeze(0)
        try:
            stems = apply_model(
                model,
                chunk,
                shifts=shifts,
                split=True,
                overlap=INTERNAL_OVERLAP,
                segment=segment,
                device=device,
                num_workers=0,
                callback=on_segment,
            )
        except Exception as error:
            if _is_oom(error, torch):
                raise OomFailure(
                    f"{type(error).__name__}: {error} "
                    f"(segment {segment}s, window {window_index + 1})"
                ) from error
            raise
        if not isinstance(stems, torch.Tensor):
            raise TypeError("apply_model returned a non-tensor result")
        stems = stems[0].detach().cpu().to(torch.float32)
        weight = torch.from_numpy(
            edge_weight(
                length,
                overlap_frames,
                first=window_index == 0,
                last=window_index == len(schedule) - 1,
            )
        )
        accumulator[:, :, offset : offset + length] += stems * weight
        weights[offset : offset + length] += weight
        emit(
            {
                "type": "progress",
                "stage": "separating",
                "fraction": min(1.0, completed / total_units if total_units else 1.0),
                "attempt": attempt_index,
                "attempts": attempt_count,
                "segment_seconds": segment,
                "window": window_index + 1,
                "windows": len(schedule),
            }
        )

    weights = weights.clamp_min(1e-8)
    stems = accumulator / weights
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[int] = []
    for index, label in enumerate(labels):
        stem = stems[index]
        if sample_rate != MODEL_SAMPLE_RATE:
            stem = convert_audio(stem, MODEL_SAMPLE_RATE, sample_rate, MODEL_CHANNELS)
        if int(stem.shape[-1]) < source_frames:
            pad = source_frames - int(stem.shape[-1])
            stem = torch.nn.functional.pad(stem, (0, pad))
        elif int(stem.shape[-1]) > source_frames:
            stem = stem[:, :source_frames]
        _write_stem(out_dir / f"{label}.f32", stem)
        written.append(source_frames)
    if len(set(written)) != 1:
        raise RuntimeError(f"stem frame counts differ: {written}")
    return written[0]


if __name__ == "__main__":
    raise SystemExit(main())
