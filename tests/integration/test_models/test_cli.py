"""Model CLI and doctor integration with local fake files; no real downloads."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

from fastapi.testclient import TestClient

from basseparate.config import Settings
from basseparate.doctor import DoctorLayout, diagnose
from basseparate.model_registry import clear_digest_cache

ROOT = Path(__file__).resolve().parents[3]
MODEL_BYTES = b"checkpoint bytes"
CONFIG_BYTES = b"config bytes"


def load_models_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "models_script_integration", ROOT / "scripts" / "models.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_registry(tmp_path: Path) -> Path:
    entry = {
        "id": "fake-model",
        "name": "Fake model",
        "engine": "msst",
        "engine_command": "echo",
        "labels": ["bass", "other"],
        "sample_rate": 44100,
        "size_bytes": len(MODEL_BYTES) + len(CONFIG_BYTES),
        "source_url": "https://example.invalid/model",
        "license": "test licence",
        "install_dir": "models/fake-model",
        "files": [
            {
                "role": "checkpoint",
                "name": "model.ckpt",
                "url": "https://example.invalid/model.ckpt",
                "size_bytes": len(MODEL_BYTES),
                "sha256": hashlib.sha256(MODEL_BYTES).hexdigest(),
            },
            {
                "role": "config",
                "name": "model.yaml",
                "url": "https://example.invalid/model.yaml",
                "size_bytes": len(CONFIG_BYTES),
                "sha256": hashlib.sha256(CONFIG_BYTES).hexdigest(),
            },
        ],
    }
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"schema_version": 2, "models": [entry]}), encoding="utf-8")
    return path


def fake_download(mapping: dict[str, bytes]):
    def download(url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(mapping[url])

    return download


def test_list_reports_all_fields_and_uses_no_network(tmp_path: Path, monkeypatch, capsys) -> None:
    script = load_models_script()

    def offline(*args, **kwargs):
        raise AssertionError("list must not use the network")

    monkeypatch.setattr(script, "download_file", offline)
    registry = make_registry(tmp_path)
    code = script.main(["--registry", str(registry), "--root", str(tmp_path / "root"), "list"])
    output = capsys.readouterr().out
    assert code == 0
    assert "fake-model" in output
    assert "missing" in output
    assert "2 stems" in output or "2 stems" in output.replace("  ", " ")
    assert "msst" in output
    assert "make models-install ID=fake-model" in output
    assert "bass" in output and "other" in output
    assert "no network" in output


def test_install_is_atomic_verified_and_idempotent(tmp_path: Path, monkeypatch, capsys) -> None:
    script = load_models_script()
    registry = make_registry(tmp_path)
    root = tmp_path / "root"
    monkeypatch.setattr(
        script,
        "download_file",
        fake_download(
            {
                "https://example.invalid/model.ckpt": MODEL_BYTES,
                "https://example.invalid/model.yaml": CONFIG_BYTES,
            }
        ),
    )
    assert (
        script.main(["--registry", str(registry), "--root", str(root), "install", "fake-model"])
        == 0
    )
    target = root / "models" / "fake-model"
    assert (target / "model.ckpt").read_bytes() == MODEL_BYTES
    assert (target / "model.yaml").read_bytes() == CONFIG_BYTES
    assert not list(target.glob("*.part"))

    def no_download(url: str, destination: Path) -> None:
        raise AssertionError("already installed must not download")

    monkeypatch.setattr(script, "download_file", no_download)
    assert (
        script.main(["--registry", str(registry), "--root", str(root), "install", "fake-model"])
        == 0
    )


def test_hash_mismatch_short_file_and_offline_exit_nonzero_with_nothing_installed(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    script = load_models_script()
    registry = make_registry(tmp_path)
    for bad in (
        {
            "https://example.invalid/model.ckpt": b"wrong bytes",
            "https://example.invalid/model.yaml": CONFIG_BYTES,
        },
        {
            "https://example.invalid/model.ckpt": MODEL_BYTES[:-1],
            "https://example.invalid/model.yaml": CONFIG_BYTES,
        },
    ):
        root = tmp_path / ("root-" + str(abs(hash(tuple(bad.values())))))
        monkeypatch.setattr(script, "download_file", fake_download(bad))
        assert (
            script.main(["--registry", str(registry), "--root", str(root), "install", "fake-model"])
            == 1
        )
        assert not (root / "models" / "fake-model").exists()

    root = tmp_path / "root-offline"

    def offline(url: str, destination: Path) -> None:
        raise script.InstallError("network unavailable")

    monkeypatch.setattr(script, "download_file", offline)
    assert (
        script.main(["--registry", str(registry), "--root", str(root), "install", "fake-model"])
        == 1
    )
    assert not (root / "models" / "fake-model").exists()
    assert "network unavailable" in capsys.readouterr().err


def test_verify_uses_no_network_and_reports_hash_mismatch(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    script = load_models_script()
    registry = make_registry(tmp_path)
    root = tmp_path / "root"
    script.install_model(
        script.load_registry(registry).get("fake-model"),
        root=root,
        fetch=fake_download(
            {
                "https://example.invalid/model.ckpt": MODEL_BYTES,
                "https://example.invalid/model.yaml": CONFIG_BYTES,
            }
        ),
    )

    def offline(*args, **kwargs):
        raise AssertionError("verify must not use the network")

    monkeypatch.setattr(script, "download_file", offline)
    assert script.main(["--registry", str(registry), "--root", str(root), "verify"]) == 0
    clear_digest_cache()
    (root / "models" / "fake-model" / "model.ckpt").write_bytes(b"corrupt")
    clear_digest_cache()
    assert script.main(["--registry", str(registry), "--root", str(root), "verify"]) == 1
    assert "hash mismatch" in capsys.readouterr().err.lower()


def test_real_registry_list_and_verify_from_the_shipped_file(monkeypatch, capsys) -> None:
    script = load_models_script()

    def offline(*args, **kwargs):
        raise AssertionError("list/verify must not use the network")

    monkeypatch.setattr(script, "download_file", offline)
    assert script.main(["list"]) == 0
    output = capsys.readouterr().out
    for model_id in ("htdemucs_ft", "scnet-xl-ihf", "bs-roformer-sw"):
        assert model_id in output
    assert "installed" in output
    assert "missing" in output


def test_doctor_reports_per_model_state(tmp_path: Path) -> None:
    # A fake repository with a corrupt declared file must show hash-mismatch.
    root = tmp_path / "repo"
    (root / "analysis").mkdir(parents=True)
    (root / "models" / "fake-model").mkdir(parents=True)
    registry = make_registry(tmp_path)
    (root / "analysis" / "models.json").write_bytes(registry.read_bytes())
    (root / "models" / "fake-model" / "model.ckpt").write_bytes(b"corrupt")
    (root / "models" / "fake-model" / "model.yaml").write_bytes(CONFIG_BYTES)
    clear_digest_cache()
    report = diagnose(
        DoctorLayout(root=root, data_root=tmp_path / "data"),
        tool_probe=lambda *args: (0, "test"),
        gpu_probe=lambda: (False, "no gpu"),
    )
    models = {model["id"]: model for model in report.to_dict()["models"]}  # type: ignore[index]
    assert models["fake-model"]["status"] == "hash-mismatch"


def test_api_doctor_lists_each_declared_model(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "web")
    from basseparate.app import create_app

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/doctor")
    assert response.status_code == 200
    payload = response.json()
    models = {model["id"]: model for model in payload["models"]}
    assert set(models) == {"htdemucs_ft", "scnet-xl-ihf", "bs-roformer-sw"}
    assert models["htdemucs_ft"]["status"] == "installed"
    assert models["scnet-xl-ihf"]["status"] in {"missing", "installed", "hash-mismatch"}
    assert all("labels" in model for model in models.values())
