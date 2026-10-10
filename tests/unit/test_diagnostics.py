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


def test_model_baseline_check_reports_a_state(config) -> None:
    """The check must exist, be optional, and name one of the three states."""
    checks = run_diagnostics(config)  # type: ignore[arg-type]
    check = next(c for c in checks if c.name == "model-baseline")
    assert check.required is False
    assert check.status in {"ok", "warn"}
    assert any(
        token in check.detail
        for token in ("bundled_available", "bundled_missing", "bundled_corrupt")
    )
    assert "htdemucs_ft" in check.detail
    assert exit_code_for(checks) == 0


def test_model_baseline_states_for_forced_directories(monkeypatch, config, tmp_path) -> None:
    import basseparate.models as models

    manifest = models.get_manifest("htdemucs_ft")

    # Missing: an empty directory -> bundled_missing.
    monkeypatch.setattr(models, "default_bundle_dir", lambda m: tmp_path / "empty")
    checks = run_diagnostics(config)  # type: ignore[arg-type]
    check = next(c for c in checks if c.name == "model-baseline")
    assert check.status == "warn"
    assert "bundled_missing" in check.detail

    # Corrupt: right file names, wrong bytes -> bundled_corrupt.
    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    for spec in manifest.artifacts:
        (corrupt_dir / spec.name).write_bytes(b"not the real bytes")
    monkeypatch.setattr(models, "default_bundle_dir", lambda m: corrupt_dir)
    checks = run_diagnostics(config)  # type: ignore[arg-type]
    check = next(c for c in checks if c.name == "model-baseline")
    assert check.status == "warn"
    assert "bundled_corrupt" in check.detail
