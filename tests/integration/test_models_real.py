"""Real MSST runs on the 8 s fixture (opt-in; weights must be installed).

Run with::

    RUN_SEPARATION_MODELS=1 .venv/bin/python -m pytest tests/integration/test_models_real.py -q

The test writes one 44.1 kHz stereo PCM from the deterministic chord fixture,
runs the SCNet XL IHF and BS-RoFormer-SW workers, and records wall time and
peak RSS from the worker meta. It uses the already installed local weights and
never downloads anything.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from basseparate.model_registry import load_registry, verify_registry

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "audio" / "chords_c_am_f_g.wav"
ANALYSIS_PYTHON = ROOT / "analysis-models" / ".venv" / "bin" / "python"
WORKER = ROOT / "analysis" / "separate_msst.py"
MODEL_IDS = ("scnet-xl-ihf", "bs-roformer-sw")

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SEPARATION_MODELS") != "1",
    reason="set RUN_SEPARATION_MODELS=1 for real MSST inference",
)


def stereo_fixture(path: Path) -> int:
    with wave.open(str(FIXTURE), "rb") as handle:
        frames = handle.getnframes()
        channels = handle.getnchannels()
        assert handle.getframerate() == 44100
        raw = handle.readframes(frames)
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels == 1:
        samples = np.column_stack([samples, samples])
    else:
        samples = samples.reshape(-1, channels)[:, :2]
    np.ascontiguousarray(samples, dtype="<f4").tofile(path)
    return int(samples.shape[0])


def test_installed_msst_models_and_real_runs(tmp_path: Path) -> None:
    registry = load_registry()
    states = {state.entry.id: state for state in verify_registry(registry)}
    for model_id in MODEL_IDS:
        assert states[model_id].installed, states[model_id].detail
    assert ANALYSIS_PYTHON.is_file(), f"missing {ANALYSIS_PYTHON}; run make models-install"
    assert WORKER.is_file()

    pcm = tmp_path / "fixture-44100-stereo.f32"
    frames = stereo_fixture(pcm)
    assert frames == 352_800

    for model_id in MODEL_IDS:
        output = tmp_path / model_id
        started = time.perf_counter()
        result = subprocess.run(
            [
                str(ANALYSIS_PYTHON),
                str(WORKER),
                "--input",
                str(pcm),
                "--out",
                str(output),
                "--model-id",
                model_id,
                "--sample-rate",
                "44100",
                "--channels",
                "2",
                "--device",
                "auto",
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        wall = time.perf_counter() - started
        assert result.returncode == 0, result.stderr[-4000:]
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        done = next(event for event in events if event["type"] == "done")
        meta = json.loads((output / "meta.json").read_text(encoding="utf-8"))
        expected_labels = list(registry.get(model_id).labels)
        assert meta["status"] == "complete"
        assert meta["model_id"] == model_id
        assert meta["labels"] == expected_labels
        assert meta["frames"] == frames
        assert meta["sample_rate"] == 44100
        assert meta["channels"] == 2
        assert meta["device"] in {"cpu", "cuda"}
        assert meta["elapsed_seconds"] > 0
        assert meta["peak_rss_kb"] > 0
        assert done["labels"] == expected_labels
        for label in expected_labels:
            path = output / f"{label}.f32"
            assert path.is_file()
            assert path.stat().st_size == frames * 2 * 4
        print(
            f"REAL_MSST {model_id}: wall={wall:.2f}s "
            f"child={meta['elapsed_seconds']:.2f}s "
            f"peak_rss={meta['peak_rss_kb'] / 1024:.1f} MiB device={meta['device']}"
        )
    print("REAL_MSST 60s estimate: scale the 8 s wall time by 7.5x")
