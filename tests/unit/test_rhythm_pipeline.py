"""Analyze Rhythm run graph entry points (M3.17 §19.2-§19.3)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from basseparate.models.rhythm_registry import (
    get_rhythm_model,
    rhythm_manifest_hash,
)
from basseparate.rhythm.pipeline import (
    RhythmPipelineError,
    RhythmPipelineService,
    RhythmRunRequest,
)
from basseparate.storage import ProjectRepository, RhythmRepository
from basseparate.storage.db import initialize_database
from basseparate.storage.paths import resolve_storage_paths


def _service(tmp_path: Path) -> tuple[RhythmPipelineService, ProjectRepository, RhythmRepository]:
    root = tmp_path / "store"
    paths = resolve_storage_paths(root)
    paths.data.mkdir(parents=True, exist_ok=True)
    db = paths.database_path
    initialize_database(db)
    projects = ProjectRepository(db)
    rhythm = RhythmRepository(db)
    return (
        RhythmPipelineService(paths=paths, projects=projects, rhythm=rhythm),
        projects,
        rhythm,
    )


def test_unknown_project_is_reported(tmp_path: Path) -> None:
    service, _projects, _rhythm = _service(tmp_path)
    with pytest.raises(RhythmPipelineError) as caught:
        service.start(uuid.uuid4(), RhythmRunRequest())
    assert caught.value.code == "PROJECT_NOT_FOUND"


def test_uninstalled_model_is_reported_before_any_run_row(tmp_path: Path) -> None:
    service, projects, rhythm = _service(tmp_path)
    project = projects.create_project("Pipeline")
    with pytest.raises(RhythmPipelineError) as caught:
        service.start(project.id, RhythmRunRequest())
    assert caught.value.code == "RHYTHM_MODEL_NOT_INSTALLED"
    assert rhythm.list_runs_for_project(project.id) == []


def test_manifest_identity_is_stable_and_sensitive() -> None:
    manifest = get_rhythm_model("beat_this_final0")
    assert rhythm_manifest_hash(manifest) == rhythm_manifest_hash(manifest)
    changed = replace(manifest, model_id="beat_this_final0_x")
    assert rhythm_manifest_hash(changed) != rhythm_manifest_hash(manifest)


def test_bar_origin_starts_at_the_first_meter_region() -> None:
    """A meter selection after musical zero must still produce a grid."""
    from datetime import UTC, datetime

    from basseparate.domain.meter import ManualMeterRegion, build_meter_map, manual_candidate
    from basseparate.domain.rhythm import MusicalPosition
    from basseparate.domain.tempo import PULSE_UNIT_QUARTER, TempoMap, TempoMapAnchor
    from basseparate.rhythm.grid import derive_grid
    from basseparate.rhythm.pipeline import automatic_bar_origin

    now = datetime(2020, 1, 1, tzinfo=UTC)
    project_id = uuid.uuid4()
    anchors = [
        TempoMapAnchor(
            id=uuid.uuid4(),
            source_frame=frame,
            musical_position=MusicalPosition(numerator=musical, denominator=1),
            origin="automatic",
            confidence=None,
            created_at=now,
            updated_at=now,
        )
        for frame, musical in (
            (1_000, 0),
            (49_000, 2),
            (97_000, 4),
            (145_000, 6),
            (193_000, 8),
        )
    ]
    tempo_map = TempoMap(
        id=uuid.uuid4(),
        project_id=project_id,
        project_sample_rate=48_000,
        source_duration_frames=200_000,
        hypothesis=PULSE_UNIT_QUARTER,
        alternatives=[],
        anchors=anchors,
        summary_bpm=120.0,
        created_at=now,
    )
    # Infer-meter selections can start after the first accepted pulses.
    meter_map = build_meter_map(
        [
            ManualMeterRegion(
                start=MusicalPosition(numerator=2, denominator=1),
                candidate=manual_candidate(4, 4, [1, 1, 1, 1]),
                origin="automatic",
            )
        ]
    )
    origin = automatic_bar_origin(meter_map)
    assert origin.first_numbered_bar_position.numerator == 2
    grid = derive_grid(tempo_map, meter_map, origin)
    assert grid.events
