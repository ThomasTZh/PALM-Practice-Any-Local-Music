"""Configuration and data paths: explicit, overridable and workspace-aware."""

from __future__ import annotations

from pathlib import Path

from basseparate.config import DEFAULT_SAMPLE_RATE, Settings, default_web_dir


def test_settings_derives_and_creates_data_paths(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "appdata", web_dir=tmp_path / "dist")
    paths = settings.data_paths.ensure()
    assert paths.root == tmp_path / "appdata"
    assert paths.projects.is_dir()
    assert paths.assets.is_dir()
    assert paths.uploads.is_dir()
    assert paths.tmp.is_dir()
    assert paths.project_file("abc") == paths.projects / "abc.json"
    assert paths.asset_dir("abc") == paths.assets / "abc"


def test_default_web_dir_is_the_vite_build_output() -> None:
    assert default_web_dir().name == "dist"
    assert default_web_dir().parent.name == "web"


def test_default_sample_rate_is_a_supported_value() -> None:
    assert DEFAULT_SAMPLE_RATE in {44_100, 48_000, 88_200, 96_000}


def test_settings_are_immutable_during_use_and_ignore_unknown_env(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BASSEPARATE_DATA_DIR", str(tmp_path / "envdir"))
    settings = Settings()
    assert settings.data_dir == tmp_path / "envdir"
    assert settings.web_dir == default_web_dir()
    # The data root is not created by construction: only `ensure` touches disk.
    assert not (tmp_path / "envdir").exists()
