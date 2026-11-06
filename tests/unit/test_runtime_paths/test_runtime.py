"""Runtime paths: source checkout versus read-only packaged app root."""

from __future__ import annotations

from pathlib import Path

import pytest

from basseparate.config import (
    REPO_ROOT,
    RuntimePathError,
    RuntimePaths,
    Settings,
    default_web_dir,
    runtime_paths,
)


@pytest.fixture(autouse=True)
def clear_palm_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("PALM_MODE", "PALM_APP_ROOT", "PALM_DATA_DIR", "BASSEPARATE_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)


def test_source_mode_keeps_the_checkout_layout() -> None:
    runtime = runtime_paths()
    assert runtime.mode == "source"
    assert runtime.app_root == REPO_ROOT
    assert runtime.web_dir == REPO_ROOT / "web" / "dist"
    assert runtime.analysis_dir == REPO_ROOT / "analysis"
    assert runtime.models_root == REPO_ROOT
    assert runtime.tools_root == REPO_ROOT / "storage" / "tools"
    assert runtime.environments_root == REPO_ROOT
    assert runtime.uv.name == "uv"
    assert runtime.demucs_python == REPO_ROOT / "analysis/.venv/bin/python"
    assert runtime.msst_python == REPO_ROOT / "analysis-models/.venv/bin/python"
    assert runtime.demucs_worker == REPO_ROOT / "analysis/separate_track.py"
    assert runtime.msst_worker == REPO_ROOT / "analysis/separate_msst.py"
    assert runtime.worker("demucs") == runtime.demucs_worker
    assert runtime.registry_path == REPO_ROOT / "analysis/models.json"
    assert runtime.checkpoint_manifest == REPO_ROOT / "analysis/checkpoints.json"
    assert runtime.logs_root.is_relative_to(runtime.data_root)
    assert runtime.setup_state.is_relative_to(runtime.data_root)


def test_source_mode_settings_use_the_resolver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PALM_DATA_DIR", str(tmp_path / "data"))
    settings = Settings()
    assert settings.data_dir == tmp_path / "data"
    assert settings.web_dir == REPO_ROOT / "web" / "dist"
    assert default_web_dir() == REPO_ROOT / "web" / "dist"


def test_packaged_mode_puts_writable_assets_under_data_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = tmp_path / "app"
    data = tmp_path / "data"
    app.mkdir()
    data.mkdir()
    monkeypatch.setenv("PALM_MODE", "packaged")
    monkeypatch.setenv("PALM_APP_ROOT", str(app))
    monkeypatch.setenv("PALM_DATA_DIR", str(data))

    runtime = runtime_paths()
    assert runtime.mode == "packaged"
    assert runtime.app_root == app
    assert runtime.data_root == data
    assert runtime.web_dir == app / "web" / "dist"
    assert runtime.analysis_dir == app / "analysis"
    assert runtime.models_root == data
    assert runtime.tools_root == data / "tools"
    assert runtime.environments_root == data / "environments"
    assert runtime.uv == app / "bin" / "uv"
    assert runtime.demucs_python == data / "environments/demucs/bin/python"
    assert runtime.msst_python == data / "environments/cpu/bin/python"
    (data / "environments/cpu/bin").mkdir(parents=True)
    (data / "environments/cpu/bin/python").write_text("cpu")
    assert runtime.msst_python == data / "environments/cpu/bin/python"
    (data / "environments/cuda/bin").mkdir(parents=True)
    (data / "environments/cuda/bin/python").write_text("cuda")
    assert runtime.msst_python == data / "environments/cuda/bin/python"
    assert runtime.worker("demucs") == app / "analysis/separate_track.py"
    assert runtime.worker("msst") == app / "analysis/separate_msst.py"
    assert runtime.registry_path == app / "analysis/models.json"
    assert runtime.checkpoint_manifest == app / "analysis/checkpoints.json"
    assert runtime.setup_state.is_relative_to(data)
    assert runtime.logs_root.is_relative_to(data)
    assert runtime.caches_root.is_relative_to(data)

    settings = Settings()
    assert settings.data_dir == data
    assert settings.web_dir == app / "web" / "dist"


def test_packaged_mode_rejects_writes_outside_data_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = tmp_path / "app"
    data = tmp_path / "data"
    app.mkdir()
    data.mkdir()
    monkeypatch.setenv("PALM_MODE", "packaged")
    monkeypatch.setenv("PALM_APP_ROOT", str(app))
    monkeypatch.setenv("PALM_DATA_DIR", str(data))
    runtime = runtime_paths()

    logs = runtime.ensure_data_path(runtime.logs_root)
    setup_parent = runtime.ensure_data_path(runtime.setup_state)
    assert logs.is_dir()
    assert setup_parent.parent.is_dir()
    assert not (app / "logs").exists()
    assert not (app / "setup.json").exists()

    with pytest.raises(RuntimePathError):
        runtime.ensure_data_path(app / "logs")
    with pytest.raises(RuntimePathError):
        runtime.ensure_data_path(app / "setup.json")
    with pytest.raises(RuntimePathError):
        runtime.data_path("..", "outside")
    assert not (tmp_path / "outside").exists()
    assert not (app / "logs").exists()


def test_overrides_are_explicit_and_mode_is_validated(tmp_path: Path) -> None:
    app = tmp_path / "app"
    data = tmp_path / "data"
    runtime = RuntimePaths.from_environment(mode="source", app_root=app, data_root=data)
    assert runtime.app_root == app.resolve()
    assert runtime.data_root == data.resolve()
    assert runtime.models_root == app.resolve()
    assert runtime.with_data_root(tmp_path / "other").data_root == (tmp_path / "other").resolve()
    with pytest.raises(RuntimePathError):
        RuntimePaths.from_environment(mode="bundle")
    with pytest.raises(RuntimePathError):
        runtime.worker("not-an-engine")
    with pytest.raises(RuntimePathError):
        runtime.environment_python("not-an-engine")


def test_doctor_layout_uses_the_same_resolver(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from basseparate.doctor import DoctorLayout

    app = tmp_path / "app"
    data = tmp_path / "data"
    app.mkdir()
    data.mkdir()
    monkeypatch.setenv("PALM_MODE", "packaged")
    monkeypatch.setenv("PALM_APP_ROOT", str(app))
    monkeypatch.setenv("PALM_DATA_DIR", str(data))
    runtime = runtime_paths()
    layout = DoctorLayout.default(data)
    assert layout.runtime == runtime
    assert layout.app_root == app
    assert layout.model_dir == data / "models" / "htdemucs_ft"
    assert layout.vamp_plugins == data / "tools" / "vamp-plugins"
    assert layout.analysis_python == data / "environments" / "demucs" / "bin" / "python"
    assert layout.exports == data / "exports"
    assert DoctorLayout.from_runtime(runtime) == layout


def test_packaged_bundled_interpreter_and_environment_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sys

    from basseparate.setup.environments import environment_spec

    app = tmp_path / "app"
    data = tmp_path / "data"
    python = app / "python" / "bin" / "python3.11"
    python.parent.mkdir(parents=True)
    python.write_text("python", encoding="utf-8")
    (app / "analysis" / "envs" / "cpu").mkdir(parents=True)
    (app / "analysis" / "envs" / "cuda").mkdir(parents=True)
    monkeypatch.setenv("PALM_MODE", "packaged")
    monkeypatch.setenv("PALM_APP_ROOT", str(app))
    monkeypatch.setenv("PALM_DATA_DIR", str(data))

    runtime = runtime_paths()
    assert runtime.bundled_python == python
    assert runtime.python == python
    assert runtime.interpreter == python
    spec = environment_spec("cpu", runtime)
    assert spec.python == python
    assert spec.project_dir == app / "analysis" / "envs" / "cpu"

    delivered = app / "python" / "bin" / "python3"
    python.unlink()
    delivered.write_text("python", encoding="utf-8")
    assert runtime.bundled_python == delivered
    delivered.unlink()
    fallback = app / "bin" / "python3.11"
    fallback.parent.mkdir(parents=True)
    fallback.write_text("python", encoding="utf-8")
    assert runtime.bundled_python == fallback

    monkeypatch.delenv("PALM_MODE")
    source = runtime_paths()
    assert source.bundled_python == Path(sys.executable)
