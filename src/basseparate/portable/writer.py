"""Portable project archive writer (M2.15, spec §17.1).

Streams the planned closure into a ZIP64 ``.basseparate`` archive:

1. ``project.sqlite`` — the portable database snapshot (stored).
2. ``assets/sha256/...`` — every plan asset (stored).
3. ``caches/waveforms/<source_hash>/...`` — waveform cache trees
   (stored, optional; a missing directory is an empty cache).
4. ``provenance/separation-runs.json`` /
   ``provenance/model-manifests.json`` (deflate).
5. ``manifest.json`` — last; it lists every member except itself, so
   the verifier (M2.16) requires exactly ``{manifest.json} ∪ names``.

Every member is streamed in 1 MiB chunks while its SHA-256 is computed,
so large assets are never buffered in memory. All ``ZipInfo``
timestamps derive from ``saved_at``, making the archive bytes
deterministic for a given input set.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import zipfile
from datetime import datetime
from pathlib import Path

from basseparate import APP_VERSION, PROJECT_SCHEMA_VERSION
from basseparate.domain.common import Uuid
from basseparate.portable.closure import (
    PortablePlan,
    model_manifests_payload,
    separation_runs_payload,
)
from basseparate.portable.format import (
    DATABASE_MEMBER,
    MANIFEST_MEMBER,
    PROVENANCE_MODELS_MEMBER,
    PROVENANCE_RUNS_MEMBER,
    ManifestAsset,
    ManifestMember,
    ManifestProvenance,
    PortableManifest,
    category_for,
    compression_for,
    compression_name,
)
from basseparate.storage.paths import StoragePaths

_CHUNK_SIZE = 1 << 20


class PortableWriteError(ValueError):
    """Raised when the archive cannot be written from the planned files."""


def _zip_time(saved_at: datetime) -> tuple[int, int, int, int, int, int]:
    return (
        saved_at.year,
        saved_at.month,
        saved_at.day,
        saved_at.hour,
        saved_at.minute,
        saved_at.second,
    )


def _make_info(name: str, saved_at: datetime) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_zip_time(saved_at))
    info.compress_type = compression_for(name)
    info.external_attr = 0o644 << 16
    return info


def _member_record(name: str, size: int, sha256: str, essential: bool) -> ManifestMember:
    return ManifestMember(
        name=name,
        uncompressed_size_bytes=size,
        sha256=sha256,
        essential=essential,
        compression=compression_name(name),
        category=category_for(name),
    )


def _write_file_member(
    zf: zipfile.ZipFile,
    name: str,
    source: Path,
    essential: bool,
    saved_at: datetime,
) -> ManifestMember:
    """Stream one file into the archive, hashing while writing."""
    if not source.is_file():
        raise PortableWriteError(f"archive source file missing: {source}")
    info = _make_info(name, saved_at)
    digest = hashlib.sha256()
    size = 0
    with zf.open(info, "w") as dest, source.open("rb") as src:
        while chunk := src.read(_CHUNK_SIZE):
            dest.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return _member_record(name, size, digest.hexdigest(), essential)


def _write_bytes_member(
    zf: zipfile.ZipFile,
    name: str,
    data: bytes,
    essential: bool,
    saved_at: datetime,
) -> ManifestMember:
    """Write one small in-memory member (provenance documents, manifest)."""
    info = _make_info(name, saved_at)
    digest = hashlib.sha256()
    digest.update(data)
    zf.writestr(info, data)
    return _member_record(name, len(data), digest.hexdigest(), essential)


def _walk_cache_files(cache_dir: Path) -> list[tuple[str, Path]]:
    """The files of one waveform cache directory, sorted by relative path."""
    return [
        (file_path.relative_to(cache_dir).as_posix(), file_path)
        for file_path in sorted(cache_dir.rglob("*"))
        if file_path.is_file()
    ]


def write_portable_archive(
    plan: PortablePlan,
    db_snapshot: Path,
    paths: StoragePaths,
    destination: Path,
    saved_at: datetime,
) -> PortableManifest:
    """Write the complete archive at ``destination`` and return the manifest.

    ``plan`` must already be reduced for missing optional assets (see
    ``save.plan_with_exclusions``); a missing file here is a planning
    error and raises :class:`PortableWriteError`. On failure no
    destination file is left behind.
    """
    destination = Path(destination)
    if not db_snapshot.is_file():
        raise PortableWriteError(f"portable database snapshot missing: {db_snapshot}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")

    members: list[ManifestMember] = []
    try:
        with zipfile.ZipFile(partial, "w", allowZip64=True) as zf:
            members.append(_write_file_member(zf, DATABASE_MEMBER, db_snapshot, True, saved_at))
            for asset in plan.assets:
                source = paths.resolve_asset_path(asset.relative_path)
                members.append(
                    _write_file_member(zf, asset.member, source, asset.essential, saved_at)
                )
            for cache in plan.waveform_caches:
                cache_dir = paths.resolve_asset_path(f"cache/waveforms/{cache.source_hash}")
                if not cache_dir.is_dir():
                    continue  # caches are reproducible; absent dir == empty cache
                for rel, file_path in _walk_cache_files(cache_dir):
                    members.append(
                        _write_file_member(
                            zf, f"{cache.member_prefix}{rel}", file_path, False, saved_at
                        )
                    )
            runs_doc = separation_runs_payload(plan.separation_runs)
            members.append(
                _write_bytes_member(
                    zf,
                    PROVENANCE_RUNS_MEMBER,
                    json.dumps(runs_doc, sort_keys=True).encode("utf-8"),
                    True,
                    saved_at,
                )
            )
            models_doc = model_manifests_payload()
            members.append(
                _write_bytes_member(
                    zf,
                    PROVENANCE_MODELS_MEMBER,
                    json.dumps(models_doc, sort_keys=True).encode("utf-8"),
                    True,
                    saved_at,
                )
            )
            manifest = PortableManifest(
                project_schema_version=int(
                    plan.project_row.get("schema_version") or PROJECT_SCHEMA_VERSION
                ),
                application_version=APP_VERSION,
                project_id=Uuid(plan.project_id),
                saved_revision=int(plan.project_row.get("revision", 0)),
                saved_at=saved_at,
                assets=[
                    ManifestAsset(
                        asset_id=Uuid(asset.asset_id),
                        content_hash=asset.content_hash,
                        role=asset.role,
                        member=asset.member,
                        essential=asset.essential,
                    )
                    for asset in plan.assets
                ],
                members=members,
                provenance=ManifestProvenance(
                    separation_runs=list(plan.separation_runs),
                    model_manifests=models_doc["models"],
                ),
            )
            members.append(
                _write_bytes_member(
                    zf, MANIFEST_MEMBER, manifest.model_dump_json().encode("utf-8"), True, saved_at
                )
            )
        fd = os.open(partial, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        partial.replace(destination)
    except BaseException:
        _suppress_unlink(partial)
        raise
    return manifest


def _suppress_unlink(path: Path) -> None:
    """Best-effort removal of a partial destination file."""
    with contextlib.suppress(OSError):
        path.unlink()
