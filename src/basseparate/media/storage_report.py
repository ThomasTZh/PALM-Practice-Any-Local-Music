"""Storage reporting and explicit reclaim (M2.7, milestone2.md §9.5).

The analysis cache is bounded by the configurable ``cache_limit_bytes``
policy (default 50 GiB). The report splits storage into:

- **Model storage** (``models/`` bundle dirs): reported, never evicted,
  and never counted against the limit (§9.5.2).
- **Project bytes**: source/canonical/derived assets and their
  waveform caches — pinned by the M1 policy.
- **Separation result bytes**: stem assets (+ their waveform caches) of
  every result set. Counted once per unique content hash, because
  publication deduplicates assets by hash.

Pinning (§9.5.3–4, 6): a result set is pinned when it is a project's
**active** set, when it is the **newest set per cache key** (the entry a
lookup would return — evicting it would break "identical requests reuse
results"), or when any of its assets was pinned by the caller (the
M2.8 edit-history / in-flight-job hook). Everything else is reclaimable.

``reclaim_storage`` is the **explicit** cleanup (§9.5.7: the report
displays the reclaimable size *before* cleanup). It evicts reclaimable
result sets LRU-first (oldest ``created_at``) until the non-model total
fits the limit, deleting stem files and waveform caches. A file is
deleted only when no remaining result set references its content hash
(dedup-safe). Result-set, stem, and asset **records are never deleted**
— a set whose bytes were reclaimed simply misses the cache lookup and a
rerun rebuilds it. Edits (markers, working state, history) are project
rows, not assets, so they are unaffected.
"""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from basseparate.domain.asset import AssetRecord, AssetRole
from basseparate.domain.separation import SeparationResultSet
from basseparate.storage.paths import StoragePaths
from basseparate.storage.repository import (
    ProjectRepository,
    SeparationRepository,
    WaveformCacheRepository,
)

#: Pin reasons for the per-result-set breakdown.
PIN_ACTIVE = "active"
PIN_NEWEST_FOR_KEY = "newest_for_key"
PIN_ASSETS = "pinned_assets"


@dataclass(frozen=True)
class ResultSetStorage:
    """One result set's storage footprint and pin state (§9.5).

    ``bytes`` sums the set's stem assets (recorded ``byte_count`` plus
    their waveform caches); with hash-deduplication the sum over sets
    can exceed the deduplicated ``StorageReport.separation_result_bytes``.
    """

    result_set_id: uuid.UUID
    created_at: datetime
    bytes: int
    pinned: bool
    pin_reason: str


@dataclass(frozen=True)
class StorageReport:
    """Storage split for the cache-limit policy (§9.5.1–2).

    ``total_bytes`` includes model storage; the limit applies to
    ``total_bytes - model_bytes``.
    """

    model_bytes: int
    project_bytes: int
    separation_result_bytes: int
    pinned_bytes: int
    reclaimable_bytes: int
    total_bytes: int
    result_sets: tuple[ResultSetStorage, ...] = ()


@dataclass(frozen=True)
class ReclaimResult:
    """Outcome of an explicit reclaim (§9.5.7)."""

    bytes_freed: int
    evicted_result_sets: tuple[uuid.UUID, ...]
    files_removed: int


def _directory_bytes(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())


def _cache_bytes(
    waveform_repository: WaveformCacheRepository | None,
    asset: AssetRecord,
    storage_paths: StoragePaths,
) -> int:
    """On-disk size of the asset's waveform cache directory, if any."""
    if waveform_repository is None:
        return 0
    record = waveform_repository.get_for_asset(asset.id)
    if record is None:
        return 0
    manifest = storage_paths.resolve_asset_path(record.manifest_path)
    return _directory_bytes(manifest.parent)


def _stem_assets(
    separation_repository: SeparationRepository,
    project_repository: ProjectRepository,
    result_set_id: uuid.UUID,
) -> list[AssetRecord]:
    stems = separation_repository.list_stems_for_result_set(result_set_id)
    assets: list[AssetRecord] = []
    for stem in stems:
        asset = project_repository.get_asset(stem.audio_asset_id)
        if asset is not None:
            assets.append(asset)
    return assets


