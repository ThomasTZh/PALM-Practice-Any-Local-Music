"""Windows portable ZIP packaging checks (no Windows execution required)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_script():  # type: ignore[no-untyped-def]
    path = ROOT / "scripts" / "package_windows.py"
    spec = importlib.util.spec_from_file_location("package_windows", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_help_and_manifest() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/package_windows.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Windows x64 portable" in result.stdout
    manifest = (ROOT / "packaging/windows/build-manifest.toml").read_text()
    assert "python-build-standalone" in manifest
    assert "x86_64-pc-windows-msvc" in manifest
    assert "sha256" in manifest


def test_windows_launcher_and_package_layout(tmp_path: Path) -> None:
    command = (ROOT / "palm.cmd").read_bytes().decode()
    assert "%~dp0python\\python.exe" in command
    assert "PALM_MODE=packaged" in command
    assert "PYTHONUTF8=1" in command
    assert "%*" in command
    assert "[project]" in (ROOT / "pyproject.toml").read_text()


def test_check_zip_accepts_required_content(tmp_path: Path) -> None:
    module = load_script()
    archive = tmp_path / "PALM-test-windows-x86_64.zip"
    required = [
        "palm-0.1.0-dev-windows-x86_64/palm.cmd",
        "palm-0.1.0-dev-windows-x86_64/python/python.exe",
        "palm-0.1.0-dev-windows-x86_64/bin/uv.exe",
        "palm-0.1.0-dev-windows-x86_64/web/dist/index.html",
        "palm-0.1.0-dev-windows-x86_64/analysis/models.json",
        "palm-0.1.0-dev-windows-x86_64/analysis/checkpoints.json",
        "palm-0.1.0-dev-windows-x86_64/analysis/separate_track.py",
        "palm-0.1.0-dev-windows-x86_64/analysis/separate_msst.py",
        "palm-0.1.0-dev-windows-x86_64/analysis/envs/cpu-windows/uv.lock",
        "palm-0.1.0-dev-windows-x86_64/analysis/envs/msst-windows/uv.lock",
        "palm-0.1.0-dev-windows-x86_64/analysis/envs/cpu-windows/pyproject.toml",
        "palm-0.1.0-dev-windows-x86_64/licenses/LICENSE",
        "palm-0.1.0-dev-windows-x86_64/licenses/third_party/manifest.json",
        "palm-0.1.0-dev-windows-x86_64/install.json",
        "palm-0.1.0-dev-windows-x86_64/PALM.exe",
        "palm-0.1.0-dev-windows-x86_64/updaters/update_helper.py",
        "palm-0.1.0-dev-windows-x86_64/updaters/uninstall_helper.py",
        "palm-0.1.0-dev-windows-x86_64/runtime-requirements.txt",
    ]
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in required:
            bundle.writestr(name, "x")
    assert module.check_zip(archive) == 0
    with zipfile.ZipFile(archive, "a") as bundle:
        bundle.writestr("palm-0.1.0-dev-windows-x86_64/models/weight.bin", "x")
    with pytest.raises(module.PackageError):
        module.check_zip(archive)


def test_built_zip_has_only_allowed_payload_when_present() -> None:
    zips = sorted((ROOT / "dist").glob("PALM-*-windows-x86_64.zip"))
    if not zips:
        pytest.skip("Windows ZIP has not been built")
    module = load_script()
    assert module.check_zip(zips[-1]) == 0
    with zipfile.ZipFile(zips[-1]) as archive:
        names = archive.namelist()
        install = next(name for name in names if name.endswith("/install.json"))
        import json

        payload = json.loads(archive.read(install))
        assert payload["channel"] == "windows-x86_64"
        assert payload["assets"]["windows-x86_64"]["name"].endswith(".zip")
    lower = [name.lower() for name in names]
    assert any(name.endswith("palm.cmd") for name in lower)
    assert any(name.endswith("python/python.exe") for name in lower)
    assert any(name.endswith("bin/uv.exe") for name in lower)
    assert any(name.endswith("web/dist/index.html") for name in lower)
    assert any(name.endswith("analysis/envs/cpu-windows/uv.lock") for name in lower)
    assert any(name.endswith("/palm.exe") for name in lower)
    assert any(name.endswith("/install.json") for name in lower)
    assert any(name.endswith("/updaters/update_helper.py") for name in lower)
    assert any(name.endswith("/licenses/third_party/manifest.json") for name in lower)
    assert not any(
        ("/ffmpeg" in name or "/sonic-annotator" in name) and "/licenses/" not in name
        for name in lower
    )
    root_forbidden = {"models", "tools", "environments", "cache", "tests", "storage"}
    assert not any(
        len(Path(name).parts) >= 2 and Path(name).parts[1] in root_forbidden for name in lower
    )
