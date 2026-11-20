"""macOS app packaging checks (SHA/content and wrapper contract)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
EXECUTABLES = (
    "PALM.app/Contents/MacOS/palm",
    "PALM.app/Contents/Resources/app/bin/palm",
    "PALM.app/Contents/Resources/app/bin/uv",
    "PALM.app/Contents/Resources/app/python/bin/python3.11",
)


def load_script():  # type: ignore[no-untyped-def]
    path = ROOT / "scripts" / "package_macos.py"
    spec = importlib.util.spec_from_file_location("package_macos", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_help_and_pins() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/package_macos.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "macOS Apple Silicon" in result.stdout
    manifest = (ROOT / "packaging/macos/build-manifest.toml").read_text()
    assert "aarch64-apple-darwin" in manifest
    assert "sha256" in manifest


def test_app_wrapper_uses_library_data_root_not_xdg(tmp_path: Path) -> None:
    bundle = tmp_path / "PALM.app"
    macro = bundle / "Contents/MacOS"
    app = bundle / "Contents/Resources/app"
    macro.mkdir(parents=True)
    app.mkdir(parents=True)
    wrapper = macro / "palm"
    wrapper.write_text((ROOT / "packaging/macos/PALM.app/Contents/MacOS/palm").read_text())
    wrapper.chmod(0o755)
    fake = app / "bin/palm"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/sh\n"
        "printf 'PALM_DATA_DIR=%s\\n' \"${PALM_DATA_DIR:-}\"\n"
        "printf 'PALM_APP_ROOT=%s\\n' \"${PALM_APP_ROOT:-}\"\n"
        "printf 'ARGS=%s\\n' \"$*\"\n"
    )
    fake.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PALM_DATA_DIR", "PALM_APP_ROOT"}
    }
    env.update({"HOME": str(home), "XDG_DATA_HOME": str(tmp_path / "xdg")})
    result = subprocess.run(
        [str(wrapper), "--status"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0
    expected = str(home / "Library" / "Application Support" / "palm")
    assert f"PALM_DATA_DIR={expected}" in result.stdout
    assert "xdg" not in result.stdout
    assert f"PALM_APP_ROOT={app}" in result.stdout
    assert "ARGS=--status" in result.stdout


def test_check_zip_accepts_required_content(tmp_path: Path) -> None:
    module = load_script()
    archive = tmp_path / "PALM-test-macos-arm64.zip"
    required = [
        "PALM.app/Contents/MacOS/palm",
        "PALM.app/Contents/Info.plist",
        "PALM.app/Contents/Resources/app/bin/palm",
        "PALM.app/Contents/Resources/app/python/bin/python3.11",
        "PALM.app/Contents/Resources/app/bin/uv",
        "PALM.app/Contents/Resources/app/web/dist/index.html",
        "PALM.app/Contents/Resources/app/analysis/models.json",
        "PALM.app/Contents/Resources/app/analysis/checkpoints.json",
        "PALM.app/Contents/Resources/app/analysis/separate_track.py",
        "PALM.app/Contents/Resources/app/analysis/separate_msst.py",
        "PALM.app/Contents/Resources/app/analysis/envs/cpu-macos/uv.lock",
        "PALM.app/Contents/Resources/app/analysis/envs/msst-macos/uv.lock",
        "PALM.app/Contents/Resources/app/licenses/LICENSE",
        "PALM.app/Contents/Resources/app/licenses/third_party/manifest.json",
        "PALM.app/Contents/Resources/app/install.json",
        "PALM.app/Contents/Resources/app/runtime-requirements.txt",
    ]
    with zipfile.ZipFile(archive, "w") as bundle:
        for name in required:
            bundle.writestr(name, "x")
    assert module.check_zip(archive) == 0
    with zipfile.ZipFile(archive, "a") as bundle:
        bundle.writestr("PALM.app/Contents/Resources/app/models/weight.bin", "x")
    with pytest.raises(module.PackageError):
        module.check_zip(archive)


def test_zip_writer_records_unix_executable_modes(tmp_path: Path) -> None:
    module = load_script()
    for name in EXECUTABLES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
    plain = tmp_path / "PALM.app/Contents/Resources/app/README.md"
    plain.write_text("readme")
    plain.chmod(0o600)
    archive = tmp_path / "PALM-test-macos-arm64.zip"
    module.build_zip(tmp_path, archive)
    with zipfile.ZipFile(archive) as bundle:
        for name in EXECUTABLES:
            info = bundle.getinfo(name)
            assert info.create_system == 3
            mode = (info.external_attr >> 16) & 0o777
            assert mode & 0o111, (name, oct(mode))
        plain_info = bundle.getinfo("PALM.app/Contents/Resources/app/README.md")
        assert plain_info.create_system == 3
        assert (plain_info.external_attr >> 16) & 0o777 == 0o644


def test_checksum_file_uses_flat_basenames(tmp_path: Path) -> None:
    module = load_script()
    files = [
        tmp_path / "PALM-0.1.0-dev-macos-arm64.zip",
        tmp_path / "PALM-0.1.0-dev-macos-arm64.dmg",
    ]
    for path in files:
        path.write_bytes(path.name.encode())
    checksums = module.write_checksums(tmp_path, "0.1.0-dev")
    lines = checksums.read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        digest, name = line.split("  ", 1)
        assert len(digest) == 64
        assert name in {path.name for path in files}
        assert "dist/" not in name
        assert digest == module.sha256(tmp_path / name)


def test_built_macos_zip_when_present() -> None:
    zips = sorted((ROOT / "dist").glob("PALM-*-macos-arm64.zip"))
    if not zips:
        pytest.skip("macOS ZIP has not been built")
    module = load_script()
    assert module.check_zip(zips[-1]) == 0
    with zipfile.ZipFile(zips[-1]) as archive:
        names = archive.namelist()
        for name in EXECUTABLES:
            info = archive.getinfo(name)
            assert info.create_system == 3, name
            assert (info.external_attr >> 16) & 0o111, name
    lower = [name.lower() for name in names]
    assert any(name.endswith("palm.app/contents/macos/palm") for name in lower)
    assert any(name.endswith("resources/app/install.json") for name in lower)
    assert any(name.endswith("resources/app/licenses/third_party/manifest.json") for name in lower)
    assert any(name.endswith("resources/app/python/bin/python3.11") for name in lower)
    assert any(name.endswith("resources/app/bin/uv") for name in lower)
    assert any(name.endswith("resources/app/web/dist/index.html") for name in lower)
    import json

    install = next(name for name in names if name.lower().endswith("resources/app/install.json"))
    with zipfile.ZipFile(zips[-1]) as archive:
        payload = json.loads(archive.read(install))
    assert payload["channel"] == "macos-arm64"
    assert payload["assets"]["macos-arm64"]["name"].endswith(".zip")
    root_forbidden = {"models", "tools", "environments", "cache", "tests", "storage"}
    assert not any(
        len(Path(name).parts) >= 2 and Path(name).parts[1] in root_forbidden for name in lower
    )
