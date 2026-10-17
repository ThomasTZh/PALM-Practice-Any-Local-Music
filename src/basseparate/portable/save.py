"""Portable project save pipeline (M2.15, spec §17).

Captures the working project at its current revision into a complete
``.basseparate`` archive and publishes it atomically to managed storage:

1. The plan (M2.14 ``compute_portable_plan``) is the *temporary
   reference* for the save: its asset set is held in memory for the
   duration of the request. "Flush pending manual commands" is an
   architectural no-op — project commands are durably applied at
   apply-time; there is no unapplied queue.
2. Asset files are checked on disk. A missing *essential* file fails
   the save (``SAVE_ASSET_MISSING``); a missing *optional* file is
   excluded from the archive and the portable database so the archive
   stays self-consistent.
3. The portable database is built into the staging directory (same
   filesystem as the publication target), then the archive is staged,
   verified (CRC + per-member re-hash against the manifest + member-set
   check), hashed, and published with atomic ``os.replace``.
4. One previous artifact is retained; older rows and files are
   reclaimed. The artifact row is recorded only after a successful
   publish.

Failure semantics: any failure removes only this save's staging files.
Published artifacts, the retained previous artifact, the source store,
and the working database are never touched, so a failed or interrupted
save never destroys the last valid file (§17.4).
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import sqlite3
import uuid
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from basseparate.domain.export import sanitize_filename_part
from basseparate.domain.portable import PortableArtifact
from basseparate.domain.project import ProjectRecord
from basseparate.media.preparation import sha256_file
from basseparate.portable.closure import PortablePlan, compute_portable_plan
from basseparate.portable.database import build_portable_database
from basseparate.portable.format import MANIFEST_MEMBER, PortableManifest
from basseparate.portable.writer import write_portable_archive
from basseparate.storage.paths import StoragePaths
from basseparate.storage.repository import PortableArtifactRepository

#: Per-member zip overhead allowance for the size estimate (header +
#: central directory + alignment).
_ZIP_OVERHEAD_PER_MEMBER = 128
#: Allowance for the manifest and zip end-of-archive structures.
_ZIP_FIXED_OVERHEAD = 4096

_STAGING_SUBDIR = ".staging"


class PortableSaveError(Exception):
    """A portable save failed; ``code`` is stable for API mapping."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class PortableSaveMissingAsset(PortableSaveError):
    """One or more essential asset files are absent from the store."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = list(missing)
        super().__init__(
            "SAVE_ASSET_MISSING",
            "essential asset file(s) are missing from the store",
            {"missing": self.missing},
        )


class PortableSaveNoSpace(PortableSaveError):
    """Not enough free disk space for the staging files."""

    def __init__(self, estimated_bytes: int, free_bytes: int) -> None:
        super().__init__(
            "SAVE_NO_SPACE",
            "not enough free disk space for a portable save",
            {"estimated_bytes": estimated_bytes, "free_bytes": free_bytes},
        )


class PortableSaveVerifyFailed(PortableSaveError):
    """The staged archive did not verify against its manifest."""

    def __init__(self, reason: str) -> None:
        super().__init__("SAVE_VERIFY_FAILED", f"staged archive failed verification: {reason}")


def plan_with_exclusions(plan: PortablePlan, excluded: set[str]) -> PortablePlan:
    """Drop excluded (optional, file-missing) assets from the plan.

    The excluded asset ids also drop their ``waveform_caches`` entries;
    ``asset_ids`` shrinks accordingly so the portable database builder
    selects the same reduced closure.
    """
    if not excluded:
        return plan
    assets = tuple(a for a in plan.assets if a.asset_id not in excluded)
    caches = tuple(c for c in plan.waveform_caches if c.asset_id not in excluded)
    return replace(
        plan, assets=assets, waveform_caches=caches, asset_ids=plan.asset_ids - excluded
    )


def _portable_root(paths: StoragePaths) -> Path:
    return paths.data / "portable"


def _staging_dir(paths: StoragePaths) -> Path:
    return _portable_root(paths) / _STAGING_SUBDIR


def _estimate_bytes(
    plan: PortablePlan, db_snapshot: Path, paths: StoragePaths
) -> int:
    """Estimated archive size (members + zip overhead), for the space check."""
    total = db_snapshot.stat().st_size + _ZIP_FIXED_OVERHEAD
    total += _ZIP_OVERHEAD_PER_MEMBER  # the database member itself
    for asset in plan.assets:
        total += asset.byte_count + _ZIP_OVERHEAD_PER_MEMBER
    for cache in plan.waveform_caches:
        cache_dir = paths.resolve_asset_path(f"cache/waveforms/{cache.source_hash}")
        if not cache_dir.is_dir():
            continue
        for file_path in cache_dir.rglob("*"):
            if file_path.is_file():
                total += file_path.stat().st_size + _ZIP_OVERHEAD_PER_MEMBER
    # Provenance documents + manifest (small, deflate).
    total += 2 * 65536
    return total


def _verify_archive(path: Path) -> None:
    """Reopen the staged archive and check it against its manifest.

    CRC check, per-member re-hash against the manifest sha256, member-set
    equality (exactly ``{manifest.json} ∪ member names``), and manifest
    model validation. Raises :class:`PortableSaveVerifyFailed` on any
    mismatch.
    """
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise PortableSaveVerifyFailed(f"CRC check failed for member {bad!r}")
        names = set(zf.namelist())
        if MANIFEST_MEMBER not in names:
            raise PortableSaveVerifyFailed("manifest.json missing from archive")
        manifest = PortableManifest.model_validate_json(
            zf.read(MANIFEST_MEMBER).decode("utf-8")
        )
        expected = {MANIFEST_MEMBER} | {m.name for m in manifest.members}
        if names != expected:
            missing = sorted(expected - names)
            stray = sorted(names - expected)
            raise PortableSaveVerifyFailed(
                f"member set mismatch (missing={missing[:3]}, stray={stray[:3]})"
            )
        for member in manifest.members:
            data = zf.read(member.name)
            if len(data) != member.uncompressed_size_bytes:
                raise PortableSaveVerifyFailed(
                    f"size mismatch for member {member.name!r}"
                )
            digest = hashlib.sha256(data).hexdigest()
            if digest != member.sha256:
                raise PortableSaveVerifyFailed(f"sha256 mismatch for member {member.name!r}")


def _retention_keep(
    artifacts: PortableArtifactRepository, project_id: uuid.UUID
) -> list[PortableArtifact]:
    """The previous artifacts to keep (the newest one) per §17.1."""
    return artifacts.list_for_project(project_id)[:1]


def _download_filename(project: ProjectRecord, revision: int) -> str:
    base = sanitize_filename_part(project.name, fallback="project")
    return f"{base}-r{revision}.basseparate"


def _directory_fsync(path: Path) -> None:
    """Best-effort fsync of a directory (durable publication)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def perform_portable_save(
    db_path: Path,
    paths: StoragePaths,
    project: ProjectRecord,
    artifacts: PortableArtifactRepository,
) -> tuple[PortableArtifact, PortableManifest]:
    """Run the full §17.1 save workflow for one project.

    Returns the recorded artifact and the archive manifest. Raises
    :class:`PortableSaveError` (and a subclass) on failure; no staging
    file is left behind and no previously published artifact is touched.
    """
    saved_at = datetime.now(UTC)
    project_id = project.id

    # 1–2. Capture the committed working state: the plan is computed from
    # a read-only connection; its asset set is the temporary reference
    # held for the duration of the save.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        plan = compute_portable_plan(conn, str(project_id))
    finally:
        conn.close()

    # 3. File presence: essential missing fails; optional missing is
    # excluded from the archive and the portable database.
    missing_essential: list[str] = []
    excluded: set[str] = set()
    for asset in plan.assets:
        asset_path = paths.resolve_asset_path(asset.relative_path)
        if not asset_path.is_file():
            if asset.essential:
                missing_essential.append(asset.relative_path)
            else:
                excluded.add(asset.asset_id)
    if missing_essential:
        raise PortableSaveMissingAsset(missing_essential)
    reduced_plan = plan_with_exclusions(plan, excluded)

    staging = _staging_dir(paths)
    staging.mkdir(parents=True, exist_ok=True)
    staging_db = staging / "project.sqlite"
    staging_archive = staging / f"{uuid.uuid4()}.basseparate"

    try:
        # 4. Portable database into the staging directory (same
        # filesystem as the publication target → atomic replace later).
        build_portable_database(
            db_path, str(project_id), staging_db, excluded_asset_ids=frozenset(excluded)
        )

        # 5. Size estimate + free-space check.
        estimated = _estimate_bytes(reduced_plan, staging_db, paths)
        free = shutil.disk_usage(staging).free
        if free < estimated:
            raise PortableSaveNoSpace(estimated, free)

        # 6. Write the archive (manifest last, per-member hashing).
        manifest = write_portable_archive(
            reduced_plan, staging_db, paths, staging_archive, saved_at
        )

        # 7. Verify the staged archive against its manifest.
        _verify_archive(staging_archive)

        # 8. Archive hash + publication destination.
        sha256 = sha256_file(staging_archive)
        byte_size = staging_archive.stat().st_size
        destination_dir = _portable_root(paths) / str(project_id)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{project.revision}-{sha256[:12]}.basseparate"

        # 9. Retention: keep one previous artifact, reclaim the rest.
        keep = _retention_keep(artifacts, project_id)
        keep_ids = {a.id for a in keep}
        for old in artifacts.list_for_project(project_id):
            if old.id not in keep_ids:
                with contextlib.suppress(OSError):
                    paths.resolve_asset_path(old.relative_path).unlink()
        artifacts.delete_older(project_id, keep_ids)

        # 10. Atomic publish + directory fsync (same filesystem: staging
        # and destination are both under the data root).
        staging_archive.replace(destination)
        _directory_fsync(destination_dir)

        # 11. Record the artifact row (only after a successful publish).
        artifact = PortableArtifact(
            id=uuid.uuid4(),
            project_id=project_id,
            saved_revision=project.revision,
            sha256=sha256,
            byte_size=byte_size,
            relative_path=f"data/portable/{project_id}/{destination.name}",
            download_filename=_download_filename(project, project.revision),
            created_at=saved_at,
        )
        artifacts.publish(artifact)
        # The intermediate portable database is no longer needed; the
        # published archive already embeds it.
        with contextlib.suppress(OSError):
            staging_db.unlink()
    except BaseException:
        for leftover in (staging_archive, staging_db):
            with contextlib.suppress(OSError):
                leftover.unlink()
        raise

    return artifact, manifest
