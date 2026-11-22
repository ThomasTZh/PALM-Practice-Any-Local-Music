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
    for key in ("python", "uv"):
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
    assert any(name.endswith("/python/bin/python3.11") for name in names)
    assert any(name.endswith("/scripts/install_tools.py") for name in names)
    assert any(name.endswith("/analysis/envs/cpu/uv.lock") for name in names)
    assert any(name.endswith("/analysis/envs/cuda/uv.lock") for name in names)
    assert any(name.endswith("/web/dist/index.html") for name in names)
    assert any(name.endswith("/tools/ffmpeg/ffmpeg") for name in names)
    assert any(name.endswith("/tools/sonic-annotator/squashfs-root/AppRun") for name in names)
    assert any(name.endswith("/tools/vamp-plugins/qm-vamp-plugins.so") for name in names)
    assert any(
        name.endswith("/licenses/bundled-tools/sources/ffmpeg-9.0.2.tar.xz") for name in names
    )
    assert any(name.endswith("/tools/vamp-plugins/nnls-chroma.so") for name in names)
    assert not any(name.startswith("/") or "/../" in name for name in names)
    forbidden_roots = {
        "models",
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


def test_built_tar_ships_current_readme_and_no_stale_release_text() -> None:
    tars = sorted((ROOT / "dist").glob("PALM-*-linux-x86_64.tar.gz"))
    if not tars:
        pytest.skip("no dist/PALM tar; run make package first")
    with tarfile.open(tars[-1], "r:gz") as archive:
        names = archive.getnames()
        readme_name = next(name for name in names if name.endswith("/README.md"))
        notes_name = next(name for name in names if name.endswith("/RELEASE-NOTES.md"))
        portable_name = next(name for name in names if name.endswith("/docs/portable.md"))
        readme = archive.extractfile(readme_name).read().decode()  # type: ignore[union-attr]
        notes = archive.extractfile(notes_name).read().decode()  # type: ignore[union-attr]
        portable = archive.extractfile(portable_name).read().decode()  # type: ignore[union-attr]
    combined = readme + "\n" + notes + "\n" + portable
    for stale in (
        "Press Ctrl+C",
        "terminal opens with the server log",
        "`ffmpeg` and `ffprobe` must already be installed",
        "Linux-only build",
        "delete-data",
        "Windows and macOS are not packaged",
    ):
        assert stale not in combined
    assert "control window" in readme.lower()
    assert "SHA256SUMS" in notes
    assert "bundled" in readme.lower()
    assert "bundled" in notes.lower()
    assert "analysis is temporarily" not in combined.lower()
    assert "tools are not bundled" not in combined.lower()
    assert "ffmpeg is not bundled" not in combined.lower()
    assert "downloads ffmpeg" not in combined.lower()
    assert "does **not** contain ffmpeg" not in portable.lower()
    assert "verified by setup; they are not external prerequisites" not in combined.lower()
    assert "no tool download or uac" in portable.lower()
    assert "bundled" in portable.lower()


def test_dist_checksum_manifest_covers_all_present_platform_assets() -> None:
    assets = sorted(
        path
        for path in (ROOT / "dist").glob("PALM-*")
        if path.suffix in {".gz", ".zip", ".exe", ".dmg"}
    )
    if not assets:
        pytest.skip("no dist release assets")
    manifest = (ROOT / "dist" / "SHA256SUMS").read_text()
    for asset in assets:
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        assert f"{digest}  {asset.name}" in manifest, asset.name
    if len({".dmg" in a.name for a in assets}) and len(assets) > 1:
        assert len(assets) >= 2


def test_extracted_tar_default_backend_analyzes_with_bundled_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile

    from basseparate.analysis_backend import default_backend
    from basseparate.features import analyze_file

    tars = sorted((ROOT / "dist").glob("PALM-*-linux-x86_64.tar.gz"))
    if not tars:
        pytest.skip("no dist/PALM tar; run make package first")
    with tempfile.TemporaryDirectory(prefix="palm-analysis-") as scratch:
        with tarfile.open(tars[-1], "r:gz") as archive:
            archive.extractall(scratch, filter="data")
        app = next(path for path in Path(scratch).iterdir() if path.is_dir())
        monkeypatch.setenv("PALM_MODE", "packaged")
        monkeypatch.setenv("PALM_APP_ROOT", str(app))
        monkeypatch.setenv("PALM_DATA_DIR", str(tmp_path / "data"))
        backend = default_backend()
        assert backend.id == "sonic"
        result = analyze_file(
            ROOT / "tests" / "fixtures" / "audio" / "chords_c_am_f_g.wav",
            cache_dir=tmp_path / "cache",
            backend=backend,
        )
        assert result.bpm is not None and result.bpm > 0
        assert result.key.label == "C major"
        assert len(result.chords) >= 2
        assert len(result.grid.beats) >= 2
