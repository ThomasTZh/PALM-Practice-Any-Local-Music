"""Short-input reference runner (M2.5, spec §7.3).

Runs the **upstream** whole-track behavior: a single ``apply_model``
call on the entire prepared input with the same quality parameters
(shifts=2, split=True, internal overlap=0.5, 7.5 s segment) and the
same global M2.4 pre-scale. This is the reference the windowed adapter
is compared against. Use on short tracks only — the whole track and
every output tensor stay in RAM by design. Stem files are written as
interleaved float32 little-endian PCM — the same layout as the
prepared input.

    analysis/.venv/bin/python analysis/reference_separate.py \
        --input prepared.pcm --profile profile.json \
        --out ref-staged/ --seed 20261010 --device cuda:1
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from separate import (  # noqa: E402
    INTERNAL_OVERLAP,
    PRESET,
    SHIFTS,
    _sha256,
    _stem_block_bytes,
    read_profile,
    registry,
    resolve_reference,
    verify_bundle,
    windowing,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Upstream whole-track reference runner")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "models" / "htdemucs_ft",
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--segment", type=float, default=7.5)
    parser.add_argument(
        "--offset-seconds",
        type=float,
        default=0.0,
        help="start of the slice (for per-window references)",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="slice length in seconds (default: whole track)",
    )
    args = parser.parse_args()

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    started = time.time()
    try:
        import torch

        # Same float32 precision pin as analysis/separate.py (spec §7): the
        # reference runner and the adapter must run in the same precision
        # mode for the §7.3 comparison to be meaningful.
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False

        from demucs.apply import apply_model
        import demucs.pretrained

        profile = read_profile(args.profile)
        if profile["mode"] == "exact_silence":
            raise SystemExit("reference runner is for non-silent inputs")
        if _sha256(args.input) != profile["prepared_input_hash"]:
            raise SystemExit("input hash does not match the profile")

        manifest = registry.get_manifest(PRESET)
        labels = list(manifest.output_labels)
        verification = verify_bundle(args.bundle_dir, manifest)
        if not all(entry["ok"] for entry in verification.values()):
            raise SystemExit(f"bundle does not verify: {verification}")

        model = demucs.pretrained.get_model(PRESET, repo=args.bundle_dir)
        model.eval()
        if list(model.sources) != labels:
            raise SystemExit("model sources do not match the registry labels")
        device = torch.device(args.device)

        total_frames = args.input.stat().st_size // 8
        offset = int(args.offset_seconds * 44100)
        if offset < 0 or offset >= total_frames:
            raise SystemExit(f"offset {offset} is outside the track")
        if args.seconds is None:
            n = total_frames - offset
        else:
            n = min(int(args.seconds * 44100), total_frames - offset)
        with args.input.open("rb") as handle:
            handle.seek(offset * 2 * 4)
            raw = handle.read(n * 2 * 4)
        x = np.frombuffer(raw, dtype="<f4").reshape(n, 2)
        mean, scale = resolve_reference(profile)
        x = windowing.pre_scale(x, mean, scale)
        mix = torch.from_numpy(np.ascontiguousarray(x.T)).unsqueeze(0)

        # One whole-track call: the upstream behavior (no outer windows).
        random.seed(args.seed)
        torch.manual_seed(args.seed)
        stems = apply_model(
            model,
            mix,
            shifts=SHIFTS,
            split=True,
            overlap=INTERNAL_OVERLAP,
            segment=args.segment,
            device=device,
            num_workers=0,
        )
        stems = stems[0].cpu().numpy()
        stems = windowing.restore_scale(stems, mean, scale)

        args.out.mkdir(parents=True, exist_ok=True)
        for i, label in enumerate(labels):
            (args.out / f"{label}.pcm").write_bytes(_stem_block_bytes(stems[i]))
        record = {
            "version": 1,
            "status": "complete",
            "device": args.device,
            "seed": args.seed,
            "quality": {
                "preset": PRESET,
                "shifts": SHIFTS,
                "internal_overlap": INTERNAL_OVERLAP,
                "segment_seconds": args.segment,
            },
            "input": {
                "hash": profile["prepared_input_hash"],
                "frame_count": n,
                "offset_frames": offset,
            },
            "labels": labels,
            "timings": {"seconds": round(time.time() - started, 3)},
        }
        (args.out / "run-record.json").write_text(json.dumps(record, indent=2))
        print(json.dumps({"type": "final", "status": "complete", "out": str(args.out)}))
        return 0
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
