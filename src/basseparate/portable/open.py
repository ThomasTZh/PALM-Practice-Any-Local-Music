"""Portable project open pipeline (M2.16, spec §18).

Opens a ``.basseparate`` archive produced by the M2.15 save pipeline into
the working store as a new, playable project:

1. Validate before import (§18.2): ZIP directory, member-count and
   uncompressed-size limits, bounded manifest read, format/container
   version checks, path safety (absolute/traversal/symlink/encrypted/
   directory/duplicate), member-set equality with the manifest, and
   essential-member presence. No ``extractall()``.
2. Staged extraction: every manifest member is streamed in 1 MiB chunks
   with a running SHA-256 into ``data/portable/.import-staging/<uuid>/``
   (partial file + atomic rename). A corrupted *essential* member fails
   the open; a corrupted or missing *optional* member is dropped and
   treated as absent (§18.6).
3. Untrusted embedded database (§18.3): opened read-only with loadable
   extensions disabled, ``user_version`` must equal the current schema
   version, the expected tables must exist, and every row is validated
   through the application domain models. No SQL text from the archive
   is ever executed.
4. ID policy (§18.5): the default ``new-copy`` mode gives the working
   copy a new project ID and a new ID for every row, remapping all FK
   references and the IDs embedded in ``record_json`` blobs. ``as-archived``
   keeps the original IDs and is only allowed when the archived project
   ID is absent from the store.
5. Asset restoration (§18.4): content-addressed objects are deduplicated
   by hash (an existing identical file is reused, a collision rejects),
   and the DB import is a single transaction — the project is exposed
   only after that commit.

The source archive is never modified; store writes are the new working
copy's rows and the (deduplicated) asset files it needs.
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import sqlite3
import uuid
import zipfile
import zlib
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import quote

from basseparate import DATABASE_SCHEMA_VERSION, PROJECT_SCHEMA_VERSION
from basseparate.domain.asset import AssetRecord, AssetRole
from basseparate.domain.import_record import ImportRecord
from basseparate.domain.marker import MarkerRecord
from basseparate.domain.media_job import MediaJob
from basseparate.domain.project import ProjectRecord
from basseparate.domain.representation import AudioRepresentation
from basseparate.domain.separation import (
    SeparationResultSet,
    SeparationRun,
    StemRecord,
)
from basseparate.domain.waveform import WaveformCacheRecord
from basseparate.portable.bundle import AssetLink, HistoryRow, PortableImportBundle
from basseparate.portable.errors import (
    PortableOpenDbInvalid,
    PortableOpenIdConflict,
    PortableOpenManifestInvalid,
    PortableOpenMemberCorrupt,
    PortableOpenMemberLimit,
    PortableOpenMemberMissing,
    PortableOpenMemberUnsafe,
    PortableOpenNoSpace,
    PortableOpenNotZip,
    PortableOpenSchemaMismatch,
    PortableOpenUncompressedLimit,
    PortableOpenVersionUnsupported,
)
from basseparate.portable.format import (
    CONTAINER_VERSION,
    DATABASE_MEMBER,
    FORMAT_ID,
    MANIFEST_MEMBER,
    WAVEFORM_CACHE_PREFIX,
    MemberCategory,
    PortableManifest,
    category_for,
)
from basseparate.storage.paths import StoragePaths
from basseparate.storage.repository import (
    ProjectRepository,
    _row_to_asset,
    _row_to_import,
    _row_to_job,
    _row_to_marker,
    _row_to_project,
    _row_to_representation,
    _row_to_waveform_cache,
)

#: Bounded manifest read (§18.2.3): the manifest is metadata, never media.
_MAX_MANIFEST_BYTES = 1 << 20
#: Streamed read/hash/copy chunk size.
_STREAM_CHUNK = 1 << 20
#: Free-space margins for the data and runtime roots.
_SPACE_MARGIN_DATA = 1 << 30  # 1 GiB
_SPACE_MARGIN_RUNTIME = 64 << 20  # 64 MiB
#: Staging subdirectory under the data root (removed after every open).
_STAGING_SUBDIR = ".import-staging"

#: Tables the embedded database must contain (§18.3.2).
_REQUIRED_TABLES = frozenset(
    {
        "projects",
        "assets",
        "project_assets",
        "imports",
        "representations",
        "waveform_caches",
        "markers",
        "project_history",
        "separation_runs",
        "separation_result_sets",
        "stems",
        "media_jobs",
    }
)

#: POSIX file-type bits in the ZIP external-attribute high word.
_S_IFMT = 0o170000
_S_IFLNK = 0o120000
#: ZIP general-purpose flag bit 0: encrypted member.
_FLAG_ENCRYPTED = 0x1
#: Members that are not listed in ``manifest.members`` (the manifest
#: never lists itself; the database is an ordinary declared member).
_FIXED_MEMBERS = frozenset({MANIFEST_MEMBER})

OpenMode = Literal["new-copy", "as-archived"]


# ---------------------------------------------------------------------------
# Internal row containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PortableRows:
    """The untrusted rows read from the embedded database (pre-remap)."""

    project: ProjectRecord
    assets: tuple[AssetRecord, ...]
    asset_links: tuple[AssetLink, ...]
    imports: tuple[ImportRecord, ...]
    representations: tuple[AudioRepresentation, ...]
    waveform_caches: tuple[WaveformCacheRecord, ...]
    markers: tuple[MarkerRecord, ...]
    history: tuple[HistoryRow, ...]
    runs: tuple[SeparationRun, ...]
    result_sets: tuple[SeparationResultSet, ...]
    stems: tuple[StemRecord, ...]
    jobs: tuple[MediaJob, ...]
    #: ``projects.history_seq`` pointer (undo/redo position, §17.4).
    history_seq: int


@dataclass(frozen=True)
class _IdMaps:
    """Old→new ID maps for every row ID space in the archive."""

    project: dict[str, str]
    asset: dict[str, str]
    import_row: dict[str, str]
    run: dict[str, str]
    result_set: dict[str, str]
    stem: dict[str, str]
    job: dict[str, str]
    marker: dict[str, str]
    waveform: dict[str, str]
    history: dict[str, str]

    @property
    def all(self) -> dict[str, str]:
        """The union of every space (disjoint UUID spaces; safe to merge)."""
        merged: dict[str, str] = {}
        for space in (
            self.project,
            self.asset,
            self.import_row,
            self.run,
            self.result_set,
            self.stem,
            self.job,
            self.marker,
            self.waveform,
            self.history,
        ):
            merged.update(space)
        return merged


# ---------------------------------------------------------------------------
# §18.2 — validate before import
# ---------------------------------------------------------------------------


def _validate_archive(
    archive_path: Path,
    *,
    max_uncompressed_bytes: int,
    max_member_count: int,
) -> tuple[PortableManifest, dict[str, zipfile.ZipInfo]]:
    """Steps 1–8 of §18.2: return the validated manifest and member infos.

    The archive is opened and closed here; extraction reopens it. No
    destination path is derived from archive content before validation.
    """
    try:
        zf = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise PortableOpenNotZip(str(exc)) from exc
    except OSError as exc:
        raise PortableOpenNotZip(f"cannot read archive: {exc}") from exc
    with zf:
        return _validate_open_zip(
            zf,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_member_count=max_member_count,
        )


def _validate_open_zip(
    zf: zipfile.ZipFile,
    *,
    max_uncompressed_bytes: int,
    max_member_count: int,
) -> tuple[PortableManifest, dict[str, zipfile.ZipInfo]]:
    infos: dict[str, zipfile.ZipInfo] = {}
    for info in zf.infolist():
        if info.filename in infos:
            raise PortableOpenMemberUnsafe(info.filename, "duplicate member name")
        infos[info.filename] = info

    if len(infos) > max_member_count:
        raise PortableOpenMemberLimit(len(infos), max_member_count)
    total = sum(info.file_size for info in infos.values())
    if total > max_uncompressed_bytes:
        raise PortableOpenUncompressedLimit(total, max_uncompressed_bytes)

    # Bounded manifest read.
    if MANIFEST_MEMBER not in infos:
        raise PortableOpenManifestInvalid("manifest.json missing from archive")
    manifest_info = infos[MANIFEST_MEMBER]
    if manifest_info.file_size > _MAX_MANIFEST_BYTES:
        raise PortableOpenManifestInvalid(
            f"manifest.json is {manifest_info.file_size} bytes, "
            f"limit is {_MAX_MANIFEST_BYTES}"
        )
    try:
        raw_manifest = zf.read(MANIFEST_MEMBER)
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise PortableOpenManifestInvalid(f"manifest.json is unreadable: {exc}") from exc
    try:
        manifest = PortableManifest.model_validate_json(raw_manifest.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PortableOpenManifestInvalid(f"manifest failed validation: {exc}") from exc

    # Versions.
    if manifest.format_id != FORMAT_ID:
        raise PortableOpenVersionUnsupported(
            f"format_id {manifest.format_id!r} != {FORMAT_ID!r}"
        )
    if manifest.container_version != CONTAINER_VERSION:
        raise PortableOpenVersionUnsupported(
            f"container_version {manifest.container_version} != {CONTAINER_VERSION}"
        )
    if not 1 <= manifest.project_schema_version <= PROJECT_SCHEMA_VERSION:
        raise PortableOpenVersionUnsupported(
            f"project_schema_version {manifest.project_schema_version} is "
            f"outside 1..{PROJECT_SCHEMA_VERSION}"
        )

    # Member safety: every physical member, then every declared member
    # (a declared member may be absent only when optional).
    seen: set[str] = set()
    for name, info in infos.items():
        _check_member_safe(name, info, seen)
    declared_seen: set[str] = set()
    for member in manifest.members:
        _check_member_safe(member.name, infos.get(member.name), declared_seen)
        try:
            category = category_for(member.name)
        except ValueError as exc:
            raise PortableOpenMemberUnsafe(member.name, str(exc)) from exc
        if category != member.category:
            raise PortableOpenMemberUnsafe(
                member.name,
                f"category {member.category.value} does not match path "
                f"({category.value})",
            )

    # Member-set equality: no stray members; essentials must be present;
    # absent optional members are allowed (treated as absent, §18.6).
    declared_names = {m.name for m in manifest.members}
    stray = sorted(set(infos) - declared_names - _FIXED_MEMBERS)
    if stray:
        raise PortableOpenMemberUnsafe(
            stray[0],
            f"archive member not listed in the manifest (stray: {stray[:3]})",
        )
    missing = declared_names - set(infos)
    essential_missing = [
        m.name for m in manifest.members if m.essential and m.name in missing
    ]
    if essential_missing:
        raise PortableOpenMemberMissing(essential_missing)
    return manifest, infos


def _check_member_safe(
    name: str, info: zipfile.ZipInfo | None, seen: set[str]
) -> None:
    """Reject unsafe member names and types (spec §18.2.5–7)."""
    if not name:
        raise PortableOpenMemberUnsafe(name, "empty member name")
    if name.startswith("/") or name.startswith("\\"):
        raise PortableOpenMemberUnsafe(name, "absolute path")
    if "\x00" in name:
        raise PortableOpenMemberUnsafe(name, "NUL byte in member name")
    if name.endswith("/"):
        raise PortableOpenMemberUnsafe(name, "directory entries are not allowed")
    if ".." in PurePosixPath(name).parts:
        raise PortableOpenMemberUnsafe(name, "traversal component")
    normalized = str(PurePosixPath(name))
    if normalized in seen:
        raise PortableOpenMemberUnsafe(name, "duplicate member after normalization")
    seen.add(normalized)
    if info is None:
        return
    if info.is_dir():
        raise PortableOpenMemberUnsafe(name, "directory entries are not allowed")
    if (info.external_attr >> 16) & _S_IFMT == _S_IFLNK:
        raise PortableOpenMemberUnsafe(name, "symlink members are not allowed")
    if info.flag_bits & _FLAG_ENCRYPTED:
        raise PortableOpenMemberUnsafe(name, "encrypted members are not allowed")


# ---------------------------------------------------------------------------
# Staged extraction (streamed, hashed)
# ---------------------------------------------------------------------------


def _extract_staged(
    archive_path: Path,
    manifest: PortableManifest,
    infos: dict[str, zipfile.ZipInfo],
    staging: Path,
) -> set[str]:
    """Extract the manifest members into ``staging``; return present names.

    Essential members must extract cleanly (size + SHA-256 per the
    manifest); a failing essential member raises
    :class:`PortableOpenMemberCorrupt`. Optional members that are absent
    or corrupt are simply not present in the returned set (§18.6).
    """
    present: set[str] = set()
    with zipfile.ZipFile(archive_path) as zf:
        for member in manifest.members:
            if member.name not in infos:
                if member.essential:
                    # Cannot happen: essential presence is checked up front.
                    raise PortableOpenMemberMissing([member.name])
                continue
            target = staging / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.parent / (target.name + ".partial")
            digest = hashlib.sha256()
            size = 0
            try:
                with zf.open(member.name) as source, partial.open("wb") as out:
                    while chunk := source.read(_STREAM_CHUNK):
                        size += len(chunk)
                        digest.update(chunk)
                        out.write(chunk)
            except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
                with contextlib.suppress(OSError):
                    partial.unlink()
                if member.essential:
                    raise PortableOpenMemberCorrupt(
                        member.name, f"cannot decompress: {exc}"
                    ) from exc
                continue
            if size != member.uncompressed_size_bytes:
                with contextlib.suppress(OSError):
                    partial.unlink()
                if member.essential:
                    raise PortableOpenMemberCorrupt(
                        member.name,
                        f"size {size} != declared {member.uncompressed_size_bytes}",
                    )
                continue
            actual_hash = digest.hexdigest()
            if actual_hash != member.sha256:
                with contextlib.suppress(OSError):
                    partial.unlink()
                if member.essential:
                    raise PortableOpenMemberCorrupt(
                        member.name, "sha256 mismatch"
                    )
                continue
            partial.replace(target)
            present.add(member.name)
    return present


# ---------------------------------------------------------------------------
# §18.3 — untrusted embedded database
# ---------------------------------------------------------------------------


def _read_database(db_file: Path) -> _PortableRows:
    """Read and validate the embedded project-only database (read-only)."""
    if not db_file.is_file():
        raise PortableOpenDbInvalid("project.sqlite missing after extraction")
    uri = "file:" + quote(str(db_file), safe="/") + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise PortableOpenDbInvalid(f"cannot open the embedded database: {exc}") from exc
    try:
        try:
            # Loadable extensions are off by default in CPython's sqlite3;
            # disable them explicitly. The archive never supplies SQL text.
            conn.enable_load_extension(False)
            conn.execute("PRAGMA query_only = ON")
            conn.row_factory = sqlite3.Row
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        except sqlite3.Error as exc:
            raise PortableOpenDbInvalid(f"cannot read the embedded database: {exc}") from exc
        if version != DATABASE_SCHEMA_VERSION:
            raise PortableOpenSchemaMismatch(version, DATABASE_SCHEMA_VERSION)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        missing_tables = sorted(_REQUIRED_TABLES - tables)
        if missing_tables:
            raise PortableOpenDbInvalid(f"missing tables: {missing_tables}")
        try:
            return _read_database_rows(conn)
        except PortableOpenDbInvalid:
            raise
        except Exception as exc:
            raise PortableOpenDbInvalid(f"row validation failed: {exc}") from exc
    finally:
        conn.close()


def _read_database_rows(conn: sqlite3.Connection) -> _PortableRows:
    project_rows = conn.execute("SELECT * FROM projects").fetchall()
    if len(project_rows) != 1:
        raise PortableOpenDbInvalid(
            f"expected exactly one project row, found {len(project_rows)}"
        )
    project = _row_to_project(project_rows[0])
    history_seq = int(project_rows[0]["history_seq"])
    assets = tuple(_row_to_asset(row) for row in conn.execute("SELECT * FROM assets"))
    asset_links: tuple[AssetLink, ...] = tuple(
        (row["project_id"], row["asset_id"], row["role"])
        for row in conn.execute("SELECT project_id, asset_id, role FROM project_assets")
    )
    imports = tuple(_row_to_import(row) for row in conn.execute("SELECT * FROM imports"))
    representations = tuple(
        _row_to_representation(row)
        for row in conn.execute(
            "SELECT r.*, a.content_hash FROM representations r "
            "JOIN assets a ON a.id = r.asset_id"
        )
    )
    waveform_caches = tuple(
        _row_to_waveform_cache(row) for row in conn.execute("SELECT * FROM waveform_caches")
    )
    markers = tuple(_row_to_marker(row) for row in conn.execute("SELECT * FROM markers"))
    history = tuple(
        HistoryRow(
            id=row["id"],
            project_id=row["project_id"],
            seq=row["seq"],
            kind=row["kind"],
            before_json=row["before_json"],
            after_json=row["after_json"],
            created_at=row["created_at"],
        )
        for row in conn.execute("SELECT * FROM project_history")
    )
    runs = tuple(
        SeparationRun.model_validate_json(row["record_json"])
        for row in conn.execute("SELECT record_json FROM separation_runs")
    )
    result_sets = tuple(
        SeparationResultSet.model_validate_json(row["record_json"])
        for row in conn.execute("SELECT record_json FROM separation_result_sets")
    )
    stems = tuple(
        StemRecord.model_validate_json(row["record_json"])
        for row in conn.execute("SELECT record_json FROM stems")
    )
    jobs = tuple(_row_to_job(row) for row in conn.execute("SELECT * FROM media_jobs"))
    return _PortableRows(
        project=project,
        assets=assets,
        asset_links=asset_links,
        imports=imports,
        representations=representations,
        waveform_caches=waveform_caches,
        markers=markers,
        history=history,
        runs=runs,
        result_sets=result_sets,
        stems=stems,
        jobs=jobs,
        history_seq=history_seq,
    )


def _check_isolation(rows: _PortableRows) -> None:
    """Re-prove the portable database's isolation on the read side (§18.3)."""
    project_id = str(rows.project.id)
    asset_ids = {str(asset.id) for asset in rows.assets}
    stem_ids = {str(stem.id) for stem in rows.stems}
    result_set_ids = {str(rs.id) for rs in rows.result_sets}
    run_ids = {str(run.id) for run in rows.runs}
    import_ids = {str(imp.id) for imp in rows.imports}

    if len(asset_ids) != len(rows.assets):
        raise PortableOpenDbInvalid("duplicate asset ids")

    def _must_be_asset(value: Any, what: str) -> None:
        if value is not None and str(value) not in asset_ids:
            raise PortableOpenDbInvalid(f"{what} references unknown asset {value}")

    for field_name in ("source_asset_id", "canonical_asset_id", "monitoring_asset_id"):
        value = getattr(rows.project, field_name)
        _must_be_asset(value, f"projects.{field_name}")
    for pid, asset_id, _role in rows.asset_links:
        if pid != project_id:
            raise PortableOpenDbInvalid(
                f"project_assets references foreign project {pid}"
            )
        if asset_id not in asset_ids:
            raise PortableOpenDbInvalid(
                f"project_assets references unknown asset {asset_id}"
            )
    for imp in rows.imports:
        if str(imp.project_id) != project_id:
            raise PortableOpenDbInvalid("imports row references a foreign project")
    for rep in rows.representations:
        _must_be_asset(rep.asset_id, "representations.asset_id")
        _must_be_asset(rep.parent_asset_id, "representations.parent_asset_id")
    for cache in rows.waveform_caches:
        _must_be_asset(cache.asset_id, "waveform_caches.asset_id")
    for marker in rows.markers:
        if str(marker.project_id) != project_id:
            raise PortableOpenDbInvalid("markers row references a foreign project")
    for row in rows.history:
        if row.project_id != project_id:
            raise PortableOpenDbInvalid(
                "project_history row references a foreign project"
            )
    for run in rows.runs:
        if str(run.project_id) != project_id:
            raise PortableOpenDbInvalid(
                "separation_runs row references a foreign project"
            )
        _must_be_asset(run.input_asset_id, "separation_runs.input_asset_id")
        if run.result_set_id is not None and str(run.result_set_id) not in result_set_ids:
            raise PortableOpenDbInvalid(
                f"run references unknown result set {run.result_set_id}"
            )
    for rs in rows.result_sets:
        if str(rs.project_id) != project_id:
            raise PortableOpenDbInvalid(
                "separation_result_sets row references a foreign project"
            )
        if str(rs.run_id) not in run_ids:
            raise PortableOpenDbInvalid(
                f"result set references unknown run {rs.run_id}"
            )
        _must_be_asset(rs.source.asset_id, "result set source.asset_id")
        _must_be_asset(rs.reference_mix.asset_id, "result set reference_mix.asset_id")
        _must_be_asset(rs.bass_residual_asset_id, "result set bass_residual_asset_id")
        for stem_id in rs.stem_ids:
            if str(stem_id) not in stem_ids:
                raise PortableOpenDbInvalid(
                    f"result set references unknown stem {stem_id}"
                )
    for stem in rows.stems:
        if str(stem.result_set_id) not in result_set_ids:
            raise PortableOpenDbInvalid(
                f"stem references unknown result set {stem.result_set_id}"
            )
        _must_be_asset(stem.audio_asset_id, "stem audio_asset_id")
        _must_be_asset(
            stem.waveform_cache_asset_id, "stem waveform_cache_asset_id"
        )
        for playback_id in stem.playback_representation_ids:
            _must_be_asset(playback_id, "stem playback_representation_ids")
    for job in rows.jobs:
        if str(job.project_id) != project_id:
            raise PortableOpenDbInvalid("media_jobs row references a foreign project")
        if job.import_id is not None and str(job.import_id) not in import_ids:
            raise PortableOpenDbInvalid(f"job references unknown import {job.import_id}")

    active = rows.project.practice_state.active_result_set_id
    if active is not None and str(active) not in result_set_ids:
        raise PortableOpenDbInvalid(
            f"practice_state references unknown result set {active}"
        )


