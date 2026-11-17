"""Doctor checks the analysis tool that the platform actually uses."""

from __future__ import annotations

from pathlib import Path

import pytest

from basseparate import doctor, platform_support
from basseparate.config import RuntimePaths
from basseparate.doctor import DoctorLayout, diagnose


def _fake_tool(_command: str, _args: tuple[str, ...], _timeout: float):
    return 0, "version-test"


def _fake_gpu():
    return True, "Test GPU"


def _runtime(tmp_path: Path) -> RuntimePaths:
    app = tmp_path / "app"
    data = tmp_path / "data"
    app.mkdir()
    return RuntimePaths.from_environment(mode="packaged", app_root=app, data_root=data)


def test_windows_reports_sonic_annotator_not_piper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doctor, "WINDOWS", True)
    monkeypatch.setattr(doctor, "MACOS", False)
    monkeypatch.setattr(platform_support, "WINDOWS", True)
    monkeypatch.setattr(platform_support, "MACOS", False)
    runtime = _runtime(tmp_path)
    sonic = runtime.tools_root / "sonic-annotator-1.7.0" / "sonic-annotator.exe"
    sonic.parent.mkdir(parents=True)
    sonic.write_bytes(b"exe")
    plugin = runtime.tools_root / "vamp-plugins" / "qm-vamp-plugins.dll"
    plugin.parent.mkdir(parents=True)
    plugin.write_bytes(b"dll")

    report = diagnose(
        DoctorLayout.from_runtime(runtime), tool_probe=_fake_tool, gpu_probe=_fake_gpu
    )
    checks = {check.id: check for check in report.checks}
    assert checks["sonic_annotator"].status == "ok"
    assert "piper" not in checks
    assert checks["vamp_plugins"].status == "ok"


def test_macos_missing_sonic_annotator_is_not_false_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doctor, "WINDOWS", False)
    monkeypatch.setattr(doctor, "MACOS", True)
    monkeypatch.setattr(platform_support, "WINDOWS", False)
    monkeypatch.setattr(platform_support, "MACOS", True)
    runtime = _runtime(tmp_path)
    plugin = runtime.tools_root / "vamp-plugins" / "qm-vamp-plugins.dylib"
    plugin.parent.mkdir(parents=True)
    plugin.write_bytes(b"dylib")

    report = diagnose(
        DoctorLayout.from_runtime(runtime), tool_probe=_fake_tool, gpu_probe=_fake_gpu
    )
    checks = {check.id: check for check in report.checks}
    assert checks["sonic_annotator"].status == "missing"
    assert "sonic_annotator" in report.missing
    assert "piper" not in checks
