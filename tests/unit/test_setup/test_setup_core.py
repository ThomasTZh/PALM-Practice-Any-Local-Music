"""Unit coverage for setup checks, downloads, models and environments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from basseparate.config import RuntimePaths
from basseparate.model_registry import load_registry
from basseparate.setup.checks import system_checks
from basseparate.setup.download import download_verified
from basseparate.setup.environments import create_environment
from basseparate.setup.errors import DownloadError, SetupCancelled
from basseparate.setup.models import install_model
from basseparate.setup.service import SetupService
from basseparate.setup.state import SetupStateStore
from basseparate.setup.tools import install_tools, tools_status

PAYLOAD = b"fake model bytes"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def make_runtime(tmp_path: Path) -> RuntimePaths:
    app = tmp_path / "app"
    data = tmp_path / "data"
    (app / "analysis").mkdir(parents=True)
    (app / "scripts").mkdir(parents=True)
    return RuntimePaths.from_environment(mode="packaged", app_root=app, data_root=data)


def write_registry(runtime: RuntimePaths, *, files: int = 1) -> None:
    entries = []
    for index in range(files):
        name = f"model-{index}.ckpt"
        entries.append(
            {
                "id": "fake-model" if index == 0 else f"fake-model-{index}",
                "name": f"Fake {index}",
                "engine": "msst",
                "engine_command": "echo",
                "labels": ["bass", "other"],
                "sample_rate": 44100,
                "size_bytes": len(PAYLOAD),
                "source_url": "https://example.invalid/model",
                "license": "test licence",
                "install_dir": "models/fake",
                "files": [
                    {
                        "role": "checkpoint",
                        "name": name,
                        "url": f"https://example.invalid/{name}",
                        "size_bytes": len(PAYLOAD),
                        "sha256": PAYLOAD_SHA,
                    }
                ],
            }
        )
    (runtime.registry_path).write_text(
        json.dumps({"schema_version": 2, "models": entries}), encoding="utf-8"
    )


def fake_fetch(mapping: dict[str, bytes]):
    def fetch(url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(mapping[url])

    return fetch


def test_download_stages_verifies_and_publishes(tmp_path: Path) -> None:
    destination = tmp_path / "artifact.bin"
    fetch = fake_fetch({"https://example.invalid/a": PAYLOAD})
    download_verified(
        "https://example.invalid/a",
        destination,
        size_bytes=len(PAYLOAD),
        sha256=PAYLOAD_SHA,
        fetch=fetch,
    )
    assert destination.read_bytes() == PAYLOAD
    assert not destination.with_name(destination.name + ".part").exists()


def test_download_rejects_bad_checksum_and_cleans_part(tmp_path: Path) -> None:
    destination = tmp_path / "artifact.bin"
    fetch = fake_fetch({"https://example.invalid/a": b"x" * len(PAYLOAD)})
    with pytest.raises(DownloadError, match="sha256 mismatch"):
        download_verified(
            "https://example.invalid/a",
            destination,
            size_bytes=len(PAYLOAD),
            sha256=PAYLOAD_SHA,
            fetch=fetch,
        )
    assert not destination.exists()
    assert not destination.with_name(destination.name + ".part").exists()


def test_download_cancel_removes_part(tmp_path: Path) -> None:
    destination = tmp_path / "artifact.bin"
    with pytest.raises(SetupCancelled):
        download_verified(
            "https://example.invalid/a",
            destination,
            size_bytes=len(PAYLOAD),
            sha256=PAYLOAD_SHA,
            fetch=fake_fetch({"https://example.invalid/a": PAYLOAD}),
            cancel=lambda: True,
        )
    assert not destination.exists()


def test_checks_report_disk_and_ffmpeg_without_network(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    checks = system_checks(
        runtime,
        disk_probe=lambda _root: type("Usage", (), {"free": 10 * 1024**3})(),
        which=lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None,
    )
    assert checks["disk"]["ok"] is True
    assert checks["ffmpeg"]["ok"] is True
    assert checks["glibc"]["ok"] is True


def test_model_install_is_atomic_and_idempotent(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    write_registry(runtime)
    registry = load_registry(runtime.registry_path)
    entry = registry.get("fake-model")
    fetch = fake_fetch({"https://example.invalid/model-0.ckpt": PAYLOAD})
    state = install_model(entry, runtime=runtime, fetch=fetch)
    assert state.installed
    target = runtime.models_root / "models/fake/model-0.ckpt"
    assert target.read_bytes() == PAYLOAD
    assert not list((runtime.models_root / "models").glob(".fake*"))

    def no_fetch(url: str, destination: Path) -> None:
        raise AssertionError("installed model must not download")

    assert install_model(entry, runtime=runtime, fetch=no_fetch).installed


def test_model_install_checksum_failure_leaves_nothing(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    write_registry(runtime)
    entry = load_registry(runtime.registry_path).get("fake-model")
    with pytest.raises(DownloadError):
        install_model(
            entry,
            runtime=runtime,
            fetch=fake_fetch({"https://example.invalid/model-0.ckpt": b"bad"}),
        )
    assert not (runtime.models_root / "models/fake").exists()


def test_model_install_retry_after_failure(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    write_registry(runtime)
    entry = load_registry(runtime.registry_path).get("fake-model")
    attempts = {"count": 0}

    def flaky(url: str, destination: Path) -> None:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise DownloadError("network unavailable")
        destination.write_bytes(PAYLOAD)

    with pytest.raises(DownloadError):
        install_model(entry, runtime=runtime, fetch=flaky)
    assert install_model(entry, runtime=runtime, fetch=flaky).installed
    assert attempts["count"] == 2


def test_environment_uses_uv_project_environment_under_data_root(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    calls: list[tuple[list[str], dict[str, str], Path]] = []

    def run_uv(command: list[str], env: dict[str, str], cwd: Path) -> None:
        calls.append((command, env, cwd))
        target = Path(env["UV_PROJECT_ENVIRONMENT"])
        (target / "bin").mkdir(parents=True)
        (target / "bin" / "python").write_text("python", encoding="utf-8")

    result = create_environment("cpu", runtime=runtime, run_uv=run_uv)
    assert result["installed"] is True
    command, env, cwd = calls[0]
    assert command[0] == str(runtime.uv)
    assert "--offline" in command
    assert Path(env["UV_PROJECT_ENVIRONMENT"]).is_relative_to(runtime.data_root)
    assert Path(env["UV_PROJECT_ENVIRONMENT"]).name.startswith(".cpu.staging-")
    assert Path(env["UV_CACHE_DIR"]).is_relative_to(runtime.data_root)
    assert cwd == runtime.analysis_dir.parent / "analysis-models"
    assert not list((runtime.data_root / "environments").glob(".cpu.staging-*"))


def test_environment_failure_and_cancel_remove_staging(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    seen: list[Path] = []

    def fail_uv(command: list[str], env: dict[str, str], cwd: Path) -> None:
        seen.append(Path(env["UV_PROJECT_ENVIRONMENT"]))
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError, match="disk full"):
        create_environment("cuda", runtime=runtime, run_uv=fail_uv)
    assert seen and not seen[0].exists()
    assert not list((runtime.data_root / "environments").glob(".cuda.staging-*"))
    with pytest.raises(SetupCancelled):
        create_environment("cpu", runtime=runtime, run_uv=fail_uv, cancel=lambda: True)
    assert not list((runtime.data_root / "environments").glob(".cpu.staging-*"))


def test_tools_accept_an_injected_installer_and_status_is_local(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)

    def installer(active: RuntimePaths, progress, cancel) -> None:
        (active.tools_root / "sv/squashfs-root/usr/bin").mkdir(parents=True)
        (active.tools_root / "sv/squashfs-root/usr/bin/piper-vamp-simple-server").write_text("p")
        (active.tools_root / "vamp-plugins").mkdir(parents=True)
        (active.tools_root / "vamp-plugins/qm-vamp-plugins.so").write_text("p")

    result = install_tools(runtime, installer=installer)
    assert all(item["installed"] for item in result.values())
    assert all(item["installed"] for item in tools_status(runtime).values())


def test_setup_state_persists_skip_under_data_root(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    store = SetupStateStore(runtime)
    assert store.load() == {}
    store.skip(True)
    assert store.path.is_relative_to(runtime.data_root)
    assert store.load()["skipped"] is True


def test_setup_service_reports_models_environments_and_readiness(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    write_registry(runtime)
    service = SetupService(
        runtime,
        which=lambda name: None,
        disk_probe=lambda _root: type("Usage", (), {"free": 10 * 1024**3})(),
    )
    status = service.status()
    assert status["mode"] == "packaged"
    assert status["roots"]["models_root"] == str(runtime.data_root)
    assert set(status["environments"]) == {"cpu", "cuda"}
    assert [model["id"] for model in status["models"]] == ["fake-model"]
    assert status["readiness"]["requires_model_choice"] is True
    assert status["readiness"]["ready"] is False
    assert status["skipped"] is False


def test_environment_cancel_after_uv_removes_staging(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    state = {"cancelled": False}

    def run_uv(command: list[str], env: dict[str, str], cwd: Path) -> None:
        target = Path(env["UV_PROJECT_ENVIRONMENT"])
        (target / "bin").mkdir(parents=True)
        (target / "bin" / "python").write_text("python", encoding="utf-8")
        state["cancelled"] = True

    with pytest.raises(SetupCancelled):
        create_environment("cpu", runtime=runtime, run_uv=run_uv, cancel=lambda: state["cancelled"])
    assert not (runtime.data_root / "environments/cpu").exists()
    assert not list((runtime.data_root / "environments").glob(".cpu.staging-*"))


def test_model_install_cancel_after_fetch_cleans_staging(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    write_registry(runtime)
    entry = load_registry(runtime.registry_path).get("fake-model")
    state = {"cancelled": False}

    def fetch(url: str, destination: Path) -> None:
        destination.write_bytes(PAYLOAD)
        state["cancelled"] = True

    with pytest.raises(SetupCancelled):
        install_model(entry, runtime=runtime, fetch=fetch, cancel=lambda: state["cancelled"])
    assert not (runtime.models_root / "models/fake").exists()
    assert not list((runtime.models_root / "models").glob(".fake-model.staging-*"))


def test_download_resumes_an_existing_part(tmp_path: Path) -> None:
    destination = tmp_path / "artifact.bin"
    part = destination.with_name(destination.name + ".part")
    part.write_bytes(PAYLOAD[:4])
    calls: list[int] = []

    def resume(url: str, target: Path) -> None:
        offset = target.stat().st_size
        calls.append(offset)
        target.write_bytes(PAYLOAD[:offset] + PAYLOAD[offset:])

    download_verified(
        "https://example.invalid/a",
        destination,
        size_bytes=len(PAYLOAD),
        sha256=PAYLOAD_SHA,
        fetch=resume,
    )
    assert calls == [4]
    assert destination.read_bytes() == PAYLOAD


def test_checks_report_low_disk_as_not_ready(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)
    checks = system_checks(
        runtime,
        disk_probe=lambda _root: type("Usage", (), {"free": 1024})(),
        which=lambda _name: None,
    )
    assert checks["disk"]["ok"] is False
    assert checks["ffmpeg"]["ok"] is False
