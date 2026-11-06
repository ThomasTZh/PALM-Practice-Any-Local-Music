"""Installer unit tests with injected fetchers and local fake files."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from basseparate.model_registry import clear_digest_cache, load_registry, verify_model

ROOT = Path(__file__).resolve().parents[3]


def load_models_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "models_script_unit", ROOT / "scripts" / "models.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIRST = b"checkpoint-bytes"
SECOND = b"config-bytes"


def make_registry(tmp_path: Path) -> Path:
    entry = {
        "id": "fake-model",
        "name": "Fake model",
        "engine": "msst",
        "engine_command": "echo",
        "labels": ["bass", "other"],
        "sample_rate": 44100,
        "size_bytes": len(FIRST) + len(SECOND),
        "source_url": "https://example.invalid/model",
        "license": "test",
        "install_dir": "models/fake-model",
        "files": [
            {
                "role": "checkpoint",
                "name": "model.ckpt",
                "url": "https://example.invalid/model.ckpt",
                "size_bytes": len(FIRST),
                "sha256": hashlib.sha256(FIRST).hexdigest(),
            },
            {
                "role": "config",
                "name": "model.yaml",
                "url": "https://example.invalid/model.yaml",
                "size_bytes": len(SECOND),
                "sha256": hashlib.sha256(SECOND).hexdigest(),
            },
        ],
    }
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"schema_version": 2, "models": [entry]}), encoding="utf-8")
    return path


def fetcher(mapping: dict[str, bytes], calls: list[str]):
    def fetch(url: str, destination: Path) -> None:
        calls.append(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(mapping[url])

    return fetch


def test_install_publishes_all_files_atomically_and_is_idempotent(tmp_path: Path) -> None:
    script = load_models_script()
    entry = load_registry(make_registry(tmp_path)).get("fake-model")
    root = tmp_path / "root"
    calls: list[str] = []
    fetch = fetcher(
        {
            "https://example.invalid/model.ckpt": FIRST,
            "https://example.invalid/model.yaml": SECOND,
        },
        calls,
    )
    state = script.install_model(entry, root=root, fetch=fetch)
    assert state.installed
    target = root / "models" / "fake-model"
    assert (target / "model.ckpt").read_bytes() == FIRST
    assert (target / "model.yaml").read_bytes() == SECOND
    assert not list(target.glob("*.part"))
    assert not list((root / "models").glob(".fake-model.*"))
    assert len(calls) == 2
    again = script.install_model(entry, root=root, fetch=lambda *_: pytest.fail("no fetch"))
    assert again.installed
    assert len(calls) == 2


def test_hash_mismatch_leaves_nothing_installed(tmp_path: Path) -> None:
    script = load_models_script()
    entry = load_registry(make_registry(tmp_path)).get("fake-model")
    root = tmp_path / "root"
    calls: list[str] = []
    fetch = fetcher(
        {
            "https://example.invalid/model.ckpt": b"wrong bytes",
            "https://example.invalid/model.yaml": SECOND,
        },
        calls,
    )
    with pytest.raises(script.InstallError, match="sha256|bytes"):
        script.install_model(entry, root=root, fetch=fetch)
    assert not (root / "models" / "fake-model").exists()
    assert not list((root / "models").glob(".fake-model.*")) if (root / "models").exists() else True


def test_short_file_and_second_file_failure_leave_nothing(tmp_path: Path) -> None:
    script = load_models_script()
    entry = load_registry(make_registry(tmp_path)).get("fake-model")
    root = tmp_path / "root"
    calls: list[str] = []
    fetch = fetcher(
        {
            "https://example.invalid/model.ckpt": FIRST,
            "https://example.invalid/model.yaml": SECOND[:-1],
        },
        calls,
    )
    with pytest.raises(script.InstallError):
        script.install_model(entry, root=root, fetch=fetch)
    assert not (root / "models" / "fake-model").exists()
    assert not any((root / "models").iterdir()) if (root / "models").exists() else True


def test_network_failure_leaves_nothing_installed(tmp_path: Path) -> None:
    script = load_models_script()
    entry = load_registry(make_registry(tmp_path)).get("fake-model")
    root = tmp_path / "root"

    def offline(url: str, destination: Path) -> None:
        raise script.InstallError("network unavailable")

    with pytest.raises(script.InstallError, match="network"):
        script.install_model(entry, root=root, fetch=offline)
    assert not (root / "models" / "fake-model").exists()


def test_install_replaces_an_extra_file_and_bad_previous_file(tmp_path: Path) -> None:
    script = load_models_script()
    entry = load_registry(make_registry(tmp_path)).get("fake-model")
    root = tmp_path / "root"
    target = root / "models" / "fake-model"
    target.mkdir(parents=True)
    (target / "model.ckpt").write_bytes(b"corrupt")
    (target / "surprise.bin").write_bytes(b"extra")
    clear_digest_cache()
    assert verify_model(entry, root).status == "hash-mismatch"
    calls: list[str] = []
    fetch = fetcher(
        {
            "https://example.invalid/model.ckpt": FIRST,
            "https://example.invalid/model.yaml": SECOND,
        },
        calls,
    )
    state = script.install_model(entry, root=root, fetch=fetch)
    assert state.installed
    assert (target / "model.ckpt").read_bytes() == FIRST
    assert not (target / "surprise.bin").exists()
