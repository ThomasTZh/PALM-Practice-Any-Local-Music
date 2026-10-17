"""Portable save pipeline (M2.15, spec §17.1, §17.4).

Full workflow against a temp data root: publication, verification,
retention, and the failure semantics (a failed save never destroys the
last valid file and leaves no staging debris).
"""

from __future__ import annotations

import hashlib
import sqlite3
import zipfile
from pathlib import Path

import pytest

from basseparate.portable.format import PortableManifest
from basseparate.portable.save import (
    PortableSaveMissingAsset,
    PortableSaveNoSpace,
    PortableSaveVerifyFailed,
    perform_portable_save,
)
from basseparate.storage import PortableArtifactRepository, ProjectRepository
from basseparate.storage.paths import resolve_storage_paths
from tests.unit.portable_seed import (
    STEM1_HASH_A,
    create_seed_files,
    seed_two_projects,
)


@pytest.fixture()
def store(tmp_path: Path):
    root = tmp_path / "store"
    seed = seed_two_projects(root)
    created = create_seed_files(root, seed)
    paths = resolve_storage_paths(root)
    db = root / "data" / "basseparate.db"
    repo = ProjectRepository(db)
    artifacts = PortableArtifactRepository(db)
    project = repo.get_project(seed.project_a)
    return {
        "root": root,
        "seed": seed,
        "files": created,
        "paths": paths,
        "db": db,
        "repo": repo,
        "artifacts": artifacts,
        "project": project,
    }


def _save(store) -> tuple:
    return perform_portable_save(
        store["db"], store["paths"], store["project"], store["artifacts"]
    )


class TestPortableSave:
    def test_save_publishes_verified_artifact(self, store) -> None:
        seed, paths, artifacts = store["seed"], store["paths"], store["artifacts"]
        artifact, manifest = _save(store)
        assert isinstance(manifest, PortableManifest)
        dest = paths.resolve_asset_path(artifact.relative_path)
        assert dest.is_file()
        # The row agrees with the file on disk.
        assert hashlib.sha256(dest.read_bytes()).hexdigest() == artifact.sha256
        assert dest.stat().st_size == artifact.byte_size
        # Managed name carries revision + hash prefix.
        assert dest.name == f"{store['project'].revision}-{artifact.sha256[:12]}.basseparate"
        assert artifact.relative_path == (
            f"data/portable/{seed.project_a}/{dest.name}"
        )
        assert artifact.download_filename.endswith(f"-r{store['project'].revision}.basseparate")
        row = artifacts.get(artifact.id)
        assert row == artifact
        assert artifacts.latest_for_project(seed.project_a) == artifact
        # The archive verifies against its manifest.
        with zipfile.ZipFile(dest) as zf:
            assert zf.testzip() is None
            names = set(zf.namelist())
            m = PortableManifest.model_validate_json(zf.read("manifest.json").decode())
        assert names == {"manifest.json"} | {x.name for x in m.members}
        # No staging debris (archive moved, intermediate db removed).
        staging = paths.data / "portable" / ".staging"
        assert not any(staging.iterdir())

    def test_retention_keeps_one_previous(self, store) -> None:
        seed, paths, artifacts = store["seed"], store["paths"], store["artifacts"]
        a1, _ = _save(store)
        a2, _ = _save(store)
        a3, _ = _save(store)
        saves = artifacts.list_for_project(seed.project_a)
        assert [s.id for s in saves] == [a3.id, a2.id]  # newest first
        # The oldest published file was reclaimed.
        assert not (paths.resolve_asset_path(a1.relative_path)).exists()
        assert (paths.resolve_asset_path(a2.relative_path)).exists()
        assert (paths.resolve_asset_path(a3.relative_path)).exists()
        on_disk = list((paths.data / "portable" / seed.project_a).glob("*.basseparate"))
        assert len(on_disk) == 2

    def test_missing_essential_fails_cleanly(self, store) -> None:
        seed, paths, artifacts = store["seed"], store["paths"], store["artifacts"]
        a1, _ = _save(store)
        stem1 = store["files"][f"data/assets/{STEM1_HASH_A}.pcm"]
        stem1.unlink()
        with pytest.raises(PortableSaveMissingAsset) as excinfo:
            _save(store)
        assert excinfo.value.code == "SAVE_ASSET_MISSING"
        assert stem1.name in [Path(m).name for m in excinfo.value.missing]
        # Last valid file intact; no new row; no staging debris.
        assert (paths.resolve_asset_path(a1.relative_path)).is_file()
        assert len(artifacts.list_for_project(seed.project_a)) == 1
        staging = paths.data / "portable" / ".staging"
        assert not any(staging.iterdir())

    def test_missing_optional_is_excluded(self, store) -> None:
        from tests.unit.portable_seed import PB_HASH_A

        seed, paths = store["seed"], store["paths"]
        store["files"][f"data/assets/{PB_HASH_A}.pcm"].unlink()
        artifact, manifest = _save(store)
        assert not any(a.asset_id == seed.pb_a for a in manifest.assets)
        dest = paths.resolve_asset_path(artifact.relative_path)
        with zipfile.ZipFile(dest) as zf:
            names = set(zf.namelist())
            assert f"assets/sha256/{PB_HASH_A}.pcm" not in names
            zf.extract("project.sqlite", store["root"])
        conn = sqlite3.connect(store["root"] / "project.sqlite")
        try:
            assert (
                conn.execute("SELECT COUNT(*) FROM assets WHERE id = ?", (seed.pb_a,)).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM representations WHERE asset_id = ?", (seed.pb_a,)
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM project_assets WHERE asset_id = ?", (seed.pb_a,)
                ).fetchone()[0]
                == 0
            )
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            conn.close()

    def test_no_space_refuses(self, store, monkeypatch) -> None:
        artifacts = store["artifacts"]
        import basseparate.portable.save as save_module

        def fake_disk_usage(path):
            class Usage:
                total = 10_000
                used = 9_000
                free = 1_000

            return Usage()

        monkeypatch.setattr(save_module.shutil, "disk_usage", fake_disk_usage)
        with pytest.raises(PortableSaveNoSpace):
            _save(store)
        assert artifacts.list_for_project(store["seed"].project_a) == []
        staging = store["paths"].data / "portable" / ".staging"
        assert not any(staging.iterdir())

    def test_verify_failure_cleans_staging(self, store, monkeypatch) -> None:
        artifacts = store["artifacts"]
        import basseparate.portable.save as save_module

        def fake_verify(path):
            raise PortableSaveVerifyFailed("simulated corruption")

        monkeypatch.setattr(save_module, "_verify_archive", fake_verify)
        with pytest.raises(PortableSaveVerifyFailed):
            _save(store)
        assert artifacts.list_for_project(store["seed"].project_a) == []
        staging = store["paths"].data / "portable" / ".staging"
        assert not any(staging.iterdir())
