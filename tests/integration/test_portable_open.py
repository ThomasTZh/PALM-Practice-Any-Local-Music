"""Portable project open pipeline (M2.16, spec §18).

Builds a real M2.15 archive from the M2.14 seed (content-addressed files,
a marker, working state, and stem-mode practice state), then exercises
the §18 open workflow: validation failures, staged extraction, untrusted
database handling, ID remap, optional-member drops, asset restoration,
dedupe, and the single-transaction import.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain.practice import (
    PlaybackMode,
    PracticeLoop,
    PracticeState,
    TrackSettings,
)
from basseparate.domain.project import SelectionRange, ViewportState, WorkingState
from basseparate.portable import open as portable_open
from basseparate.portable.errors import (
    PortableOpenDbInvalid,
    PortableOpenError,
    PortableOpenIdConflict,
)
from basseparate.portable.format import (
    DATABASE_MEMBER,
    MANIFEST_MEMBER,
    ManifestMember,
    PortableManifest,
    category_for,
    compression_for,
    compression_name,
)
from basseparate.portable.open import open_portable_archive
from basseparate.portable.save import perform_portable_save
from basseparate.storage import PortableArtifactRepository, ProjectRepository
from basseparate.storage.db import initialize_database
from basseparate.storage.paths import StoragePaths, resolve_storage_paths
from tests.unit.portable_seed import (
    CAN_HASH_A,
    PB_HASH_A,
    WF_HASH_A,
    Seed,
    create_seed_files,
    seed_two_projects,
)


@dataclass(frozen=True)
class BuiltArchive:
    archive: Path
    seed: Seed
    manifest: PortableManifest
    working_state: WorkingState
    practice_state: PracticeState
    marker_id: uuid.UUID
    loop_id: uuid.UUID


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> BuiltArchive:
    root = tmp_path_factory.mktemp("portable-open-source")
    seed = seed_two_projects(root)
    create_seed_files(root, seed)
    db = root / "data" / "basseparate.db"
    now = datetime.now(UTC)
    marker_id = uuid.uuid4()
    loop_id = uuid.uuid4()
    working_state = WorkingState(
        selection=SelectionRange(start=100, end=2000),
        viewport=ViewportState(start_frame=0, frames_per_css_pixel=64.0),
        monitoring_volume=0.7,
        last_position_frames=12_345,
        follow_playhead=False,
    )
    practice_state = PracticeState(
        playback_mode=PlaybackMode.FOUR_STEMS,
        active_result_set_id=uuid.UUID(seed.rs_a),
        tracks={
            "bass": TrackSettings(
                gain=0.8, mute=False, solo=True, balance=-0.2, display_height=1.2
            )
        },
        master_gain=0.9,
        playback_speed=0.75,
        loops=[
            PracticeLoop(
                id=loop_id,
                name="Chorus",
                start_frames=1000,
                end_frames=5001,
                repeat_count=3,
                created_at=now,
                updated_at=now,
            )
        ],
        active_loop_id=loop_id,
        loop_enabled=True,
    )
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE projects SET working_state = ?, practice_state = ? WHERE id = ?",
            (working_state.model_dump_json(), practice_state.model_dump_json(), seed.project_a),
        )
        stamp = now.isoformat().replace("+00:00", "Z")
        conn.execute(
            "INSERT INTO markers (id, project_id, position_frames, label, color, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(marker_id), seed.project_a, 500, "Verse", "#ff0000", stamp, stamp),
        )
        conn.commit()
    finally:
        conn.close()

    paths = resolve_storage_paths(root)
    repo = ProjectRepository(db)
    artifacts = PortableArtifactRepository(db)
    project = repo.get_project(uuid.UUID(seed.project_a))
    assert project is not None
    artifact, manifest = perform_portable_save(db, paths, project, artifacts)
    return BuiltArchive(
        archive=paths.resolve_asset_path(artifact.relative_path),
        seed=seed,
        manifest=manifest,
        working_state=working_state,
        practice_state=practice_state,
        marker_id=marker_id,
        loop_id=loop_id,
    )


def _new_store(root: Path) -> tuple[StoragePaths, ProjectRepository, Path]:
    root.mkdir(parents=True, exist_ok=True)
    db = root / "data" / "basseparate.db"
    initialize_database(db)
    return resolve_storage_paths(root), ProjectRepository(db), db


def _open(
    archive: Path,
    paths: StoragePaths,
    repo: ProjectRepository,
    *,
    max_uncompressed_bytes: int = 64 << 20,
    max_member_count: int = 10_000,
    **kwargs: object,
):
    kwargs.setdefault("source_filename", "song.basseparate")
    return open_portable_archive(
        archive,
        paths=paths,
        repository=repo,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_member_count=max_member_count,
        **kwargs,
    )


def _read_entries(archive: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(archive) as zf:
        return {
            info.filename: zf.read(info.filename)
            for info in zf.infolist()
            if info.filename != MANIFEST_MEMBER
        }


def _rewrite_archive(
    source: Path,
    destination: Path,
    *,
    replace: dict[str, bytes] | None = None,
    remove: set[str] | None = None,
    add: dict[str, bytes] | None = None,
    sync_manifest: bool = False,
    manifest_bytes: bytes | None = None,
) -> Path:
    """Rebuild an archive with replaced/removed/extra members.

    ``sync_manifest`` recomputes the manifest member records for every
    entry (used for embedded-database tampering). Corruption tests leave
    the manifest untouched so extraction detects the mismatch.
    """
    replace = replace or {}
    remove = remove or set()
    add = add or {}
    with zipfile.ZipFile(source) as zf:
        manifest = PortableManifest.model_validate_json(zf.read(MANIFEST_MEMBER))
        entries = {
            info.filename: zf.read(info.filename)
            for info in zf.infolist()
            if info.filename != MANIFEST_MEMBER
        }
    for name in remove:
        entries.pop(name, None)
    entries.update(replace)
    entries.update(add)
    if manifest_bytes is not None:
        manifest_raw = manifest_bytes
    else:
        if sync_manifest:
            previous = {member.name: member for member in manifest.members}
            members = []
            for name, data in entries.items():
                old = previous.get(name)
                try:
                    compression = compression_name(name)
                    category = category_for(name)
                except ValueError:
                    compression = "stored"
                    category = None
                if category is None:
                    continue
                members.append(
                    ManifestMember(
                        name=name,
                        uncompressed_size_bytes=len(data),
                        sha256=hashlib.sha256(data).hexdigest(),
                        essential=old.essential if old is not None else True,
                        compression=compression,
                        category=category,
                    )
                )
            manifest = manifest.model_copy(update={"members": members})
        manifest_raw = manifest.model_dump_json().encode()
    with zipfile.ZipFile(destination, "w", allowZip64=True) as out:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            try:
                info.compress_type = compression_for(name)
            except ValueError:
                info.compress_type = zipfile.ZIP_STORED
            out.writestr(info, data)
        out.writestr(zipfile.ZipInfo(MANIFEST_MEMBER), manifest_raw)
    return destination


def _rewrite_manifest(
    source: Path, destination: Path, manifest: PortableManifest
) -> Path:
    return _rewrite_archive(
        source, destination, manifest_bytes=manifest.model_dump_json().encode()
    )


def _add_raw_member(
    source: Path,
    destination: Path,
    name: str,
    *,
    data: bytes = b"x",
    mode: int | None = None,
) -> Path:
    with zipfile.ZipFile(source) as zf:
        entries = {
            info.filename: zf.read(info.filename) for info in zf.infolist()
        }
    with zipfile.ZipFile(destination, "w", allowZip64=True) as out:
        for member_name, member_data in entries.items():
            out.writestr(member_name, member_data)
        info = zipfile.ZipInfo(name)
        if mode is not None:
            info.external_attr = mode << 16
        out.writestr(info, data)
    return destination


def _mark_encrypted(archive: Path, member: str) -> Path:
    """Set the ZIP encryption flag bit in both headers of one member."""
    import struct

    raw = bytearray(archive.read_bytes())
    with zipfile.ZipFile(archive) as zf:
        info = zf.getinfo(member)
    offset = info.header_offset
    assert raw[offset : offset + 4] == b"PK\x03\x04"
    flags = struct.unpack_from("<H", raw, offset + 6)[0]
    struct.pack_into("<H", raw, offset + 6, flags | 0x1)
    name_bytes = member.encode()
    start = 0
    while True:
        index = raw.find(b"PK\x01\x02", start)
        if index < 0:
            break
        name_length = struct.unpack_from("<H", raw, index + 28)[0]
        name = bytes(raw[index + 46 : index + 46 + name_length])
        if name == name_bytes:
            flags = struct.unpack_from("<H", raw, index + 8)[0]
            struct.pack_into("<H", raw, index + 8, flags | 0x1)
            break
        start = index + 4
    archive.write_bytes(raw)
    return archive


def _tamper_database(
    source: Path, destination: Path, mutate
) -> Path:
    with zipfile.ZipFile(source) as zf:
        db_bytes = zf.read(DATABASE_MEMBER)
    scratch = destination.parent / f"{destination.name}.sqlite"
    scratch.write_bytes(db_bytes)
    conn = sqlite3.connect(scratch)
    try:
        mutate(conn)
        conn.commit()
    finally:
        conn.close()
    patched = scratch.read_bytes()
    scratch.unlink()
    return _rewrite_archive(
        source, destination, replace={DATABASE_MEMBER: patched}, sync_manifest=True
    )


def _member_for(built: BuiltArchive, role: str, content_hash: str) -> str:
    for entry in built.manifest.assets:
        if entry.role == role and entry.content_hash == content_hash:
            return entry.member
    raise AssertionError(f"no manifest asset for {role} {content_hash}")


def _cache_members(built: BuiltArchive) -> list[str]:
    prefix = f"caches/waveforms/{WF_HASH_A}/"
    return [m.name for m in built.manifest.members if m.name.startswith(prefix)]


def _project_count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    finally:
        conn.close()


def _table_count(db: Path, table: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def _staged_dirs(paths: StoragePaths) -> list[Path]:
    root = paths.data / "portable" / ".import-staging"
    return sorted(root.iterdir()) if root.is_dir() else []


# ---------------------------------------------------------------------------
# Happy path and state restoration
# ---------------------------------------------------------------------------


class TestOpenSuccess:
    def test_restores_project_and_state(self, built: BuiltArchive, tmp_path: Path) -> None:
        paths, repo, db = _new_store(tmp_path / "store")
        opened = _open(built.archive, paths, repo)

        assert opened.name == "Song A"
        assert opened.status.value == "ready"
        assert opened.revision == 5
        assert opened.id != uuid.UUID(built.seed.project_a)
        assert opened.id != uuid.UUID(built.seed.project_b)
        # New working copy: fresh asset rows, so fresh asset ids.
        assert opened.source_asset_id is not None
        assert opened.source_asset_id != uuid.UUID(built.seed.src_a)
        assert opened.canonical_asset_id is not None
        assert opened.monitoring_asset_id is not None

        # §18.7: working state, markers, practice state (mixer, speed,
        # active result set, loops).
        assert opened.working_state == built.working_state
        assert len(opened.markers) == 1
        marker = opened.markers[0]
        assert marker.label == "Verse"
        assert marker.position_frames == 500
        assert marker.color == "#ff0000"
        assert marker.project_id == opened.id
        practice = opened.practice_state
        assert practice.playback_mode is PlaybackMode.FOUR_STEMS
        assert practice.master_gain == 0.9
        assert practice.playback_speed == 0.75
        assert practice.tracks["bass"] == built.practice_state.tracks["bass"]
        assert len(practice.loops) == 1
        assert practice.loops[0].id == built.loop_id  # loop ids are project-local
        assert practice.active_loop_id == built.loop_id
        assert practice.active_result_set_id is not None
        assert practice.active_result_set_id != uuid.UUID(built.seed.rs_a)
        # The active result set exists in the opened project.
        conn = sqlite3.connect(db)
        try:
            result_set_ids = {
                row[0]
                for row in conn.execute("SELECT id FROM separation_result_sets")
            }
        finally:
            conn.close()
        assert str(practice.active_result_set_id) in result_set_ids

    def test_restores_all_asset_files(
        self, built: BuiltArchive, tmp_path: Path
    ) -> None:
        paths, repo, db = _new_store(tmp_path / "store")
        opened = _open(built.archive, paths, repo)

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM assets").fetchall()
            assert {row["content_hash"] for row in rows} == {
                entry.content_hash for entry in built.manifest.assets
            }
            for row in rows:
                stored = paths.resolve_asset_path(row["relative_path"])
                assert stored.is_file(), row["relative_path"]
                digest = hashlib.sha256(stored.read_bytes()).hexdigest()
                assert digest == row["content_hash"]
            # The source original follows the new working copy's import id.
            import_id = conn.execute("SELECT id FROM imports").fetchone()[0]
            source = conn.execute(
                "SELECT relative_path FROM assets WHERE id = ?",
                (str(opened.source_asset_id),),
            ).fetchone()
            assert source["relative_path"] == f"runtime/uploads/{import_id}.part"
        finally:
            conn.close()

        # Waveform cache tree restored under cache/waveforms/<source_hash>.
        cache_dir = paths.cache / "waveforms" / WF_HASH_A
        assert (cache_dir / "manifest.json").is_file()
        assert (cache_dir / "tile0.bin").is_file()
        assert _table_count(db, "waveform_caches") == 1

        # No staging debris.
        assert _staged_dirs(paths) == []

    def test_provenance_recorded(self, built: BuiltArchive, tmp_path: Path) -> None:
        paths, repo, db = _new_store(tmp_path / "store")
        _open(built.archive, paths, repo)
        conn = sqlite3.connect(db)
        try:
            raw = conn.execute("SELECT portable_provenance FROM projects").fetchone()[0]
        finally:
            conn.close()
        provenance = json.loads(raw)
        assert provenance["archived_project_id"] == built.seed.project_a
        assert provenance["saved_revision"] == 5
        assert provenance["source_filename"] == "song.basseparate"
        assert provenance["saved_at"].endswith("Z")

    def test_new_copy_gets_new_ids(self, built: BuiltArchive, tmp_path: Path) -> None:
        paths, repo, db = _new_store(tmp_path / "store")
        opened = _open(built.archive, paths, repo)
        conn = sqlite3.connect(db)
        try:
            asset_ids = {row[0] for row in conn.execute("SELECT id FROM assets")}
            run_ids = {row[0] for row in conn.execute("SELECT id FROM separation_runs")}
            stem_ids = {row[0] for row in conn.execute("SELECT id FROM stems")}
            import_ids = {row[0] for row in conn.execute("SELECT id FROM imports")}
        finally:
            conn.close()
        assert built.seed.src_a not in asset_ids
        assert built.seed.can_a not in asset_ids
        assert built.seed.run_a not in run_ids
        assert str(opened.practice_state.active_result_set_id) != built.seed.rs_a
        assert len(stem_ids) == 2
        assert len(import_ids) == 1
        # The imported records keep their content (stems remapped to the
        # new project/result-set ids).
        conn = sqlite3.connect(db)
        try:
            for row in conn.execute("SELECT record_json FROM stems"):
                record = json.loads(row[0])
                assert record["result_set_id"] == str(
                    opened.practice_state.active_result_set_id
                )
        finally:
            conn.close()

    def test_name_override(self, built: BuiltArchive, tmp_path: Path) -> None:
        paths, repo, _db = _new_store(tmp_path / "store")
        opened = _open(built.archive, paths, repo, project_name="My Copy")
        assert opened.name == "My Copy"

    def test_second_open_reuses_global_rows(
        self, built: BuiltArchive, tmp_path: Path
    ) -> None:
        paths, repo, db = _new_store(tmp_path / "store")
        first = _open(built.archive, paths, repo)
        counts_before = {
            table: _table_count(db, table)
            for table in ("assets", "representations", "waveform_caches")
        }
        second = _open(built.archive, paths, repo)
        assert second.id != first.id
        for table, count in counts_before.items():
            assert _table_count(db, table) == count
        assert first.source_asset_id == second.source_asset_id
        assert _table_count(db, "projects") == 2
        assert _table_count(db, "imports") == 2
        # One shared upload file (the source original is content-addressed).
        assert len(list((paths.runtime / "uploads").iterdir())) == 1

    def test_as_archived_keeps_ids(self, built: BuiltArchive, tmp_path: Path) -> None:
        paths, repo, db = _new_store(tmp_path / "store")
        opened = _open(built.archive, paths, repo, open_mode="as-archived")
        assert str(opened.id) == built.seed.project_a
        assert str(opened.source_asset_id) == built.seed.src_a
        assert str(opened.canonical_asset_id) == built.seed.can_a
        conn = sqlite3.connect(db)
        try:
            asset_ids = {row[0] for row in conn.execute("SELECT id FROM assets")}
        finally:
            conn.close()
        assert built.seed.src_a in asset_ids

    def test_as_archived_conflicts(self, built: BuiltArchive, tmp_path: Path) -> None:
        paths, repo, db = _new_store(tmp_path / "store")
        _open(built.archive, paths, repo, open_mode="as-archived")
        with pytest.raises(PortableOpenIdConflict) as excinfo:
            _open(built.archive, paths, repo, open_mode="as-archived")
        assert excinfo.value.code == "OPEN_ID_CONFLICT"
        assert _table_count(db, "projects") == 1


# ---------------------------------------------------------------------------
# Optional-member failures (§18.6)
# ---------------------------------------------------------------------------


class TestOptionalMembers:
    @pytest.mark.parametrize("mode", ["missing", "corrupt"])
    def test_absent_playback_asset_is_dropped(
        self, built: BuiltArchive, tmp_path: Path, mode: str
    ) -> None:
        member = _member_for(built, "derived_pcm", PB_HASH_A)
        if mode == "missing":
            patched = _rewrite_archive(built.archive, tmp_path / "patched.zip", remove={member})
        else:
            patched = _rewrite_archive(
                built.archive, tmp_path / "patched.zip", replace={member: b"corrupt"}
            )
        paths, repo, db = _new_store(tmp_path / "store")
        opened = _open(patched, paths, repo)

        conn = sqlite3.connect(db)
        try:
            hashes = {row[0] for row in conn.execute("SELECT content_hash FROM assets")}
            playback_rows = conn.execute(
                "SELECT COUNT(*) FROM representations WHERE role = 'playback_rate'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert PB_HASH_A not in hashes
        assert opened.canonical_asset_id is not None
        assert playback_rows == 0
        assert _table_count(db, "assets") == 6

    def test_incomplete_cache_tree_is_dropped(
        self, built: BuiltArchive, tmp_path: Path
    ) -> None:
        tile = next(m for m in _cache_members(built) if m.endswith("tile0.bin"))
        patched = _rewrite_archive(built.archive, tmp_path / "patched.zip", remove={tile})
        paths, repo, db = _new_store(tmp_path / "store")
        _open(patched, paths, repo)
        assert _table_count(db, "waveform_caches") == 0
        assert _table_count(db, "assets") == 7

    def test_absent_cache_tree_is_dropped(
        self, built: BuiltArchive, tmp_path: Path
    ) -> None:
        patched = _rewrite_archive(
            built.archive, tmp_path / "patched.zip", remove=set(_cache_members(built))
        )
        paths, repo, db = _new_store(tmp_path / "store")
        _open(patched, paths, repo)
        assert _table_count(db, "waveform_caches") == 0


# ---------------------------------------------------------------------------
# §18.2 validation failures
# ---------------------------------------------------------------------------


class TestValidationFailures:
    def _expect_failure(self, tmp_path: Path, archive: Path, code: str, **kwargs):
        paths, repo, db = _new_store(tmp_path / "store")
        with pytest.raises(PortableOpenError) as excinfo:
            _open(archive, paths, repo, **kwargs)
        assert excinfo.value.code == code
        assert _project_count(db) == 0
        assert _staged_dirs(paths) == []
        return excinfo.value

    def test_not_zip(self, tmp_path: Path) -> None:
        bogus = tmp_path / "bogus.basseparate"
        bogus.write_bytes(b"not a zip file")
        self._expect_failure(tmp_path, bogus, "ARCHIVE_NOT_ZIP")

    def test_member_limit(self, built: BuiltArchive, tmp_path: Path) -> None:
        self._expect_failure(tmp_path, built.archive, "ARCHIVE_MEMBER_LIMIT", max_member_count=3)

    def test_uncompressed_limit(self, built: BuiltArchive, tmp_path: Path) -> None:
        self._expect_failure(
            tmp_path, built.archive, "ARCHIVE_UNCOMPRESSED_LIMIT", max_uncompressed_bytes=1024
        )

    def test_oversized_manifest(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _rewrite_archive(
            built.archive,
            tmp_path / "patched.zip",
            manifest_bytes=b"x" * ((1 << 20) + 1),
        )
        self._expect_failure(tmp_path, patched, "ARCHIVE_MANIFEST_INVALID")

    def test_invalid_manifest(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _rewrite_archive(
            built.archive, tmp_path / "patched.zip", manifest_bytes=b"{not json"
        )
        self._expect_failure(tmp_path, patched, "ARCHIVE_MANIFEST_INVALID")

    def test_wrong_format_id(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _rewrite_manifest(
            built.archive,
            tmp_path / "patched.zip",
            built.manifest.model_copy(update={"format_id": "other.format"}),
        )
        self._expect_failure(tmp_path, patched, "ARCHIVE_VERSION_UNSUPPORTED")

    def test_wrong_container_version(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _rewrite_manifest(
            built.archive,
            tmp_path / "patched.zip",
            built.manifest.model_copy(update={"container_version": 99}),
        )
        self._expect_failure(tmp_path, patched, "ARCHIVE_VERSION_UNSUPPORTED")

    def test_wrong_project_schema_version(
        self, built: BuiltArchive, tmp_path: Path
    ) -> None:
        patched = _rewrite_manifest(
            built.archive,
            tmp_path / "patched.zip",
            built.manifest.model_copy(update={"project_schema_version": 99}),
        )
        self._expect_failure(tmp_path, patched, "ARCHIVE_VERSION_UNSUPPORTED")

    def test_absolute_member(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _add_raw_member(built.archive, tmp_path / "patched.zip", "/abs.bin")
        exc = self._expect_failure(tmp_path, patched, "ARCHIVE_MEMBER_UNSAFE")
        assert "absolute" in str(exc)

    def test_traversal_member(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _add_raw_member(built.archive, tmp_path / "patched.zip", "../evil.bin")
        exc = self._expect_failure(tmp_path, patched, "ARCHIVE_MEMBER_UNSAFE")
        assert "traversal" in str(exc)

    def test_symlink_member(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _add_raw_member(
            built.archive, tmp_path / "patched.zip", "link", mode=0o120777
        )
        exc = self._expect_failure(tmp_path, patched, "ARCHIVE_MEMBER_UNSAFE")
        assert "symlink" in str(exc)

    def test_encrypted_member(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _add_raw_member(
            built.archive, tmp_path / "patched.zip", "secret.bin", data=b"secret"
        )
        _mark_encrypted(patched, "secret.bin")
        exc = self._expect_failure(tmp_path, patched, "ARCHIVE_MEMBER_UNSAFE")
        assert "encrypted" in str(exc)

    def test_directory_entry(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _add_raw_member(
            built.archive, tmp_path / "patched.zip", "junk/", mode=0o040755
        )
        exc = self._expect_failure(tmp_path, patched, "ARCHIVE_MEMBER_UNSAFE")
        assert "directory" in str(exc)

    def test_duplicate_member(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _add_raw_member(
            built.archive, tmp_path / "patched.zip", DATABASE_MEMBER, data=b"duplicate"
        )
        self._expect_failure(tmp_path, patched, "ARCHIVE_MEMBER_UNSAFE")

    def test_stray_member(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _add_raw_member(
            built.archive, tmp_path / "patched.zip", "stray.bin", data=b"stray"
        )
        self._expect_failure(tmp_path, patched, "ARCHIVE_MEMBER_UNSAFE")

    def test_missing_essential(self, built: BuiltArchive, tmp_path: Path) -> None:
        member = _member_for(built, "source_pcm", CAN_HASH_A)
        patched = _rewrite_archive(built.archive, tmp_path / "patched.zip", remove={member})
        exc = self._expect_failure(tmp_path, patched, "ARCHIVE_MEMBER_MISSING")
        assert exc.details["missing"] == [member]

    def test_corrupt_essential(self, built: BuiltArchive, tmp_path: Path) -> None:
        member = _member_for(built, "source_pcm", CAN_HASH_A)
        patched = _rewrite_archive(
            built.archive, tmp_path / "patched.zip", replace={member: b"corrupt"}
        )
        exc = self._expect_failure(tmp_path, patched, "ARCHIVE_MEMBER_CORRUPT")
        assert exc.details["member"] == member

    def test_member_hash_must_match_asset_row(
        self, built: BuiltArchive, tmp_path: Path
    ) -> None:
        member = _member_for(built, "source_pcm", CAN_HASH_A)
        patched = _rewrite_archive(
            built.archive,
            tmp_path / "patched.zip",
            replace={member: b"other bytes"},
            sync_manifest=True,
        )
        self._expect_failure(tmp_path, patched, "ARCHIVE_MANIFEST_INVALID")

    def test_no_space(
        self, built: BuiltArchive, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(portable_open, "_free_bytes", lambda path: 0)
        self._expect_failure(tmp_path, built.archive, "OPEN_NO_SPACE")


# ---------------------------------------------------------------------------
# §18.3 untrusted embedded database
# ---------------------------------------------------------------------------


class TestDatabaseValidation:
    def _expect_failure(self, tmp_path: Path, archive: Path, code: str):
        paths, repo, db = _new_store(tmp_path / "store")
        with pytest.raises(PortableOpenError) as excinfo:
            _open(archive, paths, repo)
        assert excinfo.value.code == code
        assert _project_count(db) == 0
        assert _staged_dirs(paths) == []
        return excinfo.value

    def test_schema_mismatch(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _tamper_database(
            built.archive,
            tmp_path / "patched.zip",
            lambda conn: conn.execute("PRAGMA user_version = 3"),
        )
        exc = self._expect_failure(tmp_path, patched, "ARCHIVE_SCHEMA_MISMATCH")
        assert exc.details["version"] == 3

    def test_missing_table(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _tamper_database(
            built.archive,
            tmp_path / "patched.zip",
            lambda conn: conn.execute("DROP TABLE media_jobs"),
        )
        exc = self._expect_failure(tmp_path, patched, "ARCHIVE_DB_INVALID")
        assert "media_jobs" in str(exc)

    def test_multiple_projects(self, built: BuiltArchive, tmp_path: Path) -> None:
        def mutate(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO projects (id, name, created_at, updated_at) "
                "VALUES ('other-project', 'Other', '2020-01-01T00:00:00Z', "
                "'2020-01-01T00:00:00Z')"
            )

        patched = _tamper_database(built.archive, tmp_path / "patched.zip", mutate)
        self._expect_failure(tmp_path, patched, "ARCHIVE_DB_INVALID")

    def test_dangling_asset_reference(self, built: BuiltArchive, tmp_path: Path) -> None:
        missing = str(uuid.uuid4())

        def mutate(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE projects SET source_asset_id = ?", (missing,)
            )

        patched = _tamper_database(built.archive, tmp_path / "patched.zip", mutate)
        exc = self._expect_failure(tmp_path, patched, "ARCHIVE_DB_INVALID")
        assert missing in str(exc)

    def test_malformed_record_json(self, built: BuiltArchive, tmp_path: Path) -> None:
        patched = _tamper_database(
            built.archive,
            tmp_path / "patched.zip",
            lambda conn: conn.execute(
                "UPDATE separation_runs SET record_json = '{}'"
            ),
        )
        self._expect_failure(tmp_path, patched, "ARCHIVE_DB_INVALID")

    def test_asset_hash_mismatch(self, built: BuiltArchive, tmp_path: Path) -> None:
        def mutate(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE assets SET content_hash = ? WHERE content_hash = ?",
                ("f" * 64, CAN_HASH_A),
            )

        patched = _tamper_database(built.archive, tmp_path / "patched.zip", mutate)
        self._expect_failure(tmp_path, patched, "ARCHIVE_MANIFEST_INVALID")


# ---------------------------------------------------------------------------
# §18.4 single-transaction import
# ---------------------------------------------------------------------------


class TestImportTransaction:
    def test_failed_import_rolls_back_all_rows(
        self, built: BuiltArchive, tmp_path: Path
    ) -> None:
        paths, repo, db = _new_store(tmp_path / "store")
        # Plant an unrelated asset row that collides with an archived
        # asset id, forcing an IntegrityError mid-import (as-archived).
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "INSERT INTO assets (id, content_hash, role, relative_path, "
                "media_type, byte_count, created_at) VALUES (?, ?, 'source_pcm', "
                "'data/assets/x.pcm', 'audio/pcm', 1, '2020-01-01T00:00:00Z')",
                (built.seed.src_a, "f" * 64),
            )
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(PortableOpenDbInvalid):
            _open(built.archive, paths, repo, open_mode="as-archived")
        assert repo.list_projects() == []
        assert _table_count(db, "assets") == 1
        assert _table_count(db, "imports") == 0
        assert _table_count(db, "media_jobs") == 0
        assert _staged_dirs(paths) == []
