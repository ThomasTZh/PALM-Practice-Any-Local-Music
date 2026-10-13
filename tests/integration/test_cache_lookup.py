"""Integration tests for the analysis cache lookup (M2.7, spec §9.2).

Covers the lookup service (hit, miss on missing/partial/corrupted
assets, the optional re-hash pass, the residual), the repository
primitives (newest-valid winner, live-run-only coalescing), and the
coalescing composition the M2.17 scheduler will use.
"""

from __future__ import annotations

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
from basseparate.media.separation_cache import lookup_cached_result
from basseparate.storage.db import DatabaseError, initialize_database
from basseparate.storage.repository import ProjectRepository, SeparationRepository

KEY_A = "aa" * 32
KEY_B = "bb" * 32
FRAMES = 100
CHANNELS = 2
RATE = 48_000
EXPECTED_BYTES = FRAMES * CHANNELS * 4
LABELS = ("vocals", "drums", "bass", "other")


@pytest.fixture()
def storage_root(tmp_path: Path) -> Path:
    (tmp_path / "data" / "assets").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def db_path(storage_root: Path) -> Path:
    path = storage_root / "data" / "basseparate.db"
    initialize_database(path)
    return path


@pytest.fixture()
def projects(db_path: Path) -> ProjectRepository:
    return ProjectRepository(db_path)


@pytest.fixture()
def separation(db_path: Path) -> SeparationRepository:
    return SeparationRepository(db_path)


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


def _make_run(
    project_id: uuid.UUID,
    cache_key: str,
    status: SeparationRunStatus = SeparationRunStatus.QUEUED,
) -> SeparationRun:
    return SeparationRun(
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
        status=status,
        cache_key=cache_key,
    )


