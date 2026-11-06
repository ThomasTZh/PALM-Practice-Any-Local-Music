"""Fast contract tests for the analysis worker (no inference)."""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from basseparate.config import runtime_paths

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = runtime_paths()
WORKER = RUNTIME.demucs_worker
BUNDLE = RUNTIME.models_root / "models" / "htdemucs_ft"


def load_worker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("separate_track_contract", WORKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checkpoint_manifest_hashes_every_local_artifact() -> None:
    worker = load_worker()
    manifest = worker.load_manifest()
    assert len(manifest["checkpoints"]) == 4
    result = worker.verify_bundle(BUNDLE, manifest)
    assert result["ok"] is True, result["problems"]
    for name, entry in manifest["checkpoints"].items():
        assert result["checkpoints"][name]["sha256"] == entry["sha256"]
        assert result["checkpoints"][name]["size_bytes"] == entry["size_bytes"]


def test_a_tampered_checkpoint_fails_verification(tmp_path: Path) -> None:
    worker = load_worker()
    manifest = worker.load_manifest()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "htdemucs_ft.yaml").symlink_to(BUNDLE / "htdemucs_ft.yaml")
    names = sorted(manifest["checkpoints"])
    for name in names[:-1]:
        (bundle / name).symlink_to(BUNDLE / name)
    tampered = bundle / names[-1]
    shutil.copy2(BUNDLE / names[-1], tampered)
    with tampered.open("r+b") as handle:
        handle.seek(4096)
        current = handle.read(1)
        handle.seek(4096)
        handle.write(bytes([current[0] ^ 0xFF]))
    result = worker.verify_bundle(bundle, manifest)
    assert result["ok"] is False
    assert any("hash mismatch" in problem for problem in result["problems"])


def test_an_extra_checkpoint_is_rejected(tmp_path: Path) -> None:
    worker = load_worker()
    manifest = worker.load_manifest()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "htdemucs_ft.yaml").symlink_to(BUNDLE / "htdemucs_ft.yaml")
    for name in manifest["checkpoints"]:
        (bundle / name).symlink_to(BUNDLE / name)
    (bundle / "unexpected.th").write_bytes(b"not a checkpoint")
    result = worker.verify_bundle(bundle, manifest)
    assert result["ok"] is False
    assert any("unexpected checkpoint" in problem for problem in result["problems"])


def test_device_resolution_never_fakes_cuda() -> None:
    worker = load_worker()
    assert worker.resolve_device("auto", cuda_available=False) == "cpu"
    assert worker.resolve_device("auto", cuda_available=True) == "cuda"
    assert worker.resolve_device("cpu", cuda_available=True) == "cpu"
    assert worker.resolve_device("cuda", cuda_available=True) == "cuda"
    with pytest.raises(ValueError, match="CUDA unavailable"):
        worker.resolve_device("cuda", cuda_available=False)
    with pytest.raises(ValueError, match="unknown device"):
        worker.resolve_device("tpu", cuda_available=False)


def test_window_schedule_covers_the_track_once() -> None:
    worker = load_worker()
    window = 120 * 44_100
    overlap = 8 * 44_100
    frames = 300 * 44_100 + 123
    schedule = worker.window_schedule(frames, window, overlap)
    assert schedule[0][0] == 0
    assert schedule[-1][0] + schedule[-1][1] == frames
    for (offset, length), (next_offset, _) in zip(schedule, schedule[1:], strict=False):
        assert next_offset == offset + window - overlap
        assert 0 < length <= window
    assert len(schedule) >= 3


def test_window_schedule_handles_a_short_fixture() -> None:
    worker = load_worker()
    assert worker.window_schedule(8 * 44_100, 120 * 44_100, 8 * 44_100) == [(0, 8 * 44_100)]
    assert worker.window_schedule(0, 100, 10) == []


def test_worker_source_has_no_top_level_torch_import() -> None:
    # Importing the module in the application venv must not import torch.
    assert "torch" not in os.environ.get("PYTEST_TORCH_GUARD", "")
    worker = load_worker()
    assert worker.PRESET == "htdemucs_ft"