def _pin_reason(
    result_set_id: uuid.UUID,
    result_set: SeparationResultSet,
    active_ids: frozenset[uuid.UUID],
    newest_per_key: dict[str, tuple[datetime, uuid.UUID]],
    assets: Sequence[AssetRecord],
    pinned_ids: frozenset[uuid.UUID],
) -> str:
    if result_set_id in active_ids:
        return PIN_ACTIVE
    if (
        result_set.cache_key is not None
        and newest_per_key.get(result_set.cache_key)
        == (result_set.created_at, result_set.id)
    ):
        return PIN_NEWEST_FOR_KEY
    if any(asset.id in pinned_ids for asset in assets):
        return PIN_ASSETS
    return ""


def compute_storage_report(
    *,
    storage_paths: StoragePaths,
    model_dirs: Sequence[Path] = (),
    project_repository: ProjectRepository,
    separation_repository: SeparationRepository,
    waveform_repository: WaveformCacheRepository | None = None,
    active_result_set_ids: Iterable[uuid.UUID] = (),
    pinned_asset_ids: Iterable[uuid.UUID] = (),
) -> StorageReport:
    """Compute the §9.5 storage split and the per-result-set breakdown.

    ``active_result_set_ids``: the sets selected by working projects
    (§9.5.3). ``pinned_asset_ids``: the caller's pin hook — assets
    referenced by retained edit history and by in-flight media jobs
    (§9.5.4, 6; M2.8 fills this in).
    """
    model_bytes = sum(_directory_bytes(d) for d in model_dirs)
    active_ids = frozenset(active_result_set_ids)
    pinned_ids = frozenset(pinned_asset_ids)

    project_bytes = 0
    # result-set id -> (entry fields, its stem assets)
    raw: dict[uuid.UUID, tuple[datetime, int, list[AssetRecord]]] = {}
    # Deduplicated stem-asset accounting (assets are shared by hash).
    unique_assets: dict[str, AssetRecord] = {}

    for project in project_repository.list_projects():
        for asset, _role in project_repository.list_project_assets(project.id):
            if asset.role is AssetRole.STEM:
                continue
            project_bytes += asset.byte_count
            project_bytes += _cache_bytes(waveform_repository, asset, storage_paths)

        for result_set in separation_repository.list_result_sets_for_project(project.id):
            assets = _stem_assets(separation_repository, project_repository, result_set.id)
            set_bytes = 0
            for asset in assets:
                set_bytes += asset.byte_count
                set_bytes += _cache_bytes(waveform_repository, asset, storage_paths)
                unique_assets.setdefault(asset.content_hash, asset)
            raw[result_set.id] = (result_set.created_at, set_bytes, assets)

    # Newest valid set per cache key: the lookup winner, pinned so that
    # "identical separation requests reuse results" survives reclaim.
    newest_per_key: dict[str, tuple[datetime, uuid.UUID]] = {}
    for result_set_id, (_created_at, _bytes, _assets) in raw.items():
        fetched = separation_repository.get_result_set(result_set_id)
        assert fetched is not None
        if fetched.cache_key is None:
            continue
        stamp = (fetched.created_at, fetched.id)
        current = newest_per_key.get(fetched.cache_key)
        if current is None or stamp > current:
            newest_per_key[fetched.cache_key] = stamp

    entries: list[ResultSetStorage] = []
    pinned_asset_hashes: set[str] = set()
    for result_set_id, (created_at, set_bytes, assets) in raw.items():
        fetched = separation_repository.get_result_set(result_set_id)
        assert fetched is not None
        reason = _pin_reason(
            result_set_id,
            fetched,
            active_ids,
            newest_per_key,
            assets,
            pinned_ids,
        )
        pinned = reason != ""
        if pinned:
            pinned_asset_hashes.update(asset.content_hash for asset in assets)
        entries.append(
            ResultSetStorage(
                result_set_id=result_set_id,
                created_at=created_at,
                bytes=set_bytes,
                pinned=pinned,
                pin_reason=reason,
            )
        )

    separation_bytes = 0
    pinned_stem_bytes = 0
    for content_hash, asset in unique_assets.items():
        asset_bytes = asset.byte_count + _cache_bytes(
            waveform_repository, asset, storage_paths
        )
        separation_bytes += asset_bytes
        if content_hash in pinned_asset_hashes:
            pinned_stem_bytes += asset_bytes

    entries.sort(key=lambda e: (e.created_at, e.result_set_id))
    return StorageReport(
        model_bytes=model_bytes,
        project_bytes=project_bytes,
        separation_result_bytes=separation_bytes,
        pinned_bytes=project_bytes + pinned_stem_bytes,
        reclaimable_bytes=separation_bytes - pinned_stem_bytes,
        total_bytes=model_bytes + project_bytes + separation_bytes,
        result_sets=tuple(entries),
    )


