"""Portable rhythm persistence (M3.18, spec §20.8-§20.11).

A portable archive carries the active rhythm grid, automatic results,
branches, and rhythm undo/redo rows. Opening it restores that state (and
the active selection) into a new working copy.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from basseparate.domain.rhythm import (
    ActivationArrayRef,
    ActivationArtifactManifest,
    ActivationFrameMapping,
    RhythmAnalysisRun,
    RhythmAnalysisStatus,
    RhythmBranchRecord,
)
from basseparate.domain.rhythm_decode import BEAT_THIS_DECODER_PROFILE
from basseparate.domain.rhythm_result import RhythmResultStage, RhythmResultStatus
from basseparate.portable.open import open_portable_archive
from basseparate.portable.save import perform_portable_save
from basseparate.rhythm.decoder import DecodeInput, decode_arrays
from basseparate.rhythm.results import create_branch_from_result, publish_decoded_result
from basseparate.storage import PortableArtifactRepository, ProjectRepository
from basseparate.storage.db import initialize_database
from basseparate.storage.paths import StoragePaths, resolve_storage_paths
from basseparate.storage.repository import RhythmRepository
from tests.unit.portable_seed import create_seed_files, seed_two_projects

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)


def _mapping() -> ActivationFrameMapping:
    return ActivationFrameMapping(
        model_sample_rate=22_050, project_sample_rate=48_000, frame_hop=441
    )


def _decoded(artifact_id: uuid.UUID):
    beat = np.zeros(150, dtype=np.float32)
    downbeat = np.zeros(150, dtype=np.float32)
    beat[[10, 60, 110]] = [2.0, 1.5, 1.8]
    downbeat[[10, 110]] = [1.0, 0.8]
    return decode_arrays(
        DecodeInput(
            artifact_id=artifact_id,
            content_hash="cd" * 32,
            frame_mapping=_mapping(),
            beat=beat,
            downbeat=downbeat,
        ),
        project_sample_rate=48_000,
        source_duration_frames=1_411_200,
    )


def _rhythm_state(branch: RhythmBranchRecord):
    from basseparate.domain.rhythm import ProjectRhythmState

    return ProjectRhythmState(
        active_branch_id=branch.id,
        active_result_id=branch.parent_automatic_result_id,
    )


@pytest.fixture()
def archive(tmp_path: Path):
    root = tmp_path / "source"
    seed = seed_two_projects(root)
    create_seed_files(root, seed)
    paths = resolve_storage_paths(root)
    db = root / "data" / "basseparate.db"
    projects = ProjectRepository(db)
    rhythm = RhythmRepository(db)
    project = projects.get_project(uuid.UUID(seed.project_a))
    assert project is not None

    artifact_id = uuid.uuid4()
    run = RhythmAnalysisRun(
        id=uuid.uuid4(),
        project_id=project.id,
        input_asset_id=uuid.UUID(seed.can_a),
        input_hash="ab" * 32,
        input_role="original_mix",
        model_manifest_id="beat_this_final0",
        model_manifest_hash="ef" * 32,
        model_preset="final0",
        adapter_version="beat-this-adapter-v1",
        preprocessing_profile="beat-this-logmel-22050-441-v1",
        preprocessing_version=1,
        requested_device="cpu",
        actual_device="cpu",
        started_at=NOW,
        ended_at=NOW,
        status=RhythmAnalysisStatus.COMPLETED,
        activation_artifact_id=artifact_id,
    )
    rhythm.create_run(run)
    artifact_dir = paths.data / "rhythm" / "activations" / str(artifact_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "beat.npy").write_bytes(b"beat-array")
    (artifact_dir / "downbeat.npy").write_bytes(b"downbeat-array")
    rhythm.create_artifact(
        project.id,
        ActivationArtifactManifest(
            artifact_id=artifact_id,
            content_hash="cd" * 32,
            parent_run_id=run.id,
            source_asset_id=run.input_asset_id,
            source_hash=run.input_hash,
            model_frame_count=150,
            beat=ActivationArrayRef(
                relative_path="beat.npy", sha256="ab" * 32, element_count=150
            ),
            downbeat=ActivationArrayRef(
                relative_path="downbeat.npy", sha256="ef" * 32, element_count=150
            ),
            frame_mapping=_mapping(),
            output_semantics="test",
        ),
    )
    result = publish_decoded_result(run, _decoded(artifact_id), rhythm)
    branch = create_branch_from_result(result, rhythm)
    projects.set_rhythm_state(project.id, _rhythm_state(branch))
    project = projects.get_project(project.id)
    assert project is not None

    artifact, _manifest = perform_portable_save(
        db, paths, project, PortableArtifactRepository(db)
    )
    return {
        "archive": paths.resolve_asset_path(artifact.relative_path),
        "seed": seed,
        "project": project,
        "branch": branch,
        "result": result,
        "run": run,
    }


def _new_store(tmp_path: Path) -> tuple[StoragePaths, ProjectRepository, Path]:
    root = tmp_path / "target"
    paths = resolve_storage_paths(root)
    paths.data.mkdir(parents=True, exist_ok=True)
    db = paths.database_path
    initialize_database(db)
    return paths, ProjectRepository(db), db


def _open(built, paths: StoragePaths, repo: ProjectRepository):
    return open_portable_archive(
        built["archive"],
        paths=paths,
        repository=repo,
        max_uncompressed_bytes=2_000_000_000,
        max_member_count=100_000,
        source_filename="song.basseparate",
    )


def test_rhythm_state_and_rows_survive_reopen(archive, tmp_path: Path) -> None:
    paths, repo, db = _new_store(tmp_path)
    opened = _open(archive, paths, repo)

    assert opened.rhythm_state.active_branch_id is not None
    opened_branch_id = opened.rhythm_state.active_branch_id
    assert opened_branch_id != archive["branch"].id

    conn = sqlite3.connect(db)
    try:
        conn.row_factory = sqlite3.Row
        runs = conn.execute("SELECT * FROM rhythm_analysis_runs").fetchall()
        artifacts = conn.execute("SELECT * FROM rhythm_activation_artifacts").fetchall()
        results = conn.execute("SELECT * FROM rhythm_results").fetchall()
        branches = conn.execute("SELECT * FROM rhythm_branches").fetchall()
        project_row = conn.execute(
            "SELECT rhythm_state, rhythm_history_seq FROM projects"
        ).fetchone()
    finally:
        conn.close()

    assert len(runs) == 1 and len(artifacts) == 1
    assert len(results) == 1 and len(branches) == 1
    assert runs[0]["project_id"] == str(opened.id)
    assert artifacts[0]["run_id"] == runs[0]["id"]
    assert results[0]["run_id"] == runs[0]["id"]
    assert results[0]["activation_artifact_id"] == artifacts[0]["id"]
    assert branches[0]["id"] == str(opened_branch_id)
    assert branches[0]["parent_automatic_result_id"] == results[0]["id"]
    assert project_row["rhythm_state"] == opened.rhythm_state.model_dump_json()

    # The reopened branch keeps the corrected grid data and its parent.
    restored = RhythmRepository(db).get_branch(uuid.UUID(branches[0]["id"]))
    assert restored is not None
    assert restored.project_id == opened.id
    assert restored.parent_automatic_result_id == uuid.UUID(results[0]["id"])
    assert len(restored.pulses) == len(archive["branch"].pulses)
    assert all(pulse.parent_id == restored.id for pulse in restored.pulses)
    assert restored.grid_validity == archive["branch"].grid_validity

    restored_dir = paths.data / "rhythm" / "activations" / artifacts[0]["id"]
    assert (restored_dir / "beat.npy").read_bytes() == b"beat-array"
    assert (restored_dir / "downbeat.npy").read_bytes() == b"downbeat-array"

    result = RhythmRepository(db).get_result(uuid.UUID(results[0]["id"]))
    assert result is not None
    assert result.project_id == opened.id
    assert result.run_id == uuid.UUID(runs[0]["id"])
    assert result.activation_artifact_id == uuid.UUID(artifacts[0]["id"])
    assert all(
        pulse.parent_id == result.id
        for pulse in (*result.accepted_pulses, *result.candidate_pulses)
    )
    assert result.stage is RhythmResultStage.DECODED
    assert result.status is RhythmResultStatus.DECODED
    assert result.decoder_profile.profile_id == BEAT_THIS_DECODER_PROFILE.profile_id


def _strip_activation_members(source: Path, destination: Path) -> None:
    import json
    import zipfile

    with zipfile.ZipFile(source) as archive:
        members = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    manifest = json.loads(members["manifest.json"])
    keep = [
        entry
        for entry in manifest["members"]
        if not entry["name"].startswith("caches/rhythm/activations/")
    ]
    manifest["members"] = keep
    members["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in members.items():
            if name.startswith("caches/rhythm/activations/"):
                continue
            output.writestr(name, data)


def test_missing_optional_activations_still_reopen(archive, tmp_path: Path) -> None:
    stripped = tmp_path / "stripped.basseparate"
    _strip_activation_members(archive["archive"], stripped)
    paths, repo, db = _new_store(tmp_path)
    opened = open_portable_archive(
        stripped,
        paths=paths,
        repository=repo,
        max_uncompressed_bytes=2_000_000_000,
        max_member_count=100_000,
        source_filename="song.basseparate",
    )
    assert opened.rhythm_state.active_branch_id is not None
    conn = sqlite3.connect(db)
    try:
        branch = conn.execute("SELECT id, record_json FROM rhythm_branches").fetchone()
        artifact = conn.execute("SELECT id FROM rhythm_activation_artifacts").fetchone()
    finally:
        conn.close()
    assert branch is not None and artifact is not None
    # The corrected grid remains; only raw re-decoding material is absent.
    assert not (paths.data / "rhythm" / "activations" / artifact[0] / "beat.npy").exists()
    restored = RhythmRepository(db).get_branch(uuid.UUID(branch[0]))
    assert restored is not None and restored.pulses
