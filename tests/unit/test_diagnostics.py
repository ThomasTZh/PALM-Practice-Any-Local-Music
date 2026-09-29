"""Unit tests for the doctor diagnostics (M0.3)."""

from __future__ import annotations

import pytest

from basseparate.config import resolve_config
from basseparate.diagnostics import exit_code_for, format_report, run_diagnostics


@pytest.fixture()
def config(tmp_path) -> object:
    return resolve_config(env={}, cli={"storage_root": str(tmp_path / "never-created")})


def test_required_checks_present(config) -> None:
    checks = run_diagnostics(config)  # type: ignore[arg-type]
    required = {c.name for c in checks if c.required}
    assert {"application", "python", "platform", "frontend-build", "database"} <= required


def test_doctor_does_not_mutate_environment(config, tmp_path) -> None:
    run_diagnostics(config)  # type: ignore[arg-type]
    assert not (tmp_path / "never-created").exists()


def test_report_and_exit_code(config) -> None:
    checks = run_diagnostics(config)  # type: ignore[arg-type]
    report = format_report(checks)
    assert "basseparate doctor" in report
    assert "RESULT" in report
    assert exit_code_for(checks) == 0


def test_optional_gpu_failure_does_not_fail_doctor(monkeypatch, config) -> None:
    import basseparate.diagnostics as diagnostics

    def fake_run(args: list[str]) -> tuple[int, str]:
        return 1, "driver error"

    monkeypatch.setattr(diagnostics, "_run_command", fake_run)
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    checks = run_diagnostics(config)  # type: ignore[arg-type]
    gpu = next(c for c in checks if c.name == "gpu")
    assert gpu.status == "warn"
    assert gpu.required is False
    assert exit_code_for(checks) == 0
