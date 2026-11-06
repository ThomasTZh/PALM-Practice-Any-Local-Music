"""Release packaging: manifest pins and clean-room verifier contract."""

from __future__ import annotations

import hashlib
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_build_manifest_pins_every_asset() -> None:
    data = tomllib.loads((ROOT / "packaging" / "build-manifest.toml").read_text())
    assert data["schema_version"] == 1
    for key in ("python", "uv", "appimagetool"):
        entry = data[key]
        assert entry["url"].startswith("https://")
        assert len(entry["sha256"]) == 64
        assert entry["size"] > 0
    lock = (ROOT / "packaging" / "app-runtime" / "uv.lock").read_text()
    assert 'name = "fastapi"' in lock and "sha256:" in lock


def test_verifier_is_executable_and_syntactically_valid() -> None:
    script = ROOT / "packaging" / "verify-clean-room.sh"
    assert script.is_file()
    assert script.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_doc_records_clean_room_verification() -> None:
    doc = (ROOT / "packaging" / "VERIFICATION.md").read_text()
    assert "clean-room" in doc.lower()
    assert "api/health" in doc
    assert "SHA256SUMS" in doc


def test_built_tar_checksum_and_contents_if_present() -> None:
    tars = sorted((ROOT / "dist").glob("PALM-*-linux-x86_64.tar.gz"))
    if not tars:
        pytest.skip("no dist/PALM tar; run make package first")
    tar_path = tars[-1]
    assert tar_path.stat().st_size < 2 * 1024**3
    sums = (ROOT / "dist" / "SHA256SUMS").read_text()
    digest = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    assert f"{digest}  {tar_path.name}" in sums
    with tarfile.open(tar_path, "r:gz") as archive:
        names = archive.getnames()
    assert any(name.endswith("/bin/palm") for name in names)
    assert any(name.endswith("/web/dist/index.html") for name in names)
    assert not any(name.startswith("/") or "/../" in name for name in names)
    forbidden_roots = {
        "models",
        "tools",
        "tests",
        "audio2test",
        ".git",
        ".venv",
        "storage",
        "cache",
        "node_modules",
    }
    for name in names:
        parts = Path(name).parts
        assert len(parts) < 2 or parts[1] not in forbidden_roots, name
