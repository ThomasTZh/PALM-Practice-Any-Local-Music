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