def _check_manifest_assets(manifest: PortableManifest, rows: _PortableRows) -> None:
    """Cross-check the manifest's asset list against the embedded rows.

    This is the integrity bridge: the member hashes verified during
    extraction are tied to the ``assets`` rows here, so a file placed in
    the content-addressed store truly carries the row's ``content_hash``.
    """
    if str(rows.project.id) != str(manifest.project_id):
        raise PortableOpenManifestInvalid(
            "manifest project_id does not match the embedded database"
        )
    declared = {str(entry.asset_id): entry for entry in manifest.assets}
    if len(declared) != len(manifest.assets):
        raise PortableOpenManifestInvalid("duplicate asset entries")
    present_assets = {str(asset.id): asset for asset in rows.assets}
    if set(declared) != set(present_assets):
        raise PortableOpenManifestInvalid(
            "manifest asset list does not match the embedded database"
        )
    member_by_name = {member.name: member for member in manifest.members}
    media_members = {
        member.name
        for member in manifest.members
        if member.category is MemberCategory.MEDIA
    }
    if {entry.member for entry in manifest.assets} != media_members:
        raise PortableOpenManifestInvalid(
            "manifest media members do not match the asset list"
        )
    for asset_id, entry in declared.items():
        asset = present_assets[asset_id]
        member = member_by_name.get(entry.member)
        if member is None:
            raise PortableOpenManifestInvalid(
                f"asset {asset_id} references an undeclared member"
            )
        if entry.content_hash != asset.content_hash:
            raise PortableOpenManifestInvalid(
                f"asset {asset_id} content hash does not match the database"
            )
        if entry.role != str(asset.role):
            raise PortableOpenManifestInvalid(
                f"asset {asset_id} role does not match the database"
            )
        if member.sha256 != asset.content_hash:
            raise PortableOpenManifestInvalid(
                f"member {entry.member!r} hash does not match its asset row"
            )
        if member.essential != entry.essential:
            raise PortableOpenManifestInvalid(
                f"member {entry.member!r} essential flag is inconsistent"
            )


