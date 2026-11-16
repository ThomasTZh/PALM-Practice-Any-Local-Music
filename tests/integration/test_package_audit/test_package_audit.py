"""Release/package audit for third-party payloads and licence manifest."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/unit/test_licenses"))
import audit  # noqa: E402


def test_manifest_validates() -> None:
    audit.validate(ROOT)


def test_no_third_party_binary_or_model_is_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    forbidden = (
        ".exe",
        ".dll",
        ".dylib",
        ".dmg",
        ".ckpt",
        ".th",
        ".pt",
        ".onnx",
        ".zip",
        ".tar.gz",
    )
    allowed = {"packaging/windows/PALM.exe"}
    offenders = [
        name for name in tracked if name.lower().endswith(forbidden) and name not in allowed
    ]
    assert offenders == []
    # The one first-party exception must stay buildable from committed source.
    windows = ROOT / "packaging" / "windows"
    assert (windows / "palm_launcher.c").is_file()
    assert (windows / "build_launcher.ps1").is_file()
    assert (windows / "PALM.exe").is_file()


def test_built_packages_contain_no_tools_or_models() -> None:
    archives = sorted((ROOT / "dist").glob("PALM-*.*"))
    archives = [path for path in archives if path.suffix in {".zip", ".gz"}]
    if not archives:
        pytest.skip("no built package")
    for archive in archives:
        audit.assert_package_has_no_third_party_payload(archive)


def test_package_manifest_does_not_mark_tools_or_models_bundled() -> None:
    data = audit.load_manifest(ROOT)
    for component in data["components"]:
        if component.get("component_type") in {"tool", "model"}:
            assert component["distribution"] in {"downloaded", "excluded"}
