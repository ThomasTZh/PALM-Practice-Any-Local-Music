"""Doctor checks are deterministic, read-only and report each dependency."""

from __future__ import annotations

import socket
from pathlib import Path

from basseparate.doctor import DoctorLayout, diagnose


def make_layout(tmp_path: Path) -> DoctorLayout:
    root = tmp_path / "repo"
    data = tmp_path / "data"
    data.mkdir()
    for relative in (
        "models/htdemucs_ft",
        "storage/tools/vamp-plugins",
        "storage/tools/vamp-sdk",
        "storage/tools/vamp-host",
        "storage/tools/sv/squashfs-root/usr/bin",
        "analysis/.venv/bin",
        "third_party/emsdk",
        "third_party/signalsmith-stretch",
        "audio2test",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    for index in range(4):
        (root / "models/htdemucs_ft" / f"checkpoint-{index}.th").write_bytes(b"model")
    (root / "models/htdemucs_ft/htdemucs_ft.yaml").write_text("preset")
    (root / "storage/tools/vamp-plugins/qm-vamp-plugins.so").write_bytes(b"plugin")
    (root / "storage/tools/vamp-host/vamp-host").write_bytes(b"host")
    piper = root / "storage/tools/sv/squashfs-root/usr/bin/piper-vamp-simple-server"
    piper.write_bytes(b"piper")
    piper.chmod(0o755)
    analysis_python = root / "analysis/.venv/bin/python"
    analysis_python.write_bytes(b"python")
    (root / "audio2test/take.wav").write_bytes(b"RIFF")
    return DoctorLayout(root=root, data_root=data)


def fake_tool(command: str, args: tuple[str, ...], timeout: float) -> tuple[int, str]:
    return 0, f"{command} version-test"


def fake_gpu() -> tuple[bool, str]:
    return True, "Test GPU, 999.99"


def checks_by_id(report):
    return {check.id: check for check in report.checks}


def test_doctor_reports_each_dependency_as_ok_or_missing(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    report = diagnose(layout, tool_probe=fake_tool, gpu_probe=fake_gpu)
    checks = checks_by_id(report)
    required = {
        "ffmpeg",
        "ffprobe",
        "data_root",
        "model_bundle",
        "vamp_plugins",
        "piper",
        "analysis_venv",
    }
    for check_id in required:
        assert checks[check_id].status == "ok", (check_id, checks[check_id])
        assert checks[check_id].required is True
    assert checks["gpu"].status == "ok"
    assert checks["gpu"].required is False
    assert report.status == "ok"
    assert report.ok is True
    assert report.missing == ()
    assert all(check.status in {"ok", "missing"} for check in report.checks)


def test_missing_required_asset_degrades_the_report_without_writing(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    (layout.vamp_plugins / "qm-vamp-plugins.so").unlink()
    before = sorted(
        (str(path.relative_to(tmp_path)), path.stat().st_size)
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    report = diagnose(layout, tool_probe=fake_tool, gpu_probe=fake_gpu)
    after = sorted(
        (str(path.relative_to(tmp_path)), path.stat().st_size)
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert before == after
    assert checks_by_id(report)["vamp_plugins"].status == "missing"
    assert report.status == "degraded"
    assert "vamp_plugins" in report.missing


def test_doctor_never_opens_a_network_socket(tmp_path: Path, monkeypatch) -> None:
    layout = make_layout(tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("doctor must not use the network")

    monkeypatch.setattr(socket, "socket", no_network)
    report = diagnose(layout, tool_probe=fake_tool, gpu_probe=fake_gpu)
    assert report.status == "ok"


def test_doctor_serialises_every_check(tmp_path: Path) -> None:
    layout = make_layout(tmp_path)
    payload = diagnose(layout, tool_probe=fake_tool, gpu_probe=fake_gpu).to_dict()
    assert payload["status"] == "ok"
    assert payload["ok"] is True
    assert isinstance(payload["checks"], list)
    for check in payload["checks"]:
        assert set(check) == {"id", "label", "status", "detail", "required", "path"}