def reclaim_storage(
    *,
    report: StorageReport,
    limit_bytes: int,
    storage_paths: StoragePaths,
    project_repository: ProjectRepository,
    separation_repository: SeparationRepository,
    waveform_repository: WaveformCacheRepository | None = None,
) -> ReclaimResult:
    """Explicit cache reclaim (§9.5.7): LRU eviction under the limit.

    Evicts reclaimable result sets (oldest ``created_at`` first) until
    ``total - model`` fits ``limit_bytes``. Stem files are deleted only
    when no remaining result set references their content hash;
    waveform caches likewise per asset id. Records are never deleted.
    """
    over_by = report.total_bytes - report.model_bytes - limit_bytes
    if over_by <= 0:
        return ReclaimResult(bytes_freed=0, evicted_result_sets=(), files_removed=0)

    # Reference sets for dedup-safe deletion: every set in the report
    # (pinned sets are permanent survivors). ``live`` shrinks as sets are
    # evicted, so a file is deleted only when its last live referrer goes.
    hash_refs: dict[str, set[uuid.UUID]] = {}
    asset_refs: dict[uuid.UUID, set[uuid.UUID]] = {}
    all_sets: list[tuple[ResultSetStorage, list[AssetRecord]]] = []
    live: set[uuid.UUID] = set()
    for entry in report.result_sets:
        assets = _stem_assets(separation_repository, project_repository, entry.result_set_id)
        all_sets.append((entry, assets))
        live.add(entry.result_set_id)
        for asset in assets:
            hash_refs.setdefault(asset.content_hash, set()).add(entry.result_set_id)
            asset_refs.setdefault(asset.id, set()).add(entry.result_set_id)
    evictable = [pair for pair in all_sets if not pair[0].pinned]
    evictable.sort(key=lambda pair: (pair[0].created_at, pair[0].result_set_id))

    freed = 0
    files_removed = 0
    evicted: list[uuid.UUID] = []
    for entry, assets in evictable:
        if freed >= over_by:
            break
        evicted.append(entry.result_set_id)
        live.discard(entry.result_set_id)
        for asset in assets:
            if not (hash_refs.get(asset.content_hash, set()) & live):
                path = storage_paths.resolve_asset_path(asset.relative_path)
                if path.is_file():
                    freed += path.stat().st_size
                    files_removed += 1
                    path.unlink()
            cache_record = (
                waveform_repository.get_for_asset(asset.id) if waveform_repository else None
            )
            if cache_record is not None and not (asset_refs.get(asset.id, set()) & live):
                manifest = storage_paths.resolve_asset_path(cache_record.manifest_path)
                cache_dir = manifest.parent
                if cache_dir.is_dir():
                    freed += _directory_bytes(cache_dir)
                    files_removed += sum(1 for p in cache_dir.rglob("*") if p.is_file())
                    shutil.rmtree(cache_dir)
                if waveform_repository is not None:
                    waveform_repository.delete_for_asset(asset.id)
    return ReclaimResult(
        bytes_freed=freed,
        evicted_result_sets=tuple(evicted),
        files_removed=files_removed,
    )