# ---------------------------------------------------------------------------
# §18.5 — ID remap
# ---------------------------------------------------------------------------


def _new_id_maps(
    rows: _PortableRows, open_mode: OpenMode, asset_map: dict[str, str]
) -> _IdMaps:
    def _map(ids: list[str]) -> dict[str, str]:
        if open_mode == "as-archived":
            return {old: old for old in ids}
        return {old: str(uuid.uuid4()) for old in ids}

    return _IdMaps(
        project=_map([str(rows.project.id)]),
        asset=asset_map,
        import_row=_map([str(imp.id) for imp in rows.imports]),
        run=_map([str(run.id) for run in rows.runs]),
        result_set=_map([str(rs.id) for rs in rows.result_sets]),
        stem=_map([str(stem.id) for stem in rows.stems]),
        job=_map([str(job.id) for job in rows.jobs]),
        marker=_map([str(marker.id) for marker in rows.markers]),
        waveform=_map([str(cache.id) for cache in rows.waveform_caches]),
        history=_map([row.id for row in rows.history]),
    )


@dataclass(frozen=True)
class AssetPlan:
    """Final asset identity decisions for one open (§18.4).

    Assets are global content-addressed rows: ``assets.content_hash`` is
    unique, so a row whose content already exists in the store is reused
    (the working copy links the existing row). Otherwise a new row is
    created (``new-copy``) or the archived row is kept (``as-archived``).
    """

    #: Archived asset id -> final asset id.
    id_map: dict[str, str]
    #: Final asset records (reused rows carry their store path).
    assets: tuple[AssetRecord, ...]
    #: Final ids of the asset rows the import must insert.
    insert_ids: frozenset[str]
    #: Final asset id -> archive member holding its file.
    members: dict[str, str]

    @property
    def reused_ids(self) -> set[str]:
        """Final ids of assets whose rows already exist in the store."""
        return {value for value in self.id_map.values() if value not in self.insert_ids}


