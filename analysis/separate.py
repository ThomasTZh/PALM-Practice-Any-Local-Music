"""Bounded windowed Demucs separation worker (M2.5, spec §7).

Run with the explicit analysis interpreter (never imported by the
application — the main environment stays torch/demucs-free):

    analysis/.venv/bin/python analysis/separate.py \
        --input prepared.pcm --profile profile.json \
        --bundle-dir models/htdemucs_ft --device cuda:1 \
        --out staged/ --seed 20261010 --cancel cancel.file

Pipeline (spec §7.1–7.7):

1. HF-offline env vars are set before any demucs/torch import. The
   checked-in registry (loaded by file path, M2.3 pattern) verifies the
   bundle artifact hashes; ``get_model("htdemucs_ft", repo=...)`` loads
   with no network; the model's declared ``sources`` are cross-checked
   against the registry labels (never a hard-coded tensor index).
2. The M2.4 normalization profile gates the run: ``exact_silence``
   writes four zero stem files and exits 0 **without loading the model**
   (spec §6.4.1). The input file hash must match
   ``prepared_input_hash``.
3. 120 s outer windows, 8 s overlap (``window_schedule`` from the
   torch-free main-env module, loaded by file path). Every window is
   seeded with ``run_seed + window_index`` (Python ``random`` — the
   module demucs draws its shift offsets from — plus ``torch``),
   pre-scaled with the **same global profile** (spec §7.2.3), run
   through ``apply_model`` with ``shifts=2``, ``split=True``,
   ``overlap=0.5`` and the effective internal ``segment`` (Demucs'
   internal segment handling does the work inside each window, §7.2.4),
   restored to output scale (§7.2.6), blended with complementary
   raised-cosine weights, accumulated in float64, divided, and the
   non-overlap prefix is appended to the staged stem files as interleaved
    float32 little-endian PCM (the prepared-input layout; time-contiguous
    window blocks concatenate into one valid stream) — only the
   active window and the overlap tail stay in memory (§7.2.9–10).
4. Progress is work units = Σ_windows (models × shifts × internal
   segments); one unit per completed segment (the pinned callback
   facility, §7.4); JSON lines on stdout.
5. Cancellation: the cancel file is checked between windows and inside
   the callback; raising cancels the queued chunks (demucs
   ``pool.shutdown(cancel_futures=True)``), staged outputs are removed,
   exit 2 (§7.6).
6. Memory recovery: OOM restarts the complete run under the next
   validated internal segment (7.5 → 5 → 3 s) in a distinct staged
   directory (distinct cache identity); bounded retries; final failure
   exits 3 with a JSON suggestion offering CPU/another device (§7.5).
   Stems from different profiles are never mixed.

Exit codes: 0 complete (or exact-silence shortcut); 2 cancelled;
3 memory failure after the retry ladder; 1 any other error.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOWING_PATH = REPO_ROOT / "src" / "basseparate" / "media" / "windowing.py"
REGISTRY_PATH = REPO_ROOT / "src" / "basseparate" / "models" / "registry.py"

PRESET = "htdemucs_ft"
SHIFTS = 2
INTERNAL_OVERLAP = 0.5
DEFAULT_SEGMENT_SECONDS = 7.5
RETRY_SEGMENTS_SECONDS = (5.0, 3.0)
DEFAULT_WINDOW_SECONDS = 120.0
DEFAULT_OVERLAP_SECONDS = 8.0

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CANCELLED = 2
EXIT_MEMORY = 3


def _stem_block_bytes(stems: np.ndarray) -> bytes:
    """Serialize one ``(channels, frames)`` block as interleaved f32le PCM.

    Stem files use the project PCM convention — interleaved float32
    little-endian, ``(frames, channels)`` — the same layout as the
    prepared input. A windowed run appends one block per outer window;
    the frames are time-contiguous, so the concatenated blocks form one
    valid whole-track interleaved stream.
    """
    return np.ascontiguousarray(stems.T, dtype="<f4").tobytes()


class SeparationCancelled(Exception):
    """Cancellation requested (cancel file appeared)."""


class MemoryFailure(Exception):
    """A run attempt failed with an out-of-memory error."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


