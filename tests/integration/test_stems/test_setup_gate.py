"""Separation preflight gives setup guidance instead of launch-time errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from basseparate.config import RuntimePaths
from basseparate.model_registry import ModelEntry, ModelFile
from basseparate.stems import (
    SeparationSetupError,
    require_model_installed,
    separation_setup_problem,
)


def _model(engine: str = "msst") -> ModelEntry:
    return ModelEntry(
        id="test-model",
        name="Test model",
        engine=engine,
        engine_command="unused",
        labels=("bass", "drums", "other", "vocals"),
        sample_rate=48_000,
        size_bytes=12,
        source_url="https://example.invalid/model",
        license="test",
        install_dir="models/test-model",
        files=(
            ModelFile(
                role="checkpoint",
                name="weights.ckpt",
                url="https://example.invalid/weights.ckpt",
                size_bytes=10,
                sha256="a" * 64,
            ),
        ),
    )


def _runtime(tmp_path: Path) -> RuntimePaths:
    app = tmp_path / "app"
    data = tmp_path / "data"
    app.mkdir()
    return RuntimePaths.from_environment(mode="packaged", app_root=app, data_root=data)


def _install_runtime(runtime: RuntimePaths, engine: str = "msst") -> None:
    worker = runtime.worker(engine)
    worker.parent.mkdir(parents=True, exist_ok=True)
    worker.write_text("# fake worker\n")
    python = runtime.msst_python
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_bytes(b"python")
    python.chmod(0o755)
    tools = runtime.tools_root / "ffmpeg"
    tools.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg", "ffprobe"):
        path = tools / name
        path.write_bytes(b"tool")
        path.chmod(0o755)


def test_missing_environment_names_setup_not_make(tmp_path: Path) -> None:
    problem = separation_setup_problem(_runtime(tmp_path), _model())
    assert problem is not None
    assert "CPU environment" in problem
    assert "Open Setup" in problem
    assert "make " not in problem


def test_missing_model_is_actionable(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _install_runtime(runtime)
    with pytest.raises(SeparationSetupError) as caught:
        require_model_installed(_model())
    message = str(caught.value)
    assert "Open Setup" in message
    assert "make " not in message


def test_packaged_runtime_ready_uses_cpu_environment_and_tools(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _install_runtime(runtime)
    assert separation_setup_problem(runtime, _model()) is None


def test_missing_media_tools_is_actionable(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _install_runtime(runtime)
    (runtime.tools_root / "ffmpeg" / "ffprobe").unlink()
    problem = separation_setup_problem(runtime, _model())
    assert problem is not None
    assert "FFmpeg and FFprobe" in problem and "Open Setup" in problem


def test_demucs_falls_back_to_managed_cpu_environment(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _install_runtime(runtime, "demucs")
    bundle = runtime.models_root / "models" / "test-model"
    bundle.mkdir(parents=True)
    entry = _model("demucs")
    # demucs_python is not created by setup; the managed environment is the
    # CPU one that the setup/doctor path actually installs.
    assert not runtime.demucs_python.is_file()
    assert separation_setup_problem(runtime, entry) is None


def test_separate_route_returns_actionable_409_before_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.testclient import TestClient

    from basseparate import stems
    from basseparate.app import create_app
    from basseparate.config import Settings

    root = Path(__file__).resolve().parents[3]
    source = root / "tests" / "fixtures" / "audio" / "tone_440hz.wav"
    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "webdist")
    with TestClient(create_app(settings)) as client:
        imported = client.post("/api/imports", json={"path": str(source)})
        assert imported.status_code == 201, imported.text
        project_id = imported.json()["id"]
        entry = _model()
        monkeypatch.setattr(stems, "resolve_model", lambda _model_id: entry)
        monkeypatch.setattr(stems, "require_model_installed", lambda _entry: None)
        monkeypatch.setattr(stems, "runtime_paths", lambda: _runtime(tmp_path))
        response = client.post(
            "/api/separate",
            json={"project_id": project_id, "model_id": "test-model"},
        )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "Open Setup" in detail and "CPU environment" in detail
    assert "make " not in detail
