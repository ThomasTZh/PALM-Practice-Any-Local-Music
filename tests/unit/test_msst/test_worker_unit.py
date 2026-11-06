"""Pure helpers in the MSST worker (no torch, msst or model weights)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from basseparate.model_registry import ModelEntry, ModelFile

ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / "analysis" / "separate_msst.py"


def load_worker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("separate_msst_unit", WORKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def entry(labels: tuple[str, ...] = ("drums", "bass", "other", "vocals")) -> ModelEntry:
    return ModelEntry(
        id="fake",
        name="Fake",
        engine="msst",
        engine_command="echo",
        labels=labels,
        sample_rate=44100,
        size_bytes=4,
        source_url="https://example.invalid/model",
        license="test",
        bundled=False,
        install_dir="models/fake",
        files=(
            ModelFile("checkpoint", "m.ckpt", "https://example.invalid/m", 2, "a" * 64),
            ModelFile("config", "m.yaml", "https://example.invalid/y", 2, "b" * 64),
        ),
    )


def test_device_resolution_never_fakes_cuda() -> None:
    worker = load_worker()
    assert worker.resolve_device("auto", cuda_available=False) == "cpu"
    assert worker.resolve_device("auto", cuda_available=True) == "cuda"
    assert worker.resolve_device("cpu", cuda_available=True) == "cpu"
    assert worker.resolve_device("cuda", cuda_available=True) == "cuda"
    with pytest.raises(worker.MsstError, match="CUDA"):
        worker.resolve_device("cuda", cuda_available=False)
    with pytest.raises(worker.MsstError, match="unknown device"):
        worker.resolve_device("tpu", cuda_available=False)


def test_fit_frames_pads_and_trims() -> None:
    worker = load_worker()
    samples = np.arange(10, dtype=np.float32).reshape(2, 5)
    padded = worker.fit_frames(samples, 8)
    assert padded.shape == (2, 8)
    np.testing.assert_array_equal(padded[:, :5], samples)
    np.testing.assert_array_equal(padded[:, 5:], 0.0)
    trimmed = worker.fit_frames(samples, 3)
    assert trimmed.shape == (2, 3)
    np.testing.assert_array_equal(trimmed, samples[:, :3])
    same = worker.fit_frames(samples, 5)
    assert same.shape == (2, 5)
    np.testing.assert_array_equal(same, samples)


def test_resample_audio_round_trip_length_and_dtype() -> None:
    worker = load_worker()
    samples = np.sin(np.linspace(0, 2 * np.pi, 4800, dtype=np.float32))
    stereo = np.vstack([samples, samples]).astype(np.float32)
    resampled = worker.resample_audio(stereo, 48000, 44100)
    assert resampled.dtype == np.float32
    assert resampled.shape[0] == 2
    assert abs(resampled.shape[1] - 4410) <= 1
    back = worker.resample_audio(resampled, 44100, 48000)
    assert abs(back.shape[1] - 4800) <= 1
    same = worker.resample_audio(stereo, 48000, 48000)
    np.testing.assert_array_equal(same, stereo)


def test_instrument_labels_must_match_the_registry() -> None:
    worker = load_worker()
    worker.validate_instruments(entry(), ("drums", "bass", "other", "vocals"))
    with pytest.raises(worker.MsstError, match="does not match"):
        worker.validate_instruments(entry(), ("drums", "bass"))


def test_model_files_resolve_checkpoint_and_config(tmp_path: Path) -> None:
    worker = load_worker()
    model_root = tmp_path / "models" / "fake"
    model_root.mkdir(parents=True)
    (model_root / "m.ckpt").write_bytes(b"ck")
    (model_root / "m.yaml").write_bytes(b"yaml")
    checkpoint, config = worker._model_files(entry(), tmp_path)
    assert checkpoint == model_root / "m.ckpt"
    assert config == model_root / "m.yaml"
    (model_root / "m.ckpt").unlink()
    with pytest.raises(worker.MsstError, match="missing"):
        worker._model_files(entry(), tmp_path)


def test_unknown_model_id_and_engine_are_rejected(tmp_path: Path) -> None:
    worker = load_worker()
    registry = tmp_path / "models.json"
    registry.write_text('{"schema_version":2,"models":[]}', encoding="utf-8")
    with pytest.raises(worker.MsstError):
        worker._entry("missing", registry)
    demucs = entry().to_dict()
    demucs["engine"] = "demucs"
    registry.write_text(
        '{"schema_version":2,"models":[' + __import__("json").dumps(demucs) + "]}",
        encoding="utf-8",
    )
    with pytest.raises(worker.MsstError, match="not msst"):
        worker._entry("fake", registry)