windowing = _load_module("basseparate_media_windowing", WINDOWING_PATH)
registry = _load_module("basseparate_models_registry", REGISTRY_PATH)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(2**20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(bundle: Path, manifest) -> dict:
    """Verify every registry artifact in the bundle (M2.3 pattern)."""
    results = {}
    for spec in manifest.artifacts:
        path = bundle / spec.name
        if not path.is_file():
            results[spec.name] = {"ok": False, "error": "missing"}
            continue
        actual_hash = _sha256(path)
        ok = path.stat().st_size == spec.size_bytes and actual_hash == spec.sha256
        results[spec.name] = {"ok": ok, "sha256": actual_hash}
        if not ok:
            results[spec.name]["error"] = "size/hash mismatch"
    return results


def read_profile(path: Path) -> dict:
    """Load and validate the M2.4 normalization profile JSON."""
    with path.open("r", encoding="utf-8") as handle:
        profile = json.load(handle)
    required = (
        "version",
        "mode",
        "scale",
        "epsilon",
        "reference",
        "prepared_input_hash",
        "channel_mean",
        "full_channel",
    )
    missing = [key for key in required if key not in profile]
    if missing:
        raise ValueError(f"profile is missing fields: {missing}")
    if profile["mode"] not in ("normal", "full_channel_fallback", "exact_silence"):
        raise ValueError(f"unknown profile mode: {profile['mode']}")
    if profile["reference"] not in ("channel_mean", "full_channel"):
        raise ValueError(f"unknown profile reference: {profile['reference']}")
    return profile


def resolve_reference(profile: dict) -> tuple[float, float]:
    """(mean, scale) of the profile's selected reference domain.

    ``scale`` is already ``1 / max(rms_reference, epsilon)`` (bounded);
    the mean is taken from the same domain so pre/restore are exact
    inverses.
    """
    domain = profile[profile["reference"]]
    return float(domain["mean"]), float(profile["scale"])


@dataclass
class Progress:
    """Work-unit progress across windows × models × shifts × segments.

    Also owns the in-callback cancellation check (spec §7.6): the cancel
    file is stat'ed on every completed segment, and raising here cancels
    the remaining queued chunks (demucs ``pool.shutdown(cancel_futures)``).
    """

    total_units: int
    cancel_path: Path | None = None
    completed: int = 0
    window: int = 0
    window_count: int = 0

    def on_segment(self, info: dict) -> None:
        # The pinned callback fires per internal segment with
        # model_idx_in_bag / shift_idx / segment_offset / state.
        if self.cancel_path is not None and self.cancel_path.exists():
            raise SeparationCancelled()
        if info.get("state") == "end":
            self.completed += 1
            line = {
                "type": "segment",
                "window": self.window,
                "window_count": self.window_count,
                "model_idx": info.get("model_idx_in_bag"),
                "shift_idx": info.get("shift_idx"),
                "segment_offset": info.get("segment_offset"),
                "completed_units": self.completed,
                "total_units": self.total_units,
                "fraction": self.completed / self.total_units if self.total_units else 1.0,
            }
            print(json.dumps(line), flush=True)

    def emit(self, **data) -> None:
        print(json.dumps(data), flush=True)


def plan_units(
    schedule: list[tuple[int, int]], rate: int, segment: float, models: int
) -> tuple[list[int], int]:
    """Per-window work units and the total (spec §7.4).

    Demucs' shifts branch splits a view of length
    ``length + max_shift - offset`` (at most ``length + max_shift``), so
    the segments per (model, shift) are bounded by
    ``ceil((length + max_shift) / stride)``. The total is an upper bound;
    the reported fraction never exceeds 1.0.
    """
    seg_len = int(rate * segment)
    stride = int((1 - INTERNAL_OVERLAP) * seg_len)
    max_shift = int(rate / 2)
    per_window = [
        models * SHIFTS * ((length + max_shift + stride - 1) // stride)
        for _, length in schedule
    ]
    return per_window, sum(per_window)


def run_attempt(
    *,
    model,
    torch,
    apply_model,
    input_path: Path,
    total_frames: int,
    rate: int,
    mean: float,
    scale: float,
    out_dir: Path,
    labels: list[str],
    device,
    seed: int,
    window_frames: int,
    overlap_frames: int,
    segment: float,
    cancel_path: Path | None,
    progress: Progress,
) -> int:
    """One complete run under a fixed effective segment profile.

    Returns the number of frames written per stem. Raises
    ``SeparationCancelled`` / ``MemoryFailure``; on either, the staged
    stem files in ``out_dir`` are left for the caller to remove.
    """
    schedule = windowing.window_schedule(total_frames, window_frames, overlap_frames)
    progress.window_count = len(schedule)

    pending_sum = np.zeros((len(labels), 2, 0), dtype=np.float64)
    pending_w = np.zeros(0, dtype=np.float64)
    stem_files = [out_dir.joinpath(f"{label}.pcm").open("wb") for label in labels]
    written = 0
    try:
        for idx, (offset, length) in enumerate(schedule):
            if cancel_path is not None and cancel_path.exists():
                raise SeparationCancelled()
            # Reproducible per-window seed: run seed + window index
            # (spec §7.2.5). Python `random` is what demucs draws its
            # shift offsets from.
            random.seed(seed + idx)
            torch.manual_seed(seed + idx)
            progress.window = idx + 1

            with input_path.open("rb") as handle:
                handle.seek(offset * 2 * 4)
                raw = handle.read(length * 2 * 4)
            x = np.frombuffer(raw, dtype="<f4").reshape(length, 2)
            x = windowing.pre_scale(x, mean, scale)  # same global profile (§7.2.3)
            # demucs expects (batch, channels, length): transpose to (2, L).
            mix = torch.from_numpy(np.ascontiguousarray(x.T)).unsqueeze(0)

            try:
                stems = apply_model(
                    model,
                    mix,
                    shifts=SHIFTS,
                    split=True,
                    overlap=INTERNAL_OVERLAP,
                    segment=segment,
                    device=device,
                    num_workers=0,
                    callback=progress.on_segment,
                )
            except torch.cuda.OutOfMemoryError as exc:
                raise MemoryFailure(f"cuda OOM in window {idx + 1}: {exc}") from exc
            except MemoryError as exc:
                raise MemoryFailure(f"host MemoryError in window {idx + 1}") from exc

            stems = stems[0].cpu().numpy()  # (sources, channels, length) float32
            stems = windowing.restore_scale(stems, mean, scale)  # §7.2.6
            is_last = idx == len(schedule) - 1
            weight = windowing.outer_window_weight(
                length, overlap_frames, is_first=(idx == 0), is_last=is_last
            )
            region, region_w = windowing.accumulate_overlap(
                pending_sum, pending_w, stems, weight
            )
            # Finalize everything except the overlap tail the next
            # window will re-cover (the last window finalizes all).
            finalize_len = length if is_last else length - overlap_frames
            finalized, pending_sum, pending_w = windowing.finalize_region(
                region, region_w, finalize_len
            )
            for i in range(len(labels)):
                stem_files[i].write(_stem_block_bytes(finalized[i]))
            written += finalize_len
            progress.emit(
                type="window",
                window=idx + 1,
                window_count=len(schedule),
                frames=written,
                total_frames=total_frames,
            )
    finally:
        for handle in stem_files:
            handle.close()
    return written


def write_zero_stems(out_dir: Path, labels: list[str], frames: int) -> None:
    silence = np.zeros(frames * 2, dtype="<f4").tobytes()
    for label in labels:
        out_dir.joinpath(f"{label}.pcm").write_bytes(silence)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded windowed Demucs separation worker")
    parser.add_argument("--input", type=Path, required=True, help="prepared input PCM (f32le)")
    parser.add_argument("--profile", type=Path, required=True, help="normalization profile JSON")
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=REPO_ROOT / "models" / "htdemucs_ft",
        help="bundled model directory (default: models/htdemucs_ft)",
    )
    parser.add_argument("--device", default="cpu", help="torch device (default: cpu)")
    parser.add_argument("--out", type=Path, required=True, help="staged output directory")
    parser.add_argument("--seed", type=int, required=True, help="fixed run seed (recorded)")
    parser.add_argument(
        "--cancel", type=Path, default=None, help="cancellation flag file path"
    )
    parser.add_argument(
        "--segment",
        type=float,
        default=DEFAULT_SEGMENT_SECONDS,
        help="initial internal segment seconds (default 7.5)",
    )
    parser.add_argument(
        "--window-seconds", type=float, default=DEFAULT_WINDOW_SECONDS
    )
    parser.add_argument(
        "--overlap-seconds", type=float, default=DEFAULT_OVERLAP_SECONDS
    )
    args = parser.parse_args()

    # Disable every remote fetch path before demucs/torch are imported.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    started = time.time()
    record: dict = {
        "version": 1,
        "status": "failed",
        "device": args.device,
        "seed": args.seed,
        "window_policy": {
            "version": windowing.WINDOW_POLICY_VERSION,
            "window_seconds": args.window_seconds,
            "overlap_seconds": args.overlap_seconds,
        },
        "quality": {
            "preset": PRESET,
            "shifts": SHIFTS,
            "internal_overlap": INTERNAL_OVERLAP,
        },
        "attempts": [],
    }

    def finish(status: str, code: int, **extra) -> int:
        record["status"] = status
        record["timings"] = {"seconds": round(time.time() - started, 3)}
        record.update(extra)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "run-record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"type": "final", "status": status, "record": str(args.out / "run-record.json")}
            ),
            flush=True,
        )
        return code

    try:
        import torch  # noqa: E402  (after the offline env vars)

        # Spec §7 mandates float32: TF32 tensor-core acceleration (10-bit
        # mantissa) is not float32, and with TF32 enabled cuBLAS/cuDNN may
        # select algorithms whose workspace needs depend on the GPU memory
        # state at run time, making results process-dependent. Pinning both
        # flags off gives full-precision float32, stable across processes.
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False

        from demucs.apply import apply_model  # noqa: E402
        import demucs.pretrained  # noqa: E402

        profile = read_profile(args.profile)
        rate = 44100
        channels = 2
        # Input identity (spec §6.2.2 / §7.7: verified shared transform).
        input_hash = _sha256(args.input)
        if input_hash != profile["prepared_input_hash"]:
            raise ValueError(
                "input hash mismatch: the prepared input does not match "
                "the normalization profile"
            )
        total_frames = args.input.stat().st_size // (4 * channels)
        if total_frames <= 0:
            raise ValueError("input PCM is empty")
        record["input"] = {
            "hash": input_hash,
            "frame_count": total_frames,
            "sample_rate": rate,
            "channels": channels,
        }
        record["profile"] = {
            "version": profile["version"],
            "hash": profile["prepared_input_hash"],
            "mode": profile["mode"],
            "scale": profile["scale"],
        }

        manifest = registry.get_manifest(PRESET)
        if rate != manifest.input_sample_rate or channels != manifest.input_channels:
            raise ValueError("prepared input does not match the model's input layout")
        labels = list(manifest.output_labels)

        # Exact silence: zero stems without inference (spec §6.4.1).
        if profile["mode"] == "exact_silence":
            out_dir = args.out / "attempt-1"
            out_dir.mkdir(parents=True, exist_ok=True)
            write_zero_stems(out_dir, labels, total_frames)
            return finish("complete_silence", EXIT_OK, frames=total_frames, outputs=str(out_dir), labels=labels)

        verification = verify_bundle(args.bundle_dir, manifest)
        if not all(entry["ok"] for entry in verification.values()):
            raise RuntimeError(f"bundle does not verify against the registry: {verification}")
        record["model_identity"] = {
            "preset": PRESET,
            "artifacts": {name: entry["sha256"] for name, entry in verification.items()},
        }

        model = demucs.pretrained.get_model(PRESET, repo=args.bundle_dir)
        model.eval()
        if list(model.sources) != labels:
            raise RuntimeError(
                f"model sources {list(model.sources)} do not match the "
                f"registry labels {labels}"
            )
        device = torch.device(args.device)
        if device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError(f"cuda device requested but unavailable: {args.device}")
        max_segment = model.max_allowed_segment
        if args.segment > max_segment:
            raise RuntimeError(
                f"segment {args.segment} s exceeds the model's validated "
                f"maximum {max_segment} s"
            )

        window_frames = int(args.window_seconds * rate)
        overlap_frames = int(args.overlap_seconds * rate)
        mean, scale = resolve_reference(profile)
        # Memory-recovery ladder (spec §7.5): initial, then 5 s, then 3 s.
        ladder: list[float] = [args.segment]
        for candidate in RETRY_SEGMENTS_SECONDS:
            if candidate < args.segment and candidate not in ladder:
                ladder.append(candidate)

        last_error: str | None = None
        for attempt_no, segment in enumerate(ladder, start=1):
            out_dir = args.out / f"attempt-{attempt_no}"
            out_dir.mkdir(parents=True, exist_ok=True)
            record["attempts"].append(
                {"attempt": attempt_no, "segment_seconds": segment, "status": "running"}
            )
            models = len(model.models) if hasattr(model, "models") else 1
            schedule = windowing.window_schedule(total_frames, window_frames, overlap_frames)
            _, total_units = plan_units(schedule, rate, segment, models)
            progress = Progress(total_units=total_units, cancel_path=args.cancel)
            try:
                frames = run_attempt(
                    model=model,
                    torch=torch,
                    apply_model=apply_model,
                    input_path=args.input,
                    total_frames=total_frames,
                    rate=rate,
                    mean=mean,
                    scale=scale,
                    out_dir=out_dir,
                    labels=labels,
                    device=device,
                    seed=args.seed,
                    window_frames=window_frames,
                    overlap_frames=overlap_frames,
                    segment=segment,
                    cancel_path=args.cancel,
                    progress=progress,
                )
                record["attempts"][-1]["status"] = "complete"
                record["quality"]["segment_seconds"] = segment
                return finish(
                    "complete", EXIT_OK, frames=frames, outputs=str(out_dir), labels=labels
                )
            except SeparationCancelled:
                shutil.rmtree(out_dir, ignore_errors=True)
                record["attempts"][-1]["status"] = "cancelled"
                return finish("cancelled", EXIT_CANCELLED)
            except MemoryFailure as exc:
                last_error = str(exc)
                record["attempts"][-1]["status"] = "memory_failure"
                record["attempts"][-1]["error"] = last_error
                shutil.rmtree(out_dir, ignore_errors=True)
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

        return finish(
            "failed_memory",
            EXIT_MEMORY,
            error=last_error,
            suggestion={
                "try_device": "cpu" if device.type == "cuda" else None,
                "note": (
                    "all segment profiles exhausted; try another device "
                    "or explicit CPU execution (spec §7.5.9)"
                ),
            },
        )
    except SeparationCancelled:
        return finish("cancelled", EXIT_CANCELLED)
    except Exception as exc:  # noqa: BLE001 — the worker reports, never crashes bare
        return finish("failed", EXIT_ERROR, error=f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
