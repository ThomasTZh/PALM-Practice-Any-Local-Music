"""Integration tests for the storage policy (M2.7, spec §9.5).

Covers the report split (model storage counted separately, project vs
separation bytes), the pinning rules (active set, newest per cache key,
the caller pin hook), and the explicit LRU reclaim (eviction under the
limit, pinned bytes untouched, dedup-safe file deletion, waveform
cache removal, records and edits surviving).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.separation import (
    DeviceType,
    ReferenceMixIdentity,
    SeparationMode,
    SeparationResultSet,
    SeparationRun,
    SeparationRunStatus,
    SourceIdentity,
    StemRecord,
    StemRole,
    ValidationStatus,
)
from basseparate.media.storage_report import (
    PIN_ACTIVE,
    PIN_ASSETS,
    PIN_NEWEST_FOR_KEY,
    compute_storage_report,
    reclaim_storage,
)
from basseparate.storage.db import initialize_database
from basseparate.storage.paths import resolve_storage_paths
from basseparate.storage.repository import (
    ProjectRepository,
    SeparationRepository,
    WaveformCacheRepository,
)

KEY = "aa" * 32
OTHER_KEY = "bb" * 32
FRAMES = 125
CHANNELS = 2
RATE = 48_000
STEM_BYTES = FRAMES * CHANNELS * 4  # 1000
SET_BYTES = 4 * STEM_BYTES
LABELS = ("vocals", "drums", "bass", "other")


@pytest.fixture()
def storage_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def paths(storage_root: Path):
    return resolve_storage_paths(storage_root)


@pytest.fixture()
def db_path(paths) -> Path:
    initialize_database(paths.database_path)
    return paths.database_path


@pytest.fixture()
def projects(db_path: Path) -> ProjectRepository:
    return ProjectRepository(db_path)


@pytest.fixture()
def separation(db_path: Path) -> SeparationRepository:
    return SeparationRepository(db_path)


def _write_asset(paths, asset: AssetRecord, content: bytes | None = None) -> None:
    target = paths.data / "assets" / f"{asset.content_hash}.pcm"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content if content is not None else b"\x00" * asset.byte_count)


def _asset(content_hash: str, byte_count: int, created_at: datetime) -> AssetRecord:
    return AssetRecord(
        id=uuid.uuid4(),
        content_hash=content_hash,
        role=AssetRole.STEM,
        relative_path=f"data/assets/{content_hash}.pcm",
        media_type="application/octet-stream",
        byte_count=byte_count,
        created_at=created_at,
        audio=AudioMetadata(
            sample_rate=RATE,
            channel_count=CHANNELS,
            frame_count=FRAMES,
            sample_format="f32le",
        ),
    )


def _publish_set(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    project_id: uuid.UUID,
    cache_key: str | None,
    created_at: datetime,
    shared_stem_asset: AssetRecord | None = None,
) -> tuple[SeparationResultSet, list[AssetRecord]]:
    """Publish a minimal valid four-stem result set and write its assets.

    ``shared_stem_asset`` replaces the first stem's asset (dedup test).
    """
    result_set_id = uuid.uuid4()
    run = SeparationRun(
        id=uuid.uuid4(),
        project_id=project_id,
        input_asset_id=uuid.uuid4(),
        input_transform_hash="ab" * 32,
        requested_mode=SeparationMode.FOUR_STEMS,
        model_manifest_id=uuid.uuid4(),
        model_manifest_hash="cd" * 32,
        engine_version="demucs-4.1.0",
        adapter_version="outer-window-v1",
        device_type=DeviceType.CPU,
        status=SeparationRunStatus.QUEUED,
        cache_key=cache_key,
    )
    separation.create_run(run)
    stems: list[StemRecord] = []
    assets: list[AssetRecord] = []
    for index, label in enumerate(LABELS):
        if index == 0 and shared_stem_asset is not None:
            asset = shared_stem_asset
        else:
            asset = _asset(uuid.uuid4().hex * 2, STEM_BYTES, created_at)
            assets.append(asset)
        stems.append(
            StemRecord(
                id=uuid.uuid4(),
                result_set_id=result_set_id,
                role=StemRole(label),
                display_name=label.title(),
                audio_asset_id=asset.id,
                sample_rate=RATE,
                channel_count=CHANNELS,
                frame_count=FRAMES,
                confidence=Confidence(kind=ConfidenceKind.UNAVAILABLE),
            )
        )
    result_set = SeparationResultSet(
        id=result_set_id,
        run_id=run.id,
        project_id=project_id,
        source=SourceIdentity(
            asset_id=uuid.uuid4(),
            source_hash="ab" * 32,
            sample_rate=RATE,
            duration_frames=FRAMES,
        ),
        output_sample_rate=RATE,
        output_channel_count=CHANNELS,
        output_frame_count=FRAMES,
        available_stem_roles=list(map(StemRole, LABELS)),
        stem_ids=[stem.id for stem in stems],
        reference_mix=ReferenceMixIdentity(
            asset_id=uuid.uuid4(), hash="cd" * 32, transformation_hash="ef" * 32
        ),
        validation_status=ValidationStatus.VALID,
        created_at=created_at,
        cache_key=cache_key,
    )
    completed = run.model_copy(
        update={
            "status": SeparationRunStatus.COMPLETED,
            "result_set_id": result_set_id,
            "started_at": created_at,
            "ended_at": created_at,
        }
    )
    separation.publish_result_set(completed, result_set, stems, assets)
    for asset in assets:
        _write_asset(paths, asset)
    return result_set, assets


def _add_source_asset(projects: ProjectRepository, paths, project_id: uuid.UUID) -> None:
    """A 5000-byte canonical source asset (always pinned)."""
    now = datetime.now(UTC)
    source = AssetRecord(
        id=uuid.uuid4(),
        content_hash="cc" * 32,
        role=AssetRole.SOURCE_PCM,
        relative_path=f"data/assets/cc{'0' * 62}.pcm",
        media_type="application/octet-stream",
        byte_count=5000,
        created_at=now,
        audio=AudioMetadata(
            sample_rate=RATE, channel_count=CHANNELS, frame_count=625, sample_format="f32le"
        ),
    )
    projects.register_asset(source)
    projects.attach_asset(project_id, source.id, AssetRole.SOURCE_PCM)
    _write_asset(paths, source)


def _model_dir(storage_root: Path, size: int = 8192) -> Path:
    model_dir = storage_root / "models" / "baseline"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "weights.bin").write_bytes(b"\x00" * size)
    return model_dir


def _add_waveform_cache(db_path: Path, paths, asset: AssetRecord) -> Path:
    """A waveform_caches row + on-disk cache dir for a stem asset."""
    cache_dir = paths.cache / "waveforms" / asset.content_hash
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "manifest.json").write_text("{}")
    (cache_dir / "tiles.bin").write_bytes(b"\x00" * 256)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO waveform_caches (id, asset_id, cache_version, source_hash,
                                         sample_rate, frame_count, channel_count,
                                         levels_json, manifest_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                str(asset.id),
                1,
                asset.content_hash,
                RATE,
                FRAMES,
                CHANNELS,
                '[{"bucket_frame_count": 1, "bucket_count": 1, '
                '"tile_count": 1, "final_tile_buckets": 1}]',
                f"cache/waveforms/{asset.content_hash}/manifest.json",
                datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            ),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()
    return cache_dir


def test_report_counts_model_separately(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    storage_root: Path,
) -> None:
    model_dir = _model_dir(storage_root, 8192)
    project = projects.create_project("Song")
    _publish_set(
        separation, projects, paths, project.id, KEY, datetime(2026, 1, 1, tzinfo=UTC)
    )
    report = compute_storage_report(
        storage_paths=paths,
        model_dirs=[model_dir],
        project_repository=projects,
        separation_repository=separation,
    )
    assert report.model_bytes == 8192
    assert report.project_bytes == 0
    assert report.separation_result_bytes == SET_BYTES
    assert report.total_bytes == 8192 + SET_BYTES
    # Reclaim under a tiny limit must not touch model storage.
    result = reclaim_storage(
        report=report,
        limit_bytes=0,
        storage_paths=paths,
        project_repository=projects,
        separation_repository=separation,
    )
    assert (model_dir / "weights.bin").is_file()
    assert result.bytes_freed == 0  # the only set is newest-per-key pinned


def test_report_splits_project_and_separation(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    storage_root: Path,
) -> None:
    _model_dir(storage_root)
    project = projects.create_project("Song")
    _add_source_asset(projects, paths, project.id)
    _publish_set(
        separation, projects, paths, project.id, KEY, datetime(2026, 1, 1, tzinfo=UTC)
    )
    report = compute_storage_report(
        storage_paths=paths,
        model_dirs=[],
        project_repository=projects,
        separation_repository=separation,
    )
    assert report.project_bytes == 5000
    assert report.separation_result_bytes == SET_BYTES
    assert report.pinned_bytes == 5000 + SET_BYTES  # source + newest-per-key set
    assert report.reclaimable_bytes == 0
    assert report.total_bytes == 5000 + SET_BYTES


def test_report_pinning_rules(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    storage_root: Path,
) -> None:
    project = projects.create_project("Song")
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, tzinfo=UTC)
    older, _ = _publish_set(separation, projects, paths, project.id, KEY, t1)
    newest, _ = _publish_set(separation, projects, paths, project.id, KEY, t2)
    # Same key as the other two: not the newest → the only reclaimable set.
    # (A set with a key of its own would be pinned as newest-for-key.)
    other_old, _ = _publish_set(separation, projects, paths, project.id, KEY, t1)

    report = compute_storage_report(
        storage_paths=paths,
        model_dirs=[],
        project_repository=projects,
        separation_repository=separation,
        active_result_set_ids=[older.id],
    )
    by_id = {entry.result_set_id: entry for entry in report.result_sets}
    assert by_id[older.id].pinned and by_id[older.id].pin_reason == PIN_ACTIVE
    assert by_id[newest.id].pinned and by_id[newest.id].pin_reason == PIN_NEWEST_FOR_KEY
    assert not by_id[other_old.id].pinned
    assert report.reclaimable_bytes == SET_BYTES
    assert report.pinned_bytes == 2 * SET_BYTES


def test_report_pin_hook(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    storage_root: Path,
) -> None:
    """The M2.8 hook: caller-pinned assets pin their result set."""
    project = projects.create_project("Song")
    # No cache key: not active, not newest-per-key → only the hook pins.
    result_set, assets = _publish_set(
        separation, projects, paths, project.id, None, datetime(2026, 1, 1, tzinfo=UTC)
    )
    report = compute_storage_report(
        storage_paths=paths,
        model_dirs=[],
        project_repository=projects,
        separation_repository=separation,
        pinned_asset_ids=[assets[0].id],
    )
    entry = report.result_sets[0]
    assert entry.result_set_id == result_set.id
    assert entry.pinned and entry.pin_reason == PIN_ASSETS
    assert report.reclaimable_bytes == 0


def test_reclaim_noop_under_limit(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    storage_root: Path,
) -> None:
    project = projects.create_project("Song")
    result_set, assets = _publish_set(
        separation, projects, paths, project.id, KEY, datetime(2026, 1, 1, tzinfo=UTC)
    )
    report = compute_storage_report(
        storage_paths=paths,
        model_dirs=[],
        project_repository=projects,
        separation_repository=separation,
    )
    result = reclaim_storage(
        report=report,
        limit_bytes=report.total_bytes,
        storage_paths=paths,
        project_repository=projects,
        separation_repository=separation,
    )
    assert result.bytes_freed == 0
    assert result.evicted_result_sets == ()
    assert result.files_removed == 0
    for asset in assets:
        assert (paths.data / "assets" / f"{asset.content_hash}.pcm").is_file()


def test_reclaim_evicts_lru_until_under_limit(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    storage_root: Path,
) -> None:
    project = projects.create_project("Song")
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, tzinfo=UTC)
    t3 = datetime(2026, 1, 3, tzinfo=UTC)
    set1, assets1 = _publish_set(separation, projects, paths, project.id, KEY, t1)
    set2, assets2 = _publish_set(separation, projects, paths, project.id, KEY, t2)
    set3, assets3 = _publish_set(separation, projects, paths, project.id, KEY, t3)

    # Total 4 * SET_BYTES; limit forces eviction of the two oldest.
    report = compute_storage_report(
        storage_paths=paths,
        model_dirs=[],
        project_repository=projects,
        separation_repository=separation,
    )
    result = reclaim_storage(
        report=report,
        limit_bytes=SET_BYTES,  # keep only the newest (pinned) set
        storage_paths=paths,
        project_repository=projects,
        separation_repository=separation,
    )
    assert result.evicted_result_sets == (set1.id, set2.id)
    assert result.bytes_freed == 2 * SET_BYTES
    assert result.files_removed == 8
    for asset in [*assets1, *assets2]:
        assert not (paths.data / "assets" / f"{asset.content_hash}.pcm").exists()
    for asset in assets3:
        assert (paths.data / "assets" / f"{asset.content_hash}.pcm").is_file()
    # Records are never deleted: all three sets (and their stems) survive.
    for result_set in (set1, set2, set3):
        assert separation.get_result_set(result_set.id) is not None
        assert len(separation.list_stems_for_result_set(result_set.id)) == 4


def test_reclaim_never_touches_pinned(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    storage_root: Path,
) -> None:
    project = projects.create_project("Song")
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, tzinfo=UTC)
    active, active_assets = _publish_set(separation, projects, paths, project.id, KEY, t1)
    newest, _ = _publish_set(separation, projects, paths, project.id, KEY, t2)

    # Both sets are pinned (active + newest-per-key): nothing is evictable.
    report = compute_storage_report(
        storage_paths=paths,
        model_dirs=[],
        project_repository=projects,
        separation_repository=separation,
        active_result_set_ids=[active.id],
    )
    assert report.reclaimable_bytes == 0
    result = reclaim_storage(
        report=report,
        limit_bytes=0,
        storage_paths=paths,
        project_repository=projects,
        separation_repository=separation,
    )
    assert result.bytes_freed == 0
    assert result.evicted_result_sets == ()
    for asset in active_assets:
        assert (paths.data / "assets" / f"{asset.content_hash}.pcm").is_file()


def test_reclaim_dedup_shared_assets(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    storage_root: Path,
) -> None:
    project = projects.create_project("Song")
    shared = _asset(uuid.uuid4().hex * 2, STEM_BYTES, datetime(2026, 1, 1, tzinfo=UTC))
    # The shared stem asset is registered once; both sets reference it.
    projects.register_asset(shared)
    projects.attach_asset(project.id, shared.id, AssetRole.STEM)
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, tzinfo=UTC)
    # No cache key: neither set is newest-per-key, so both are evictable.
    old, old_assets = _publish_set(
        separation, projects, paths, project.id, None, t1, shared_stem_asset=shared
    )
    new, new_assets = _publish_set(
        separation, projects, paths, project.id, None, t2, shared_stem_asset=shared
    )
    _write_asset(paths, shared)
    shared_path = paths.data / "assets" / f"{shared.content_hash}.pcm"

    report = compute_storage_report(
        storage_paths=paths,
        model_dirs=[],
        project_repository=projects,
        separation_repository=separation,
    )
    # The shared file is counted once, not twice.
    assert report.separation_result_bytes == 2 * SET_BYTES - STEM_BYTES

    # Evicting the older set must not delete the shared file (the newer
    # set still references it).
    result = reclaim_storage(
        report=report,
        limit_bytes=SET_BYTES,
        storage_paths=paths,
        project_repository=projects,
        separation_repository=separation,
    )
    assert result.evicted_result_sets == (old.id,)
    assert shared_path.is_file()
    for asset in old_assets[1:]:
        assert not (paths.data / "assets" / f"{asset.content_hash}.pcm").exists()

    # Evicting the newer set finally removes the shared file.
    report2 = compute_storage_report(
        storage_paths=paths,
        model_dirs=[],
        project_repository=projects,
        separation_repository=separation,
    )
    result2 = reclaim_storage(
        report=report2,
        limit_bytes=0,
        storage_paths=paths,
        project_repository=projects,
        separation_repository=separation,
    )
    # The (already empty) older set is evicted again, idempotently.
    assert result2.evicted_result_sets == (old.id, new.id)
    assert result2.bytes_freed == SET_BYTES
    assert not shared_path.exists()
    for asset in new_assets[1:]:
        assert not (paths.data / "assets" / f"{asset.content_hash}.pcm").exists()


def test_reclaim_removes_waveform_caches(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    db_path: Path,
    storage_root: Path,
) -> None:
    waveform = WaveformCacheRepository(db_path, paths.cache / "waveforms")
    project = projects.create_project("Song")
    # Two sets, same key: the older is evictable, the newest pinned.
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, tzinfo=UTC)
    old, old_assets = _publish_set(separation, projects, paths, project.id, KEY, t1)
    _publish_set(separation, projects, paths, project.id, KEY, t2)
    cache_dir = _add_waveform_cache(db_path, paths, old_assets[0])
    assert waveform.get_for_asset(old_assets[0].id) is not None

    report = compute_storage_report(
        storage_paths=paths,
        model_dirs=[],
        project_repository=projects,
        separation_repository=separation,
        waveform_repository=waveform,
    )
    # The cache dir bytes are counted with the stem asset.
    assert report.separation_result_bytes == 2 * SET_BYTES + 256 + len("{}")

    result = reclaim_storage(
        report=report,
        limit_bytes=SET_BYTES,
        storage_paths=paths,
        project_repository=projects,
        separation_repository=separation,
        waveform_repository=waveform,
    )
    assert result.evicted_result_sets == (old.id,)
    assert not cache_dir.exists()
    assert waveform.get_for_asset(old_assets[0].id) is None


def test_edits_survive_reclaim(
    separation: SeparationRepository,
    projects: ProjectRepository,
    paths,
    db_path: Path,
    storage_root: Path,
) -> None:
    """Acceptance: edits never disappear because a cache entry was
    reclaimed — they are project rows, not assets."""
    project = projects.create_project("Song")
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, tzinfo=UTC)
    _publish_set(separation, projects, paths, project.id, KEY, t1)
    _publish_set(separation, projects, paths, project.id, KEY, t2)
    before = projects.get_project(project.id)
    assert before is not None

    conn = sqlite3.connect(str(db_path))
    history_before = conn.execute("SELECT COUNT(*) FROM project_history").fetchone()[0]
    conn.close()

    report = compute_storage_report(
        storage_paths=paths,
        model_dirs=[],
        project_repository=projects,
        separation_repository=separation,
    )
    reclaim_storage(
        report=report,
        limit_bytes=SET_BYTES,
        storage_paths=paths,
        project_repository=projects,
        separation_repository=separation,
    )

    after = projects.get_project(project.id)
    assert after is not None
    assert after.name == before.name
    assert after.working_state == before.working_state
    assert after.practice_state == before.practice_state
    conn = sqlite3.connect(str(db_path))
    history_after = conn.execute("SELECT COUNT(*) FROM project_history").fetchone()[0]
    conn.close()
    assert history_after == history_before
