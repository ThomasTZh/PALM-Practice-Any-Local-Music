"""Pinned Windows/macOS tool acquisition with fake archives and installers."""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from basseparate.config import RuntimePaths
from basseparate.setup import tool_assets
from basseparate.setup.errors import SetupInstallError
from basseparate.setup.tool_assets import (
    PLATFORM_ASSETS,
    install_sonic_annotator,
    install_vamp_plugin_pack,
)


def _asset(tool: str, platform: str, data: bytes):
    current = PLATFORM_ASSETS[(platform, tool)]
    return replace(
        current,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _zip_bytes() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("sonic-annotator-win64/sonic-annotator.exe", b"exe")
    return stream.getvalue()


def _tar_bytes() -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        payload = b"binary"
        info = tarfile.TarInfo("sonic-annotator-1.7.0-macos/sonic-annotator")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return stream.getvalue()


def test_all_platform_assets_are_pinned() -> None:
    expected = {
        ("windows", "sonic_annotator"),
        ("macos", "sonic_annotator"),
        ("macos", "vamp_plugin_pack"),
    }
    assert set(PLATFORM_ASSETS) == expected
    for asset in PLATFORM_ASSETS.values():
        assert asset.url.startswith("https://github.com/")
        assert len(asset.sha256) == 64 and int(asset.sha256, 16) >= 0
        assert asset.size > 0


def test_windows_sonic_zip_extracts_into_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _zip_bytes()
    asset = _asset("sonic_annotator", "windows", data)
    monkeypatch.setitem(PLATFORM_ASSETS, ("windows", "sonic_annotator"), asset)
    runtime = RuntimePaths.from_environment(
        mode="packaged", app_root=tmp_path / "app", data_root=tmp_path / "data with spaces"
    )
    runtime.app_root.mkdir()
    result = install_sonic_annotator(
        runtime,
        platform="windows",
        downloader=lambda _asset, path: path.write_bytes(data),
    )
    assert result.is_file()
    assert result.parent == runtime.tools_root / "sonic-annotator-1.7.0"


def test_macos_sonic_tar_extracts_into_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _tar_bytes()
    asset = _asset("sonic_annotator", "macos", data)
    monkeypatch.setitem(PLATFORM_ASSETS, ("macos", "sonic_annotator"), asset)
    runtime = RuntimePaths.from_environment(
        mode="packaged", app_root=tmp_path / "app", data_root=tmp_path / "data"
    )
    runtime.app_root.mkdir()
    result = install_sonic_annotator(
        runtime,
        platform="macos",
        downloader=lambda _asset, path: path.write_bytes(data),
    )
    assert result.is_file()
    assert result.name == "sonic-annotator"


def test_bad_hash_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"not the pinned archive"
    monkeypatch.setitem(
        PLATFORM_ASSETS,
        ("windows", "sonic_annotator"),
        replace(_asset("sonic_annotator", "windows", data), sha256="0" * 64),
    )
    runtime = RuntimePaths.from_environment(
        mode="packaged", app_root=tmp_path / "app", data_root=tmp_path / "data"
    )
    runtime.app_root.mkdir()
    with pytest.raises(SetupInstallError, match="SHA-256"):
        install_sonic_annotator(
            runtime,
            platform="windows",
            downloader=lambda _asset, path: path.write_bytes(data),
        )


def test_windows_vamp_gui_installer_is_blocked(tmp_path: Path) -> None:
    runtime = RuntimePaths.from_environment(
        mode="packaged", app_root=tmp_path / "app", data_root=tmp_path / "data"
    )
    runtime.app_root.mkdir()
    calls: list[object] = []

    def downloader(_asset, path):
        calls.append(path)
        raise AssertionError("blocked Windows Vamp must not download a GUI installer")

    with pytest.raises(SetupInstallError) as caught:
        install_vamp_plugin_pack(
            runtime,
            platform="windows",
            downloader=downloader,
            runner=lambda command: calls.append(command),
        )
    message = str(caught.value)
    assert "No redistributable 64-bit qm-vamp-plugins" in message
    assert "GUI installer will not be run" in message
    assert calls == []


def test_windows_tools_install_sonic_but_refuses_gui_vamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = RuntimePaths.from_environment(
        mode="packaged", app_root=tmp_path / "app", data_root=tmp_path / "data"
    )
    runtime.app_root.mkdir()
    monkeypatch.setattr(
        tool_assets,
        "install_sonic_annotator",
        lambda *_args, **_kwargs: runtime.tools_root / "sonic-annotator-1.7.0",
    )
    with pytest.raises(SetupInstallError, match="No redistributable 64-bit"):
        tool_assets.install_platform_tools(runtime, platform="windows")


def test_macos_dmg_uses_hdiutil_and_pkgutil(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"dmg"
    monkeypatch.setitem(
        PLATFORM_ASSETS, ("macos", "vamp_plugin_pack"), _asset("vamp_plugin_pack", "macos", data)
    )
    monkeypatch.setattr(tool_assets, "plugin_suffix", lambda: ".dylib")
    runtime = RuntimePaths.from_environment(
        mode="packaged", app_root=tmp_path / "app", data_root=tmp_path / "data"
    )
    runtime.app_root.mkdir()
    commands: list[list[str]] = []

    def runner(command: list[str]):
        commands.append(command)
        if command[0] == "hdiutil" and command[1] == "attach":
            mount = Path(command[command.index("-mountpoint") + 1])
            (mount / "Vamp.pkg").write_bytes(b"pkg")
        elif command[0] == "pkgutil":
            expanded = Path(command[-1])
            expanded.mkdir(parents=True, exist_ok=True)
            (expanded / "qm-vamp-plugins.dylib").write_bytes(b"dylib")

    target = install_vamp_plugin_pack(
        runtime,
        platform="macos",
        downloader=lambda _asset, path: path.write_bytes(data),
        runner=runner,
    )
    assert (target / "qm-vamp-plugins.dylib").is_file()
    assert commands[0][0] == "hdiutil"
    assert any(command[0] == "pkgutil" for command in commands)


def test_macos_dmg_without_plugins_fails_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = b"dmg"
    monkeypatch.setitem(
        PLATFORM_ASSETS, ("macos", "vamp_plugin_pack"), _asset("vamp_plugin_pack", "macos", data)
    )
    monkeypatch.setattr(tool_assets, "plugin_suffix", lambda: ".dylib")
    runtime = RuntimePaths.from_environment(
        mode="packaged", app_root=tmp_path / "app", data_root=tmp_path / "data"
    )
    runtime.app_root.mkdir()
    with pytest.raises(SetupInstallError, match="no plugin libraries"):
        install_vamp_plugin_pack(
            runtime,
            platform="macos",
            downloader=lambda _asset, path: path.write_bytes(data),
            runner=lambda _command: None,
        )


def test_windows_and_macos_environment_projects_exist() -> None:
    root = Path(__file__).resolve().parents[3] / "analysis" / "envs"
    for name in ("cpu-windows", "cpu-macos", "msst-windows", "msst-macos"):
        assert (root / name / "pyproject.toml").is_file()
        assert (root / name / "uv.lock").is_file()
        assert (root / name / f"{name}.json").is_file()


def test_cuda_is_hidden_outside_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from basseparate import platform_support
    from basseparate.setup.environments import (
        available_env_variants,
        create_environment,
        environment_spec,
        environments_status,
    )

    app = tmp_path / "app"
    data = tmp_path / "data"
    app.mkdir()
    monkeypatch.setattr(platform_support, "WINDOWS", True)
    monkeypatch.setattr(platform_support, "MACOS", False)
    runtime = RuntimePaths.from_environment(mode="packaged", app_root=app, data_root=data)
    assert available_env_variants() == ("cpu",)
    assert set(environments_status(runtime)) == {"cpu"}
    assert environment_spec("cpu", runtime).project_dir.name == "cpu-windows"
    with pytest.raises(SetupInstallError, match="not available"):
        environment_spec("cuda", runtime)
    with pytest.raises(SetupInstallError, match="not available"):
        create_environment("cuda", runtime=runtime, run_uv=lambda *_: None)


def test_windows_macos_tool_status_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from basseparate import platform_support
    from basseparate.setup.tools import tools_status

    app = tmp_path / "app"
    data = tmp_path / "data"
    app.mkdir()
    monkeypatch.setattr(platform_support, "WINDOWS", False)
    monkeypatch.setattr(platform_support, "MACOS", False)
    windows_exe = data / "tools" / "sonic-annotator-1.7.0" / "sonic-annotator.exe"
    windows_exe.parent.mkdir(parents=True)
    windows_exe.write_bytes(b"exe")
    windows_plugin = data / "tools" / "vamp-plugins" / "qm-vamp-plugins.dll"
    windows_plugin.parent.mkdir(parents=True)
    windows_plugin.write_bytes(b"dll")
    monkeypatch.setattr(platform_support, "WINDOWS", True)
    monkeypatch.setattr(tool_assets, "plugin_suffix", lambda: ".dll")
    runtime = RuntimePaths.from_environment(mode="packaged", app_root=app, data_root=data)
    status = tools_status(runtime)
    assert status["sonic_visualiser"]["name"] == "Sonic Annotator"
    assert status["sonic_visualiser"]["path"] == str(windows_exe)
    assert status["vamp_plugin_pack"]["path"] == str(windows_plugin)
