"""Windows portable ZIP packaging checks (no Windows execution required)."""

from __future__ import annotations

import importlib.util
import os
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
    assert any(name.endswith("/licenses/third_party/manifest.json") for name in lower)
    assert not any(
        ("/ffmpeg" in name or "/sonic-annotator" in name) and "/licenses/" not in name
        for name in lower
    )
    root_forbidden = {"models", "tools", "environments", "cache", "tests", "storage"}
    assert not any(
        len(Path(name).parts) >= 2 and Path(name).parts[1] in root_forbidden for name in lower
    )


def test_native_launcher_builds_and_sets_packaged_environment() -> None:
    source = (ROOT / "packaging/windows/palm_launcher.c").read_text()
    script = (ROOT / "packaging/windows/build_launcher.ps1").read_text()
    packager = (ROOT / "scripts/package_windows.py").read_text()
    assert "PALM_MODE" in source and "packaged" in source
    assert "PALM_APP_ROOT" in source
    assert "PALM_DATA_DIR" in source
    assert "PYTHONPATH" in source
    assert "PYTHONUTF8" in source
    assert "pythonw.exe" in source
    assert "WaitForSingleObject" in source
    assert "exit code %lu" in source
    assert "palm.cmd --help" in source
    assert "palm_launcher.c" in script and "$Out" in script and "SUBSYSTEM:WINDOWS" in script
    assert "build_launcher" in packager and "palm_launcher.c" in packager
    binary = (ROOT / "packaging/windows/PALM.exe").read_bytes()
    assert binary[:2] == b"MZ"
    assert len(binary) > 4096


def test_inno_installer_contract() -> None:
    script = (ROOT / "packaging/windows/PALM.iss").read_text()
    packager = (ROOT / "scripts/package_windows.py").read_text()
    for value in (
        "PrivilegesRequired=lowest",
        "DefaultDirName={localappdata}\\Programs\\PALM",
        "AppId={{",
        "{userprograms}\\PALM",
        "{userdesktop}\\PALM",
        "UninstallDisplayIcon={app}\\PALM.exe",
        "CloseApplications=yes",
        "UninstallSilent",
        "MB_DEFBUTTON1",
        "DeleteData",
        "{localappdata}\\palm",
    ):
        assert value in script, value
    assert "build_installer" in packager and "ISCC.exe" in packager and "PALM.iss" in packager
    assert "PALM-{version_value}-windows-x86_64-installer.exe" in packager
    assert not any(
        path.name.endswith("-installer.exe")
        for path in (ROOT / "packaging").rglob("*")
        if path.is_file()
    )


@pytest.mark.skipif(sys.platform != "win32", reason="native installer test requires Windows")
def test_native_installer_install_upgrade_uninstall(tmp_path: Path) -> None:
    installer = next(
        iter(sorted((ROOT / "dist").glob("PALM-*-windows-x86_64-installer.exe"))), None
    )
    if installer is None:
        pytest.skip("installer has not been built")
    app_dir = tmp_path / "PALM app"
    data_dir = Path(os.environ["LOCALAPPDATA"]) / "palm"
    data_dir.mkdir(parents=True, exist_ok=True)
    keep = data_dir / "projects" / "keep.txt"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("keep")
    base = [
        str(installer),
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        f"/DIR={app_dir}",
    ]
    assert subprocess.run(base, check=False).returncode == 0
    assert (app_dir / "PALM.exe").is_file()
    assert (app_dir / "unins000.exe").is_file()
    start_menu = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/PALM.lnk"
    assert start_menu.exists()
    marker = app_dir / "upgrade-marker.txt"
    marker.write_text("old")
    assert subprocess.run(base, check=False).returncode == 0
    assert (app_dir / "PALM.exe").is_file()
    assert marker.exists()
    assert keep.is_file()
    marker.unlink()
    uninstaller = app_dir / "unins000.exe"
    assert (
        subprocess.run(
            [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=False
        ).returncode
        == 0
    )
    assert not app_dir.exists()
    assert keep.is_file()
