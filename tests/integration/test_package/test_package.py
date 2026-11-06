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


def test_extracted_tar_has_bundled_python_envs_and_tool_installer() -> None:
    import tempfile

    from basseparate.config import RuntimePaths
    from basseparate.setup.environments import create_environment, environment_spec
    from basseparate.setup.tools import _load_legacy_installer

    tars = sorted((ROOT / "dist").glob("PALM-*-linux-x86_64.tar.gz"))
    if not tars:
        pytest.skip("no dist/PALM tar; run make package first")
    with tempfile.TemporaryDirectory(prefix="palm-layout-") as scratch:
        with tarfile.open(tars[-1], "r:gz") as archive:
            archive.extractall(scratch, filter="data")
        app = next(path for path in Path(scratch).iterdir() if path.is_dir())
        runtime = RuntimePaths.from_environment(
            mode="packaged", app_root=app, data_root=Path(scratch) / "data"
        )
        bundled = app / "python" / "bin" / "python3.11"
        assert runtime.bundled_python == bundled
        assert bundled.is_file()
        assert (app / "scripts" / "install_tools.py").is_file()
        installer = _load_legacy_installer(runtime)
        assert (
            Path(installer.__file__).resolve() == (app / "scripts" / "install_tools.py").resolve()
        )
        spec = environment_spec("cpu", runtime)
        assert spec.project_dir == app / "analysis" / "envs" / "cpu"
        assert (spec.project_dir / "pyproject.toml").is_file()
        assert (spec.project_dir / "uv.lock").is_file()
        assert (spec.project_dir / "cpu.json").is_file()
        calls: list[tuple[list[str], dict[str, str]]] = []

        def run_uv(command: list[str], environment: dict[str, str], cwd: Path) -> None:
            calls.append((command, environment))
            target = Path(environment["UV_PROJECT_ENVIRONMENT"])
            (target / "bin").mkdir(parents=True)
            (target / "bin" / "python").write_text("python", encoding="utf-8")

        result = create_environment("cpu", runtime=runtime, run_uv=run_uv)
        assert result["installed"] is True
        command, environment = calls[0]
        python_arg = command[command.index("--python") + 1]
        project_arg = command[command.index("--directory") + 1]
        assert Path(python_arg) == bundled and Path(python_arg).is_file()
        assert Path(project_arg) == spec.project_dir and Path(project_arg).is_dir()
        assert Path(environment["UV_PROJECT_ENVIRONMENT"]).is_relative_to(runtime.data_root)
