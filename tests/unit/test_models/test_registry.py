"""Registry parsing and verification against local fake files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from basseparate.model_registry import (
    ModelRegistryError,
    clear_digest_cache,
    format_size,
    load_registry,
    verify_model,
    verify_registry,
)

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "analysis" / "models.json"
PAYLOAD = b"fake checkpoint bytes"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def fake_registry(tmp_path: Path, **overrides: object) -> Path:
    entry: dict[str, object] = {
        "id": "fake-model",
        "name": "Fake model",
        "engine": "msst",
        "engine_command": "analysis-models/.venv/bin/python analysis/separate_msst.py",
        "labels": ["bass", "other"],
        "sample_rate": 44100,
        "size_bytes": len(PAYLOAD),
        "source_url": "https://example.invalid/model",
        "license": "test licence",
        "bundled": False,
        "install_dir": "models/fake-model",
        "files": [
            {
                "role": "checkpoint",
                "name": "model.ckpt",
                "url": "https://example.invalid/model.ckpt",
                "size_bytes": len(PAYLOAD),
                "sha256": PAYLOAD_SHA,
            }
        ],
    }
    entry.update(overrides)
    payload = {"schema_version": 1, "models": [entry]}
    path = tmp_path / "models.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def fake_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    model_dir = root / "models" / "fake-model"
    model_dir.mkdir(parents=True)
    (model_dir / "model.ckpt").write_bytes(PAYLOAD)
    return root


def test_shipped_registry_declares_all_three_models() -> None:
    registry = load_registry(REGISTRY)
    assert [entry.id for entry in registry.models] == [
        "htdemucs_ft",
        "scnet-xl-ihf",
        "bs-roformer-sw",
    ]
    demucs, scnet, roformer = registry.models
    assert demucs.bundled is True
    assert demucs.checkpoint_manifest == "analysis/checkpoints.json"
    assert demucs.labels == ("drums", "bass", "other", "vocals")
    assert scnet.bundled is False
    assert scnet.engine == "msst"
    assert scnet.labels == ("drums", "bass", "other", "vocals")
    assert scnet.sample_rate == 44100
    assert scnet.size_bytes == 214_069_684
    assert scnet.files[0].size_bytes == 214_063_778
    assert scnet.files[0].sha256.startswith("ac25975f0f5704f3")
    assert scnet.files[1].sha256.startswith("54ddcb8aeeae85c8")
    assert roformer.labels == ("bass", "drums", "other", "vocals", "guitar", "piano")
    assert roformer.size_bytes == 699_416_765
    assert roformer.files[0].size_bytes == 699_412_152
    assert roformer.files[0].sha256.startswith("24e7d35ee9c64415")
    assert roformer.files[1].sha256.startswith("f9fada9f94e5ba2d")
    for entry in registry.models:
        assert entry.engine
        assert entry.engine_command
        assert entry.source_url.startswith("https://")
        assert entry.license
        assert entry.install_command


def test_bundled_demucs_verifies_against_the_checkpoint_manifest() -> None:
    clear_digest_cache()
    registry = load_registry(REGISTRY)
    state = verify_model(registry.get("htdemucs_ft"), ROOT)
    assert state.status == "installed", state.detail
    assert len(state.files) == 5
    assert all(file.ok for file in state.files)


def test_fake_model_verifies_as_installed(tmp_path: Path) -> None:
    entry = load_registry(fake_registry(tmp_path)).get("fake-model")
    state = verify_model(entry, fake_root(tmp_path))
    assert state.status == "installed"
    assert state.entry.labels == ("bass", "other")


def test_missing_short_and_hash_mismatch_states(tmp_path: Path) -> None:
    entry = load_registry(fake_registry(tmp_path)).get("fake-model")
    root = fake_root(tmp_path)
    target = root / "models" / "fake-model" / "model.ckpt"
    target.unlink()
    assert verify_model(entry, root).status == "missing"
    target.write_bytes(PAYLOAD[:-1])
    state = verify_model(entry, root)
    assert state.status == "hash-mismatch"
    assert state.files[0].status == "size-mismatch"
    target.write_bytes(b"x" * len(PAYLOAD))
    state = verify_model(entry, root)
    assert state.status == "hash-mismatch"
    assert state.files[0].status == "hash-mismatch"


def test_extra_file_is_not_installed(tmp_path: Path) -> None:
    entry = load_registry(fake_registry(tmp_path)).get("fake-model")
    root = fake_root(tmp_path)
    (root / "models" / "fake-model" / "surprise.bin").write_bytes(b"extra")
    state = verify_model(entry, root)
    assert state.status == "hash-mismatch"
    assert any(file.role == "extra" for file in state.files)


def test_bundled_extra_checkpoint_is_reported(tmp_path: Path) -> None:
    root = tmp_path / "root"
    model_dir = root / "models" / "htdemucs_ft"
    model_dir.mkdir(parents=True)
    manifest = {
        "checkpoints": {"a.th": {"size_bytes": 1, "sha256": hashlib.sha256(b"a").hexdigest()}}
    }
    (root / "analysis").mkdir()
    (root / "analysis" / "checkpoints.json").write_text(json.dumps(manifest), encoding="utf-8")
    (model_dir / "a.th").write_bytes(b"a")
    (model_dir / "htdemucs_ft.yaml").write_text("preset", encoding="utf-8")
    (model_dir / "b.th").write_bytes(b"b")
    payload = {
        "schema_version": 1,
        "models": [
            {
                "id": "htdemucs_ft",
                "name": "Demucs",
                "engine": "demucs",
                "engine_command": "separate_track.py",
                "labels": ["drums", "bass", "other", "vocals"],
                "sample_rate": 44100,
                "size_bytes": 1,
                "source_url": "https://example.invalid/demucs",
                "license": "test",
                "bundled": True,
                "install_dir": "models/htdemucs_ft",
                "checkpoint_manifest": "analysis/checkpoints.json",
                "config_name": "htdemucs_ft.yaml",
                "files": [],
            }
        ],
    }
    registry_path = tmp_path / "models.json"
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    entry = load_registry(registry_path).get("htdemucs_ft")
    state = verify_model(entry, root)
    assert state.status == "hash-mismatch"
    assert any(file.role == "extra" and file.name == "b.th" for file in state.files)


@pytest.mark.parametrize(
    "override",
    [
        {"id": "Bad/Id"},
        {"engine": "unknown"},
        {"labels": []},
        {"labels": ["bass", "bass"]},
        {"sample_rate": 0},
        {"size_bytes": 4},
        {"source_url": "http://example.invalid/x"},
        {"license": ""},
        {"bundled": True},
        {"files": []},
    ],
)
def test_invalid_entries_are_rejected(tmp_path: Path, override: dict[str, object]) -> None:
    with pytest.raises(ModelRegistryError):
        load_registry(fake_registry(tmp_path, **override))


def test_registry_shape_errors(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ModelRegistryError, match="cannot read"):
        load_registry(path)
    path.write_text(json.dumps({"schema_version": 2, "models": []}), encoding="utf-8")
    with pytest.raises(ModelRegistryError):
        load_registry(path)
    path.write_text(json.dumps({"schema_version": 1, "models": []}), encoding="utf-8")
    with pytest.raises(ModelRegistryError):
        load_registry(path)


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    path = fake_registry(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["models"].append(payload["models"][0])
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ModelRegistryError, match="duplicate"):
        load_registry(path)


def test_bad_hash_is_rejected(tmp_path: Path) -> None:
    path = fake_registry(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["models"][0]["files"][0]["sha256"] = "not-a-hash"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ModelRegistryError, match="sha256"):
        load_registry(path)


def test_verify_registry_returns_all_states() -> None:
    registry = load_registry(REGISTRY)
    states = verify_registry(registry)
    assert [state.entry.id for state in states] == [entry.id for entry in registry.models]
    assert states[0].status == "installed"


def test_format_size() -> None:
    assert format_size(512) == "512 B"
    assert format_size(214_069_684).endswith("MiB")
