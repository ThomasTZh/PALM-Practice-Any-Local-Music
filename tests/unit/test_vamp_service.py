"""Service tests for cached Vamp branch publication."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.storage.db import initialize_database
from basseparate.storage.paths import resolve_storage_paths
from basseparate.storage.repository import ProjectRepository, RhythmRepository
from basseparate.vamp.features import VampAnalysis, VampEvent
from basseparate.vamp.service import VampAnalysisService

NOW = datetime(2026, 10, 25, tzinfo=UTC)


@pytest.fixture()
def setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ProjectRepository, RhythmRepository, VampAnalysisService, uuid.UUID]:
    paths = resolve_storage_paths(tmp_path / "store")
    paths.data.mkdir(parents=True)
    paths.cache.mkdir(parents=True)
    db = paths.database_path
    initialize_database(db)
    repo = ProjectRepository(db)
    project = repo.create_project("Vamp")
    asset_id = uuid.uuid4()
    pcm = paths.data / "assets" / "source.f32"
    pcm.parent.mkdir(parents=True)
    pcm.write_bytes(b"\x00" * 64)
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            """
            UPDATE projects SET status='ready', source_asset_id=?, canonical_asset_id=?,
                source_stream_index=0, sample_rate=48000, duration_frames=480000,
                source_channel_count=1, source_channel_layout='mono',
                decode_profile_version=1
            WHERE id=?
            """,
            (str(uuid.uuid4()), str(asset_id), str(project.id)),
        )
        conn.execute(
            """
            INSERT INTO assets (id, content_hash, role, relative_path, media_type,
                                byte_count, created_at, audio_sample_rate,
                                audio_channel_count, audio_frame_count,
                                audio_sample_format)
            VALUES (?, ?, 'source_pcm', 'data/assets/source.f32', 'audio/x-raw',
                    64, ?, 48000, 1, 16, 'f32le')
            """,
            (str(asset_id), "a" * 64, NOW.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    calls = 0

    def fake_analyze(*args: object, **kwargs: object) -> VampAnalysis:
        nonlocal calls
        calls += 1
        return VampAnalysis(
            plugin_key="qm-vamp-plugins:qm-barbeattracker",
            plugin_version="3",
            sample_rate=48000,
            bpb=4,
            features={
                "beats": tuple(
                    VampEvent(time_seconds=value) for value in (0.5, 1.0, 1.5, 2.0, 2.5)
                ),
                "bars": (VampEvent(time_seconds=0.5), VampEvent(time_seconds=2.5)),
            },
        )

    monkeypatch.setattr("basseparate.vamp.service.analyze_pcm", fake_analyze)
    service = VampAnalysisService(
        storage_paths=paths,
        repository=repo,
        rhythm_repository=RhythmRepository(db),
        server_path=str(tmp_path / "server"),
        plugin_path=str(tmp_path / "plugins"),
        library_path="",
        timeout_seconds=30,
    )
    return repo, RhythmRepository(db), service, project.id


def test_publishes_branch_and_uses_cache(setup) -> None:
    repo, rhythm, service, project_id = setup
    first = service.analyze(project_id, 4)
    assert first.cached is False
    assert first.beats == 5
    assert first.bars == 2
    project = repo.get_project(project_id)
    assert project is not None
    assert project.rhythm_state.active_branch_id == first.branch.id
    assert rhythm.get_branch(first.branch.id).pulses == first.branch.pulses

    second = service.analyze(project_id, 4)
    assert second.cached is True
    assert second.branch.id != first.branch.id


def test_rejects_invalid_bpb(setup) -> None:
    _repo, _rhythm, service, project_id = setup
    with pytest.raises(Exception, match="bpb"):
        service.analyze(project_id, 5)