def plan_assets(
    rows: _PortableRows,
    manifest: PortableManifest,
    open_mode: OpenMode,
    existing_assets: dict[str, AssetRecord],
) -> AssetPlan:
    """Decide the final id of every asset row (content-addressed reuse)."""
    entry_by_id = {str(entry.asset_id): entry for entry in manifest.assets}
    id_map: dict[str, str] = {}
    by_hash: dict[str, AssetRecord] = {}
    insert_ids: set[str] = set()
    members: dict[str, str] = {}
    for asset in rows.assets:
        chosen = by_hash.get(asset.content_hash)
        if chosen is None:
            existing = existing_assets.get(asset.content_hash)
            if existing is not None:
                chosen = existing
            else:
                asset_id = asset.id if open_mode == "as-archived" else uuid.uuid4()
                chosen = asset.model_copy(update={"id": asset_id})
                insert_ids.add(str(chosen.id))
            by_hash[asset.content_hash] = chosen
            members[str(chosen.id)] = entry_by_id[str(asset.id)].member
        id_map[str(asset.id)] = str(chosen.id)
    return AssetPlan(
        id_map=id_map,
        assets=tuple(by_hash.values()),
        insert_ids=frozenset(insert_ids),
        members=members,
    )


def _remap_uuid(maps: dict[str, str], value: uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    return uuid.UUID(maps[str(value)])


def _remap_uuid_list(
    maps: dict[str, str], values: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Remap a UUID list, keeping unknown (pre-existing dangling) ids."""
    return [uuid.UUID(maps.get(str(value), str(value))) for value in values]


def _remap_json_uuids(value: Any, maps: dict[str, str]) -> Any:
    """Recursively replace exact old-UUID strings in free-form JSON."""
    if isinstance(value, str):
        return maps.get(value, value)
    if isinstance(value, list):
        return [_remap_json_uuids(item, maps) for item in value]
    if isinstance(value, dict):
        return {key: _remap_json_uuids(item, maps) for key, item in value.items()}
    return value


def build_bundle(
    rows: _PortableRows,
    manifest: PortableManifest,
    plan: AssetPlan,
    *,
    open_mode: OpenMode,
    project_name: str | None,
    source_filename: str,
    existing_representation_assets: set[str],
    existing_waveform_cache_assets: set[str],
) -> PortableImportBundle:
    """Remap every row ID and produce the import bundle (§18.5).

    Asset-keyed global rows (``representations``, ``waveform_caches``)
    are included only when the store has no row for the final asset yet.
    """
    maps = _new_id_maps(rows, open_mode, plan.id_map)
    assets = plan.assets
    insert_asset_ids = plan.insert_ids
    asset_members = plan.members
    if insert_asset_ids:
        assets = tuple(
            _rewrite_source_original_path(asset, maps, insert_asset_ids)
            for asset in assets
        )
    flat = maps.all
    new_project_id = uuid.UUID(maps.project[str(rows.project.id)])

    project = rows.project
    practice_state = project.practice_state
    if practice_state.active_result_set_id is not None:
        old_active = str(practice_state.active_result_set_id)
        if old_active in maps.result_set:
            practice_state = practice_state.model_copy(
                update={"active_result_set_id": uuid.UUID(maps.result_set[old_active])}
            )
    project = project.model_copy(
        update={
            "id": new_project_id,
            "source_asset_id": _remap_uuid(maps.asset, project.source_asset_id),
            "canonical_asset_id": _remap_uuid(maps.asset, project.canonical_asset_id),
            "monitoring_asset_id": _remap_uuid(maps.asset, project.monitoring_asset_id),
            "practice_state": practice_state,
        }
    )
    if project_name is not None:
        # model_copy does not re-validate; go through the domain model so
        # the requested name gets the same rules as a user-entered name.
        project = ProjectRecord.model_validate(
            {**project.model_dump(mode="python"), "name": project_name}
        )

    asset_links = tuple(
        (maps.project[pid], maps.asset[asset_id], role)
        for pid, asset_id, role in rows.asset_links
    )
    imports = tuple(
        imp.model_copy(
            update={
                "id": uuid.UUID(maps.import_row[str(imp.id)]),
                "project_id": new_project_id,
                "job_ids": tuple(
                    uuid.UUID(maps.job.get(str(job_id), str(job_id)))
                    for job_id in imp.job_ids
                ),
            }
        )
        for imp in rows.imports
    )
    representations = tuple(
        rep.model_copy(
            update={
                "asset_id": uuid.UUID(maps.asset[str(rep.asset_id)]),
                "parent_asset_id": _remap_uuid(maps.asset, rep.parent_asset_id),
            }
        )
        for rep in rows.representations
        if maps.asset[str(rep.asset_id)] not in existing_representation_assets
    )
    waveform_caches = tuple(
        cache.model_copy(
            update={
                "id": uuid.UUID(maps.waveform[str(cache.id)]),
                "asset_id": uuid.UUID(maps.asset[str(cache.asset_id)]),
            }
        )
        for cache in rows.waveform_caches
        if maps.asset[str(cache.asset_id)] not in existing_waveform_cache_assets
    )
    markers = tuple(
        marker.model_copy(
            update={
                "id": uuid.UUID(maps.marker[str(marker.id)]),
                "project_id": new_project_id,
            }
        )
        for marker in rows.markers
    )
    history = tuple(
        HistoryRow(
            id=maps.history[row.id],
            project_id=maps.project[row.project_id],
            seq=row.seq,
            kind=row.kind,
            before_json=row.before_json,
            after_json=row.after_json,
            created_at=row.created_at,
        )
        for row in rows.history
    )
    runs = tuple(
        run.model_copy(
            update={
                "id": uuid.UUID(maps.run[str(run.id)]),
                "project_id": new_project_id,
                "input_asset_id": uuid.UUID(maps.asset[str(run.input_asset_id)]),
                "result_set_id": _remap_uuid(maps.result_set, run.result_set_id),
            }
        )
        for run in rows.runs
    )
    result_sets = tuple(
        rs.model_copy(
            update={
                "id": uuid.UUID(maps.result_set[str(rs.id)]),
                "run_id": uuid.UUID(maps.run[str(rs.run_id)]),
                "project_id": new_project_id,
                "source": rs.source.model_copy(
                    update={"asset_id": uuid.UUID(maps.asset[str(rs.source.asset_id)])}
                ),
                "reference_mix": rs.reference_mix.model_copy(
                    update={
                        "asset_id": uuid.UUID(
                            maps.asset[str(rs.reference_mix.asset_id)]
                        )
                    }
                ),
                "stem_ids": _remap_uuid_list(maps.stem, list(rs.stem_ids)),
                "bass_residual_asset_id": _remap_uuid(
                    maps.asset, rs.bass_residual_asset_id
                ),
            }
        )
        for rs in rows.result_sets
    )
    stems = tuple(
        stem.model_copy(
            update={
                "id": uuid.UUID(maps.stem[str(stem.id)]),
                "result_set_id": uuid.UUID(maps.result_set[str(stem.result_set_id)]),
                "audio_asset_id": uuid.UUID(maps.asset[str(stem.audio_asset_id)]),
                "waveform_cache_asset_id": _remap_uuid(
                    maps.asset, stem.waveform_cache_asset_id
                ),
                "playback_representation_ids": _remap_uuid_list(
                    maps.asset, list(stem.playback_representation_ids)
                ),
            }
        )
        for stem in rows.stems
    )
    jobs = tuple(
        job.model_copy(
            update={
                "id": uuid.UUID(maps.job[str(job.id)]),
                "project_id": new_project_id,
                "import_id": _remap_uuid(maps.import_row, job.import_id),
                "result": _remap_json_uuids(job.result, flat),
                "parameters": _remap_json_uuids(job.parameters, flat),
            }
        )
        for job in rows.jobs
    )

    provenance = {
        "archived_project_id": str(manifest.project_id),
        "saved_revision": manifest.saved_revision,
        "saved_at": manifest.saved_at.isoformat().replace("+00:00", "Z"),
        "source_filename": source_filename,
    }
    return PortableImportBundle(
        project=project,
        history_seq=rows.history_seq,
        assets=assets,
        insert_asset_ids=insert_asset_ids,
        asset_members=asset_members,
        asset_links=asset_links,
        imports=imports,
        representations=representations,
        waveform_caches=waveform_caches,
        markers=markers,
        history=history,
        runs=runs,
        result_sets=result_sets,
        stems=stems,
        jobs=jobs,
        portable_provenance=provenance,
    )


def _rewrite_source_original_path(
    asset: AssetRecord, maps: _IdMaps, insert_asset_ids: frozenset[str]
) -> AssetRecord:
    """Give a newly stored source original its own upload path.

    The restored source file must not share a path with the archived
    project's upload (which may still exist in the same store), so its
    ``relative_path`` follows the remapped import id. Reused asset rows
    keep their existing path.
    """
    if (
        asset.role is not AssetRole.SOURCE_ORIGINAL
        or str(asset.id) not in insert_asset_ids
    ):
        return asset
    old_import_id = PurePosixPath(asset.relative_path).stem
    new_import_id = maps.import_row.get(old_import_id)
    if new_import_id is None or new_import_id == old_import_id:
        return asset
    return asset.model_copy(
        update={"relative_path": f"runtime/uploads/{new_import_id}.part"}
    )


# ---------------------------------------------------------------------------
# §18.6 — optional-member failure handling
# ---------------------------------------------------------------------------


def drop_absent_optional_assets(
    bundle: PortableImportBundle,
    manifest: PortableManifest,
    present: set[str],
) -> PortableImportBundle:
    """Drop optional assets whose file is absent and incomplete caches.

    Essential assets can never be absent here (validated up front); a
    missing optional asset (e.g. a playback-rate cache) loses its row and
    its dependent representation/link rows so the app regenerates it on
    demand. A waveform cache tree is kept only when every member of the
    tree verified; otherwise its ``waveform_caches`` row is dropped.
    """
    essential_by_member = {
        entry.member: entry.essential for entry in manifest.assets
    }
    dropped_assets: set[str] = set()
    for asset in bundle.assets:
        member = bundle.asset_members[str(asset.id)]
        if member in present:
            continue
        if essential_by_member.get(member, True):
            raise PortableOpenMemberMissing([member])
        dropped_assets.add(str(asset.id))

    members_by_hash: dict[str, list[str]] = {}
    for manifest_member in manifest.members:
        if manifest_member.name.startswith(WAVEFORM_CACHE_PREFIX):
            rest = manifest_member.name[len(WAVEFORM_CACHE_PREFIX):]
            source_hash = rest.split("/", 1)[0]
            members_by_hash.setdefault(source_hash, []).append(manifest_member.name)
    dropped_caches: set[str] = set()
    for cache in bundle.waveform_caches:
        tree = members_by_hash.get(cache.source_hash, [])
        if not tree or any(name not in present for name in tree):
            dropped_caches.add(str(cache.id))

    if not dropped_assets and not dropped_caches:
        return bundle

    for field_name in ("source_asset_id", "canonical_asset_id", "monitoring_asset_id"):
        value = getattr(bundle.project, field_name)
        if value is not None and str(value) in dropped_assets:
            raise PortableOpenDbInvalid(
                f"project {field_name} is an optional asset with no file"
            )

    assets = tuple(a for a in bundle.assets if str(a.id) not in dropped_assets)
    asset_links = tuple(
        link for link in bundle.asset_links if link[1] not in dropped_assets
    )
    representations = tuple(
        rep
        for rep in bundle.representations
        if str(rep.asset_id) not in dropped_assets
    )
    waveform_caches = tuple(
        cache
        for cache in bundle.waveform_caches
        if str(cache.id) not in dropped_caches
        and str(cache.asset_id) not in dropped_assets
    )
    stems = tuple(
        _drop_absent_playback_ids(stem, dropped_assets) for stem in bundle.stems
    )
    return replace(
        bundle,
        assets=assets,
        asset_links=asset_links,
        representations=representations,
        waveform_caches=waveform_caches,
        stems=stems,
    )


def _drop_absent_playback_ids(
    stem: StemRecord, dropped_assets: set[str]
) -> StemRecord:
    updates: dict[str, Any] = {}
    if any(str(pid) in dropped_assets for pid in stem.playback_representation_ids):
        updates["playback_representation_ids"] = [
            pid
            for pid in stem.playback_representation_ids
            if str(pid) not in dropped_assets
        ]
    if (
        stem.waveform_cache_asset_id is not None
        and str(stem.waveform_cache_asset_id) in dropped_assets
    ):
        updates["waveform_cache_asset_id"] = None
    return stem.model_copy(update=updates) if updates else stem


# ---------------------------------------------------------------------------
# §18.4 — free space + asset file restoration
# ---------------------------------------------------------------------------


def _free_bytes(path: Path) -> int:
    """Free bytes on the filesystem of ``path`` (first existing ancestor)."""
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _member_size(infos: dict[str, zipfile.ZipInfo], member: str) -> int:
    info = infos.get(member)
    return info.file_size if info is not None else 0


def check_free_space(
    manifest: PortableManifest,
    infos: dict[str, zipfile.ZipInfo],
    paths: StoragePaths,
) -> None:
    """Free-space check before extraction (§18.2 step 9).

    The data root must hold the staged extraction plus every store
    object that is not already present (worst case: all of them; the
    exact dedupe decision is made at restoration after the hash check).
    The runtime root holds the new copy of the original upload.
    """
    staged_bytes = sum(info.file_size for info in infos.values())
    store_bytes = 0
    runtime_bytes = 0
    for entry in manifest.assets:
        size = _member_size(infos, entry.member)
        if entry.role == AssetRole.SOURCE_ORIGINAL:
            runtime_bytes += size
            continue
        suffix = PurePosixPath(entry.member).suffix or ".bin"
        destination = paths.data / "assets" / f"{entry.content_hash}{suffix}"
        if not destination.is_file():
            store_bytes += size
    data_needed = staged_bytes + store_bytes + _SPACE_MARGIN_DATA
    data_free = _free_bytes(paths.data)
    if data_free < data_needed:
        raise PortableOpenNoSpace(data_needed, data_free)
    runtime_needed = runtime_bytes + _SPACE_MARGIN_RUNTIME
    runtime_free = _free_bytes(paths.runtime)
    if runtime_free < runtime_needed:
        raise PortableOpenNoSpace(runtime_needed, runtime_free)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_STREAM_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_copy(source: Path, destination: Path) -> None:
    """Streamed copy with atomic rename (partial file first)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.parent / (destination.name + ".partial")
    try:
        shutil.copyfile(source, partial)
        partial.replace(destination)
    except BaseException:
        with contextlib.suppress(OSError):
            partial.unlink()
        raise


def _copy_deduped(source: Path, destination: Path, expected_hash: str) -> None:
    """Copy ``source`` to ``destination``; reuse an existing identical file.

    A destination that exists with a different hash is a content-
    addressing collision and rejects the open.
    """
    if destination.is_file():
        if _sha256_file(destination) == expected_hash:
            return
        raise PortableOpenDbInvalid(
            f"asset store collision at {destination.name}: existing file hash "
            f"differs from {expected_hash}"
        )
    _stream_copy(source, destination)


def _copy_verified(source: Path, destination: Path, expected_hash: str) -> None:
    """Copy a reproducible cache file; identical existing files are reused.

    Cache files are keyed by source content hash, so a destination with
    a different hash can only be stale or damaged; the verified archive
    copy replaces it.
    """
    if destination.is_file() and _sha256_file(destination) == expected_hash:
        return
    _stream_copy(source, destination)


def restore_asset_files(
    bundle: PortableImportBundle,
    manifest: PortableManifest,
    staging: Path,
    present: set[str],
    paths: StoragePaths,
) -> None:
    """Place asset and waveform-cache files in the store (§18.4)."""
    for asset in bundle.assets:
        member = bundle.asset_members[str(asset.id)]
        if member not in present:
            raise PortableOpenDbInvalid(
                f"staged file for asset {asset.id} is absent ({member})"
            )
        destination = paths.resolve_asset_path(asset.relative_path)
        _copy_deduped(staging / member, destination, asset.content_hash)

    for cache in bundle.waveform_caches:
        prefix = f"{WAVEFORM_CACHE_PREFIX}{cache.source_hash}/"
        for cache_member in manifest.members:
            if not cache_member.name.startswith(prefix):
                continue
            if cache_member.name not in present:
                raise PortableOpenDbInvalid(
                    f"staged waveform cache member {cache_member.name!r} is absent"
                )
            relative = cache_member.name[len(prefix):]
            destination = paths.cache / "waveforms" / cache.source_hash / relative
            _copy_verified(staging / cache_member.name, destination, cache_member.sha256)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _staging_root(paths: StoragePaths) -> Path:
    return paths.data / "portable" / _STAGING_SUBDIR


def open_portable_archive(
    archive_path: Path,
    *,
    paths: StoragePaths,
    repository: ProjectRepository,
    max_uncompressed_bytes: int,
    max_member_count: int,
    open_mode: OpenMode = "new-copy",
    project_name: str | None = None,
    source_filename: str,
) -> ProjectRecord:
    """Run the full §18 open workflow for one uploaded archive.

    Returns the opened working-copy project. Raises
    :class:`PortableOpenError` (and subclasses) on failure; the staging
    directory is removed and the store is left untouched (the project is
    only exposed by the single import transaction).
    """
    manifest, infos = _validate_archive(
        archive_path,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_member_count=max_member_count,
    )
    check_free_space(manifest, infos, paths)

    staging = _staging_root(paths) / str(uuid.uuid4())
    try:
        staging.mkdir(parents=True)
        present = _extract_staged(archive_path, manifest, infos, staging)
        rows = _read_database(staging / DATABASE_MEMBER)
        _check_isolation(rows)
        _check_manifest_assets(manifest, rows)
        if open_mode == "as-archived" and repository.get_project(rows.project.id) is not None:
            raise PortableOpenIdConflict(str(rows.project.id))
        existing_assets = repository.get_assets_by_hashes(
            {asset.content_hash for asset in rows.assets}
        )
        plan = plan_assets(rows, manifest, open_mode, existing_assets)
        reused_ids = {uuid.UUID(value) for value in plan.reused_ids}
        existing_representations, existing_caches = repository.get_asset_metadata_ids(
            reused_ids
        )
        bundle = build_bundle(
            rows,
            manifest,
            plan,
            open_mode=open_mode,
            project_name=project_name,
            source_filename=source_filename,
            existing_representation_assets=existing_representations,
            existing_waveform_cache_assets=existing_caches,
        )
        bundle = drop_absent_optional_assets(bundle, manifest, present)
        restore_asset_files(bundle, manifest, staging, present, paths)
        return repository.import_portable_bundle(bundle)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
