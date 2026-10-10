"""Offline qualification of the bundled htdemucs_ft baseline (spec §5.3.6).

Run with the explicit analysis interpreter:

    analysis/.venv/bin/python analysis/qualify_bundled.py
    analysis/.venv/bin/python analysis/qualify_bundled.py --device cuda:0

Network access is disabled *before* demucs is imported (HF_HUB_OFFLINE and
TRANSFORMERS_OFFLINE), and the model is loaded only from the explicit local
bundle directory — there is no remote fallback path in this script. The
expected artifact set and SHA-256 hashes are read from the checked-in
registry (src/basseparate/models/registry.py), so this script and the
application verify against the same manifest.

Exit code 0 = the bundle verifies, loads, and produces a finite 5 s
inference; 1 = any failure (the JSON report on stdout says which).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "src" / "basseparate" / "models" / "registry.py"


def _load_registry():
    spec = importlib.util.spec_from_file_location("basseparate_models_registry", REGISTRY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load registry module from {REGISTRY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(2**20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_artifacts(bundle: Path, manifest) -> list[dict]:
    results = []
    for spec in manifest.artifacts:
        path = bundle / spec.name
        entry: dict = {"name": spec.name, "ok": False}
        if not path.is_file():
            entry["error"] = "missing"
        else:
            actual_size = path.stat().st_size
            actual_hash = _sha256(path)
            entry.update(
                {
                    "size_bytes": actual_size,
                    "size_expected": spec.size_bytes,
                    "sha256": actual_hash,
                    "sha256_expected": spec.sha256,
                }
            )
            entry["ok"] = actual_size == spec.size_bytes and actual_hash == spec.sha256
            if not entry["ok"]:
                entry["error"] = "size/hash mismatch"
        results.append(entry)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        default=REPO_ROOT / "models" / "htdemucs_ft",
        help="bundle directory (default: models/htdemucs_ft in the repo root)",
    )
    parser.add_argument("--device", default="cpu", help="torch device (default: cpu)")
    args = parser.parse_args()

    # Disable every remote fetch path before demucs/torch are imported.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    report: dict = {
        "bundle": str(args.bundle.resolve()),
        "device": args.device,
        "network": "disabled (HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1)",
        "artifacts": [],
        "overall": "fail",
    }
    try:
        registry = _load_registry()
        manifest = registry.get_manifest("htdemucs_ft")
        report["artifacts"] = verify_artifacts(args.bundle, manifest)
        if not all(a["ok"] for a in report["artifacts"]):
            report["error"] = "bundle does not verify against the registry"
            return _finish(report)

        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        report["fingerprint"] = {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "demucs": _demucs_version(),
        }

        t0 = time.monotonic()
        model = get_model("htdemucs_ft", repo=args.bundle)
        report["load_seconds"] = round(time.monotonic() - t0, 3)
        report["model_type"] = type(model).__name__

        # 5 s of noise at 44.1 kHz stereo (the manifest's input requirements).
        frames = 22050 * 5
        x = torch.randn(1, manifest.input_channels, frames) * 0.05
        t0 = time.monotonic()
        sources = apply_model(
            model,
            x,
            shifts=1,
            split=True,
            overlap=0.25,
            progress=False,
            device=args.device,
            num_workers=0,
        )
        report["inference_seconds"] = round(time.monotonic() - t0, 3)
        report["output_shape"] = list(sources.shape)
        report["finite"] = bool(torch.isfinite(sources).all())

        expected_shape = [1, len(manifest.output_labels), manifest.input_channels, frames]
        if sources.shape != torch.Size(expected_shape) or not report["finite"]:
            report["error"] = "inference output is not the expected finite tensor"
            return _finish(report)

        report["overall"] = "pass"
        return _finish(report)
    except Exception as exc:  # noqa: BLE001 - qualification must report, not crash
        report["error"] = f"{type(exc).__name__}: {exc}"
        return _finish(report)


def _demucs_version() -> str:
    try:
        from importlib.metadata import version

        return version("demucs")
    except Exception:  # noqa: BLE001
        return "unknown"


def _finish(report: dict) -> int:
    print(json.dumps(report, indent=2))
    return 0 if report["overall"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
