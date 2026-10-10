"""PyTorch/CUDA qualification for the isolated analysis environment (M2.2).

Run with the analysis environment's explicit interpreter:

    analysis/.venv/bin/python analysis/qualify.py --all

Per CUDA device this runs a small tensor computation, a representative
convolution, an FFT, and a short `htdemucs` separation (spec 4.2.4-4.2.6).
The CPU path runs the same tensor/conv/FFT set with compute threads limited
to four (spec 4.3.2) plus a short model run to prove CPU inference works.
Devices are marked usable only after the model test succeeds (spec 4.2.8).

Prints a JSON report to stdout; exit code 0 iff every requested device
passed. One device is processed at a time; CUDA context is released between
devices (no combined memory pool, spec 4.5).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

DEMUCS_MODEL = "htdemucs"
DEMUCS_SAMPLE_RATE = 44100
DEMUCS_SECONDS = 5.0
CPU_THREADS = 4


def _driver_version() -> str | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return out.stdout.strip().splitlines()[0] or None
    except Exception:
        return None


def _fingerprint() -> dict:
    import torch

    return {
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "torch_cuda_build": torch.version.cuda,
        "demucs": _import_version("demucs"),
        "driver": _driver_version(),
    }


def _import_version(name: str) -> str:
    try:
        module = __import__(name)
        return str(getattr(module, "__version__", "unknown"))
    except Exception:
        return "unavailable"


def _timed(fn):
    start = time.monotonic()
    result = fn()
    return result, time.monotonic() - start


def _tensor_test(device) -> dict:
    import torch

    def run():
        a = torch.randn(512, 512, device=device)
        b = torch.randn(512, 512, device=device)
        c = (a @ b) / 512
        if not torch.isfinite(c).all():
            raise AssertionError("non-finite tensor result")
        return c.shape

    try:
        shape, seconds = _timed(run)
        return {"pass": True, "seconds": round(seconds, 3), "shape": list(shape)}
    except Exception as exc:
        return {"pass": False, "error": f"{type(exc).__name__}: {exc}"}


def _conv_test(device) -> dict:
    import torch
    import torch.nn as nn

    def run():
        conv = nn.Conv2d(1, 8, kernel_size=3, padding=1).to(device)
        x = torch.randn(2, 1, 64, 441, device=device)
        y = conv(x)
        if not torch.isfinite(y).all():
            raise AssertionError("non-finite conv result")
        return y.shape

    try:
        shape, seconds = _timed(run)
        return {"pass": True, "seconds": round(seconds, 3), "shape": list(shape)}
    except Exception as exc:
        return {"pass": False, "error": f"{type(exc).__name__}: {exc}"}


def _fft_test(device) -> dict:
    import torch

    def run():
        x = torch.randn(44100, device=device)
        spectrum = torch.fft.fft(x)
        if not torch.isfinite(spectrum).all():
            raise AssertionError("non-finite fft result")
        return spectrum.shape

    try:
        shape, seconds = _timed(run)
        return {"pass": True, "seconds": round(seconds, 3), "shape": list(shape)}
    except Exception as exc:
        return {"pass": False, "error": f"{type(exc).__name__}: {exc}"}


def _make_short_mix(path: Path) -> None:
    """Write a few seconds of stereo test audio (tones + soft noise)."""
    import numpy as np
    import soundfile as sf

    n = int(DEMUCS_SECONDS * DEMUCS_SAMPLE_RATE)
    t = np.arange(n) / DEMUCS_SAMPLE_RATE
    left = 0.5 * np.sin(2 * np.pi * 110.0 * t) + 0.3 * np.sin(2 * np.pi * 440.0 * t)
    right = 0.5 * np.sin(2 * np.pi * 220.0 * t) + 0.3 * np.sin(2 * np.pi * 330.0 * t)
    noise = 0.05 * np.random.default_rng(42).standard_normal((n, 2))
    mix = np.stack([left, right], axis=-1) + noise  # (frames, channels)
    peak = np.max(np.abs(mix))
    sf.write(path, (mix / peak * 0.9).astype(np.float32), DEMUCS_SAMPLE_RATE)


def _demucs_test(device, report: dict) -> None:
    import soundfile as sf
    import torch

    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    with tempfile.TemporaryDirectory(prefix="basseparate-qualify-") as tmp:
        wav = Path(tmp) / "short_mix.wav"
        _make_short_mix(wav)
        data, _ = sf.read(wav, dtype="float32", always_2d=True)
        wave = torch.from_numpy(data.T).unsqueeze(0)  # (1, 2, n)

        model = None
        try:
            start = time.monotonic()
            # get_model() loads on CPU; move to the target device explicitly.
            model = get_model(DEMUCS_MODEL).to(device)
            sources = apply_model(
                model,
                wave,
                device=device,
                shifts=1,
                split=True,
                overlap=0.25,
                progress=False,
            )
            seconds = time.monotonic() - start
            if not torch.isfinite(sources).all():
                raise AssertionError("non-finite model output")
            report.update(
                {
                    "pass": True,
                    "seconds": round(seconds, 3),
                    "model": DEMUCS_MODEL,
                    "sources": list(sources.shape),
                }
            )
        except Exception as exc:
            report.update({"pass": False, "error": f"{type(exc).__name__}: {exc}"})
            traceback.print_exc(file=sys.stderr)
        finally:
            # Release the model and CUDA context before the next device.
            if model is not None:
                del model
            if str(device).startswith("cuda"):
                torch.cuda.empty_cache()


def _qualify_cuda(index: int) -> dict:
    import torch

    device = torch.device(f"cuda:{index}")
    props = torch.cuda.get_device_properties(index)
    free_bytes, total_bytes = torch.cuda.mem_get_info(index)
    record = {
        "id": f"cuda:{index}",
        "name": props.name,
        "uuid": props.uuid.decode() if isinstance(props.uuid, bytes) else str(props.uuid),
        "vram_total_mib": round(total_bytes / 2**20),
        "vram_free_mib_before": round(free_bytes / 2**20),
    }
    record["tensor"] = _tensor_test(device)
    record["conv"] = _conv_test(device)
    record["fft"] = _fft_test(device)
    record["demucs"] = {}
    _demucs_test(device, record["demucs"])
    record["pass"] = all(
        record[key]["pass"] for key in ("tensor", "conv", "fft", "demucs")
    )
    return record


def _qualify_cpu() -> dict:
    import torch

    torch.set_num_threads(CPU_THREADS)
    device = torch.device("cpu")
    record = {
        "id": "cpu",
        "threads": CPU_THREADS,
        "note": "CPU inference is expected to be slow; explicit selection only.",
    }
    record["tensor"] = _tensor_test(device)
    record["conv"] = _conv_test(device)
    record["fft"] = _fft_test(device)
    record["demucs"] = {}
    _demucs_test(device, record["demucs"])
    record["pass"] = all(
        record[key]["pass"] for key in ("tensor", "conv", "fft", "demucs")
    )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="qualify every CUDA device plus the CPU path",
    )
    parser.add_argument(
        "--cuda",
        type=int,
        action="append",
        default=[],
        metavar="INDEX",
        help="qualify a specific CUDA device index (repeatable)",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="qualify the CPU path",
    )
    args = parser.parse_args(argv)

    if args.all:
        import torch

        indices = list(range(torch.cuda.device_count()))
        use_cpu = True
    else:
        indices = args.cuda
        use_cpu = args.cpu

    if not indices and not use_cpu:
        parser.error("select at least one device: --all, --cuda N, or --cpu")

    report: dict = {"fingerprint": _fingerprint(), "devices": []}
    if indices:
        import torch

        available = torch.cuda.device_count()
        for index in indices:
            if index >= available:
                report["devices"].append(
                    {
                        "id": f"cuda:{index}",
                        "pass": False,
                        "error": f"only {available} CUDA device(s) visible",
                    }
                )
                continue
            report["devices"].append(_qualify_cuda(index))
    if use_cpu:
        report["devices"].append(_qualify_cpu())

    report["overall"] = "pass" if all(d["pass"] for d in report["devices"]) else "fail"
    print(json.dumps(report, indent=2))
    return 0 if report["overall"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
