"""Archive writer (M2.15, spec §17.1): streaming, hashing, determinism."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.portable.closure import compute_portable_plan
from basseparate.portable.database import build_portable_database
from basseparate.portable.format import (
    DATABASE_MEMBER,
    MANIFEST_MEMBER,
    PROVENANCE_MODELS_MEMBER,
    PROVENANCE_RUNS_MEMBER,
    PortableManifest,
    compression_for,
)
from basseparate.portable.writer import PortableWriteError, write_portable_archive
from basseparate.storage.paths import resolve_storage_paths
from tests.unit.portable_seed import create_seed_files, seed_two_projects

SAVED_AT = datetime(2026, 10, 17, 12, 0, 0, tzinfo=UTC)


@pytest.fixture()
def store(tmp_path: Path):
    """A seeded store with on-disk files; returns (root, seed, paths, plan, db)."""
    root = tmp_path / "store"
    seed = seed_two_projects(root)
    create_seed_files(root, seed)
    paths = resolve_storage_paths(root)
    import sqlite3

    conn = sqlite3.connect(f"file:{seed.db_path}?mode=ro", uri=True)
    try:
        plan = compute_portable_plan(conn, seed.project_a)
    finally:
        conn.close()
    db_snapshot = tmp_path / "snapshot.sqlite"
    build_portable_database(seed.db_path, seed.project_a, db_snapshot)
    return root, seed, paths, plan, db_snapshot


class TestPortableWriter:
    def test_member_set_and_order(self, store) -> None:
        _root, _seed, paths, plan, db = store
        destination = store[0] / "out" / "song.basseparate"
        manifest = write_portable_archive(plan, db, paths, destination, SAVED_AT)
        with zipfile.ZipFile(destination) as zf:
            names = zf.namelist()
        assert names[0] == DATABASE_MEMBER
        assert names[-1] == MANIFEST_MEMBER
        # Every plan asset, cache file, and provenance document is present.
        for asset in plan.assets:
            assert asset.member in names
        for cache in plan.waveform_caches:
            assert f"{cache.member_prefix}manifest.json" in names
            assert f"{cache.member_prefix}tile0.bin" in names
        assert PROVENANCE_RUNS_MEMBER in names
        assert PROVENANCE_MODELS_MEMBER in names
        # The archive contains exactly the manifest's members plus itself.
        assert set(names) == {MANIFEST_MEMBER} | {m.name for m in manifest.members}

    def test_per_member_hash_and_size(self, store) -> None:
        _root, _seed, paths, plan, db = store
        destination = store[0] / "out" / "song.basseparate"
        manifest = write_portable_archive(plan, db, paths, destination, SAVED_AT)
        with zipfile.ZipFile(destination) as zf:
            for member in manifest.members:
                data = zf.read(member.name)
                assert len(data) == member.uncompressed_size_bytes
                assert hashlib.sha256(data).hexdigest() == member.sha256

    def test_compression_types_follow_policy(self, store) -> None:
        _root, _seed, paths, plan, db = store
        destination = store[0] / "out" / "song.basseparate"
        manifest = write_portable_archive(plan, db, paths, destination, SAVED_AT)
        with zipfile.ZipFile(destination) as zf:
            for member in manifest.members:
                info = zf.getinfo(member.name)
                assert info.compress_type == compression_for(member.name)
                assert member.compression == (
                    "stored" if compression_for(member.name) == 0 else "deflate"
                )

    def test_manifest_excludes_itself_and_validates(self, store) -> None:
        _root, _seed, paths, plan, db = store
        destination = store[0] / "out" / "song.basseparate"
        write_portable_archive(plan, db, paths, destination, SAVED_AT)
        with zipfile.ZipFile(destination) as zf:
            raw = zf.read(MANIFEST_MEMBER)
        manifest = PortableManifest.model_validate_json(raw.decode("utf-8"))
        assert MANIFEST_MEMBER not in {m.name for m in manifest.members}
        assert manifest.saved_revision == 5  # the seed's projects.revision
        assert manifest.format_id == "basseparate.project"
        assert str(manifest.project_id) == plan.project_id
        assert len(manifest.assets) == len(plan.assets)
        for asset in manifest.assets:
            assert asset.member in {m.name for m in manifest.members}

    def test_provenance_documents(self, store) -> None:
        _root, _seed, paths, plan, db = store
        destination = store[0] / "out" / "song.basseparate"
        write_portable_archive(plan, db, paths, destination, SAVED_AT)
        with zipfile.ZipFile(destination) as zf:
            runs = json.loads(zf.read(PROVENANCE_RUNS_MEMBER))
            models = json.loads(zf.read(PROVENANCE_MODELS_MEMBER))
        assert runs["version"] == 1
        assert len(runs["runs"]) == len(plan.separation_runs)
        assert models["version"] == 1
        assert models["models"]  # the checked-in registry metadata

    def test_deterministic_bytes_for_same_inputs(self, store) -> None:
        _root, _seed, paths, plan, db = store
        out1 = store[0] / "out" / "one.basseparate"
        out2 = store[0] / "out" / "two.basseparate"
        write_portable_archive(plan, db, paths, out1, SAVED_AT)
        write_portable_archive(plan, db, paths, out2, SAVED_AT)
        assert hashlib.sha256(out1.read_bytes()).hexdigest() == (
            hashlib.sha256(out2.read_bytes()).hexdigest()
        )

    def test_missing_asset_file_raises(self, store) -> None:
        root, seed, paths, plan, db = store
        # Delete one essential asset file.
        target = None
        for asset in plan.assets:
            if asset.role == "source_pcm":
                target = paths.resolve_asset_path(asset.relative_path)
                break
        assert target is not None
        target.unlink()
        destination = root / "out" / "song.basseparate"
        with pytest.raises(PortableWriteError):
            write_portable_archive(plan, db, paths, destination, SAVED_AT)
        assert not destination.exists()

    def test_missing_cache_dir_is_empty_cache(self, store) -> None:
        root, seed, paths, plan, db = store
        cache_dir = paths.resolve_asset_path(
            f"cache/waveforms/{plan.waveform_caches[0].source_hash}"
        )
        for file_path in cache_dir.iterdir():
            file_path.unlink()
        cache_dir.rmdir()
        destination = root / "out" / "song.basseparate"
        manifest = write_portable_archive(plan, db, paths, destination, SAVED_AT)
        names = {m.name for m in manifest.members}
        assert not any(
            n.startswith(plan.waveform_caches[0].member_prefix) for n in names
        )