def _publish_valid_set(
    separation: SeparationRepository,
    storage_root: Path,
    project_id: uuid.UUID,
    cache_key: str,
    created_at: datetime,
    with_residual: bool = False,
    run: SeparationRun | None = None,
) -> tuple[SeparationResultSet, list[AssetRecord]]:
    """Publish a minimal valid four-stem result set and write its assets.

    ``run`` may be an existing in-flight run (already created) — the
    publication completes it; otherwise a fresh queued run is created.
    """
    if run is None:
        run = separation.create_run(_make_run(project_id, cache_key))
    result_set_id = uuid.uuid4()
    stems: list[StemRecord] = []
    assets: list[AssetRecord] = []
    for label in LABELS:
        asset = _asset(uuid.uuid4().hex * 2, EXPECTED_BYTES, created_at)
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
    residual_id: uuid.UUID | None = None
    if with_residual:
        residual = _asset(uuid.uuid4().hex * 2, EXPECTED_BYTES, created_at)
        assets.append(residual)
        residual_id = residual.id
    result_set = SeparationResultSet(
        id=result_set_id,
        run_id=run.id,
        project_id=project_id,
        source=SourceIdentity(
            asset_id=uuid.uuid4(), source_hash="ab" * 32, sample_rate=RATE, duration_frames=FRAMES
        ),
        output_sample_rate=RATE,
        output_channel_count=CHANNELS,
        output_frame_count=FRAMES,
        available_stem_roles=[
            *map(StemRole, LABELS),
            *([StemRole.OTHERS] if with_residual else []),
        ],
        stem_ids=[stem.id for stem in stems],
        bass_residual_asset_id=residual_id,
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
        (storage_root / asset.relative_path).write_bytes(b"\x00" * asset.byte_count)
    return result_set, assets


def _lookup(
    separation: SeparationRepository,
    projects: ProjectRepository,
    storage_root: Path,
    project_id: uuid.UUID,
    cache_key: str,
    verify_hashes: bool = False,
) -> SeparationResultSet | None:
    return lookup_cached_result(
        project_id=project_id,
        cache_key=cache_key,
        storage_root=storage_root,
        separation_repository=separation,
        asset_repository=projects,
        verify_hashes=verify_hashes,
    )


def _first_asset_file(storage_root: Path) -> Path:
    return next(iter((storage_root / "data" / "assets").iterdir()))


def test_lookup_hit(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    project = projects.create_project("Song")
    result_set, _ = _publish_valid_set(
        separation, storage_root, project.id, KEY_A, datetime.now(UTC)
    )
    got = _lookup(separation, projects, storage_root, project.id, KEY_A)
    assert got is not None and got.id == result_set.id


def test_lookup_hit_with_residual(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    project = projects.create_project("Song")
    result_set, _ = _publish_valid_set(
        separation, storage_root, project.id, KEY_A, datetime.now(UTC), with_residual=True
    )
    assert result_set.bass_residual_asset_id is not None
    got = _lookup(separation, projects, storage_root, project.id, KEY_A)
    assert got is not None and got.id == result_set.id


def test_lookup_miss_without_result_set(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    project = projects.create_project("Song")
    assert _lookup(separation, projects, storage_root, project.id, KEY_A) is None


def test_lookup_miss_unknown_key(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    project = projects.create_project("Song")
    _publish_valid_set(separation, storage_root, project.id, KEY_A, datetime.now(UTC))
    assert _lookup(separation, projects, storage_root, project.id, KEY_B) is None


def test_lookup_miss_missing_asset(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    project = projects.create_project("Song")
    result_set, assets = _publish_valid_set(
        separation, storage_root, project.id, KEY_A, datetime.now(UTC)
    )
    (storage_root / assets[0].relative_path).unlink()
    assert _lookup(separation, projects, storage_root, project.id, KEY_A) is None
    # The record is untouched: only the bytes are missing.
    assert separation.get_result_set(result_set.id) is not None


def test_lookup_miss_partial_file(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    project = projects.create_project("Song")
    _publish_valid_set(separation, storage_root, project.id, KEY_A, datetime.now(UTC))
    # Truncate one stem asset (a partial write): exact-size check fails.
    _first_asset_file(storage_root).write_bytes(b"\x00" * (EXPECTED_BYTES // 2))
    assert _lookup(separation, projects, storage_root, project.id, KEY_A) is None


def test_lookup_fast_path_ignores_byte_corruption(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    """The content-addressed name + exact size is the normal guarantee."""
    project = projects.create_project("Song")
    result_set, assets = _publish_valid_set(
        separation, storage_root, project.id, KEY_A, datetime.now(UTC)
    )
    (storage_root / assets[0].relative_path).write_bytes(b"\xff" * EXPECTED_BYTES)
    got = _lookup(separation, projects, storage_root, project.id, KEY_A)
    assert got is not None and got.id == result_set.id


def test_lookup_verify_hashes_catches_corruption(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    project = projects.create_project("Song")
    _publish_valid_set(separation, storage_root, project.id, KEY_A, datetime.now(UTC))
    _first_asset_file(storage_root).write_bytes(b"\xff" * EXPECTED_BYTES)
    assert (
        _lookup(separation, projects, storage_root, project.id, KEY_A, verify_hashes=True)
        is None
    )


def test_lookup_miss_residual_missing(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    project = projects.create_project("Song")
    _publish_valid_set(
        separation, storage_root, project.id, KEY_A, datetime.now(UTC), with_residual=True
    )
    # The residual is the last asset written.
    residual = _first_asset_file(storage_root)  # any one file is enough to break the hit
    residual.unlink()
    assert _lookup(separation, projects, storage_root, project.id, KEY_A) is None


def test_lookup_miss_invalid_result_set(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    """Pending/invalid sets never match, even with all assets present."""
    project = projects.create_project("Song")
    run = separation.create_run(_make_run(project.id, KEY_A))
    pending = SeparationResultSet(
        id=uuid.uuid4(),
        run_id=run.id,
        project_id=project.id,
        source=SourceIdentity(
            asset_id=uuid.uuid4(), source_hash="ab" * 32, sample_rate=RATE, duration_frames=FRAMES
        ),
        output_sample_rate=RATE,
        output_channel_count=CHANNELS,
        output_frame_count=FRAMES,
        reference_mix=ReferenceMixIdentity(
            asset_id=uuid.uuid4(), hash="cd" * 32, transformation_hash="ef" * 32
        ),
        validation_status=ValidationStatus.PENDING,
        created_at=datetime.now(UTC),
        cache_key=KEY_A,
    )
    separation.create_result_set(pending)
    assert _lookup(separation, projects, storage_root, project.id, KEY_A) is None


def test_find_valid_result_set_newest_wins(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    project = projects.create_project("Song")
    older, _ = _publish_valid_set(
        separation, storage_root, project.id, KEY_A, datetime(2026, 1, 1, tzinfo=UTC)
    )
    newer, _ = _publish_valid_set(
        separation, storage_root, project.id, KEY_A, datetime(2026, 1, 2, tzinfo=UTC)
    )
    got = separation.find_valid_result_set(project.id, KEY_A)
    assert got is not None and got.id == newer.id
    assert older.id != newer.id


def test_find_active_run_live_states_only(
    separation: SeparationRepository, projects: ProjectRepository
) -> None:
    project = projects.create_project("Song")
    for status in (
        SeparationRunStatus.QUEUED,
        SeparationRunStatus.RUNNING,
        SeparationRunStatus.CANCELLED,
        SeparationRunStatus.FAILED,
        SeparationRunStatus.INTERRUPTED,
    ):
        separation.create_run(_make_run(project.id, KEY_A, status))
    got = separation.find_active_run(project.id, KEY_A)
    assert got is not None
    assert got.status in (SeparationRunStatus.QUEUED, SeparationRunStatus.RUNNING)
    # A key with no runs at all:
    assert separation.find_active_run(project.id, KEY_B) is None


def test_coalescing_primitives(
    separation: SeparationRepository,
    projects: ProjectRepository,
    storage_root: Path,
) -> None:
    """§9.2.6–7 composition: an identical in-flight run is coalesced
    (no duplicate job), and once it publishes the lookup serves the
    result."""
    project = projects.create_project("Song")
    in_flight = separation.create_run(_make_run(project.id, KEY_A, SeparationRunStatus.RUNNING))
    # While the run is in flight: no cached result, one live run.
    assert _lookup(separation, projects, storage_root, project.id, KEY_A) is None
    assert separation.find_active_run(project.id, KEY_A) is not None
    assert separation.find_active_run(project.id, KEY_A).id == in_flight.id
    # The same run completes and publishes: the lookup now hits and the
    # run is no longer live (nothing to coalesce).
    _publish_valid_set(
        separation, storage_root, project.id, KEY_A, datetime.now(UTC), run=in_flight
    )
    got = _lookup(separation, projects, storage_root, project.id, KEY_A)
    assert got is not None
    assert separation.find_active_run(project.id, KEY_A) is None


def test_publish_rejects_run_set_key_mismatch(
    separation: SeparationRepository, projects: ProjectRepository, storage_root: Path
) -> None:
    """Phase 2 guard: a run and its result set must agree on the key."""
    project = projects.create_project("Song")
    run = separation.create_run(_make_run(project.id, KEY_A))
    result_set_id = uuid.uuid4()
    now = datetime.now(UTC)
    stems: list[StemRecord] = []
    assets: list[AssetRecord] = []
    for label in LABELS:
        asset = _asset(uuid.uuid4().hex * 2, EXPECTED_BYTES, now)
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
        project_id=project.id,
        source=SourceIdentity(
            asset_id=uuid.uuid4(), source_hash="ab" * 32, sample_rate=RATE, duration_frames=FRAMES
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
        created_at=now,
        cache_key=KEY_B,  # disagrees with the run's KEY_A
    )
    completed = run.model_copy(
        update={
            "status": SeparationRunStatus.COMPLETED,
            "result_set_id": result_set_id,
            "started_at": now,
            "ended_at": now,
        }
    )
    with pytest.raises(DatabaseError, match="cache keys must match"):
        separation.publish_result_set(completed, result_set, stems, assets)
