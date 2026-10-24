"""Immutable automatic rhythm results and branch creation (M3.6, §8)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from basseparate.domain.meter import (
    ManualMeterRegion,
    build_meter_map,
    manual_candidate,
)
from basseparate.domain.rhythm import (
    ActivationArrayRef,
    ActivationArtifactManifest,
    ActivationFrameMapping,
    GridValidity,
    MusicalPosition,
    RhythmAnalysisRun,
    RhythmAnalysisStatus,
    RhythmDisplayMode,
)
from basseparate.domain.rhythm_decode import BEAT_THIS_DECODER_PROFILE
from basseparate.domain.rhythm_result import (
    RhythmResultRecord,
    RhythmResultStage,
    RhythmResultStatus,
)
from basseparate.rhythm.decoder import DecodeInput, decode_arrays
from basseparate.rhythm.results import (
    RhythmResultError,
    activate_branch,
    activate_result,
    create_branch_from_result,
    publish_decoded_result,
)
from basseparate.rhythm.tempo import build_automatic_tempo_map
from basseparate.storage.db import initialize_database
from basseparate.storage.repository import ProjectRepository, RhythmRepository

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)


def _mapping() -> ActivationFrameMapping:
    return ActivationFrameMapping(
        model_sample_rate=22_050, project_sample_rate=48_000, frame_hop=441
    )


def _decoded(artifact_id: uuid.UUID, *, extra_candidate: bool = False):
    beat = np.zeros(150, dtype=np.float32)
    downbeat = np.zeros(150, dtype=np.float32)
    beat[[10, 60, 110]] = [2.0, 1.5, 1.8]
    downbeat[[10, 110]] = [1.0, 0.8]
    if extra_candidate:
        beat[80:85] = -3.0
        beat[82] = -1.0
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


def _run(project_id: uuid.UUID, artifact_id: uuid.UUID) -> RhythmAnalysisRun:
    return RhythmAnalysisRun(
        id=uuid.uuid4(),
        project_id=project_id,
        input_asset_id=uuid.uuid4(),
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
        runtime_metrics={"inference_seconds": 0.2},
    )


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "basseparate.db"
    initialize_database(path)
    return path


def _setup(db_path: Path):
    projects = ProjectRepository(db_path)
    project = projects.create_project("Rhythm")
    repo = RhythmRepository(db_path)
    artifact_id = uuid.uuid4()
    run = _run(project.id, artifact_id)
    repo.create_run(run)
    repo.create_artifact(
        project.id,
        ActivationArtifactManifest(
            artifact_id=artifact_id,
            content_hash="cd" * 32,
            parent_run_id=run.id,
            source_asset_id=run.input_asset_id,
            source_hash=run.input_hash,
            model_frame_count=1,
            beat=ActivationArrayRef(relative_path="beat.npy", sha256="ab" * 32, element_count=1),
            downbeat=ActivationArrayRef(
                relative_path="downbeat.npy", sha256="ef" * 32, element_count=1
            ),
            frame_mapping=_mapping(),
            output_semantics="test",
        ),
    )
    return projects, project, repo, run


class TestPublishResult:
    def test_publishes_decoded_stage(self, db_path: Path) -> None:
        projects, project, repo, run = _setup(db_path)
        decoded = _decoded(run.activation_artifact_id)
        result = publish_decoded_result(run, decoded, repo)

        assert result.stage is RhythmResultStage.DECODED
        assert result.status is RhythmResultStatus.DECODED
        assert result.project_id == project.id
        assert result.run_id == run.id
        assert result.decoded_content_hash == decoded.content_hash
        assert len(result.accepted_pulses) == len(decoded.accepted_pulses)
        assert len(result.candidate_pulses) == len(decoded.candidate_pulses)
        assert all(pulse.parent_id == result.id for pulse in result.accepted_pulses)
        assert all(pulse.acceptance.value == "accepted" for pulse in result.accepted_pulses)
        assert repo.get_result(result.id) == result
        assert repo.list_results_for_project(project.id) == [result]
        assert result.tempo_map_id is None and result.meter_result_id is None

    def test_idempotent_for_same_run_and_content(self, db_path: Path) -> None:
        _projects, _project, repo, run = _setup(db_path)
        decoded = _decoded(run.activation_artifact_id)
        first = publish_decoded_result(run, decoded, repo)
        second = publish_decoded_result(run, decoded, repo)
        assert first == second
        assert len(repo.list_results_for_project(first.project_id)) == 1

    def test_conflicting_content_for_same_run_rejected(self, db_path: Path) -> None:
        _projects, _project, repo, run = _setup(db_path)
        decoded = _decoded(run.activation_artifact_id)
        publish_decoded_result(run, decoded, repo)
        changed = decoded.model_copy(update={"content_hash": "ff" * 32})
        with pytest.raises(RhythmResultError):
            publish_decoded_result(run, changed, repo)

    def test_incomplete_run_or_mismatched_artifact(self, db_path: Path) -> None:
        _projects, _project, repo, run = _setup(db_path)
        decoded = _decoded(run.activation_artifact_id)
        running = run.model_copy(update={"status": RhythmAnalysisStatus.RUNNING, "ended_at": None})
        with pytest.raises(RhythmResultError):
            publish_decoded_result(running, decoded, repo)
        other = _decoded(uuid.uuid4())
        with pytest.raises(RhythmResultError):
            publish_decoded_result(run, other, repo)


class TestBranches:
    def test_branch_copies_pulses_and_parent(self, db_path: Path) -> None:
        _projects, _project, repo, run = _setup(db_path)
        result = publish_decoded_result(
            run, _decoded(run.activation_artifact_id, extra_candidate=True), repo
        )
        branch = create_branch_from_result(result, repo)

        assert branch.parent_automatic_result_id == result.id
        assert branch.grid_validity is GridValidity.UNMAPPED
        assert branch.revision == 0
        assert len(branch.pulses) == len(result.accepted_pulses) + len(result.candidate_pulses)
        assert all(pulse.parent_id == branch.id for pulse in branch.pulses)
        assert repo.get_branch(branch.id) == branch

    def test_rerun_keeps_results_and_branches(self, db_path: Path) -> None:
        _projects, project, repo, first_run = _setup(db_path)
        first = publish_decoded_result(first_run, _decoded(first_run.activation_artifact_id), repo)
        branch = create_branch_from_result(first, repo)

        second_run = _run(project.id, uuid.uuid4())
        repo.create_run(second_run)
        assert second_run.activation_artifact_id is not None
        repo.create_artifact(
            project.id,
            ActivationArtifactManifest(
                artifact_id=second_run.activation_artifact_id,
                content_hash="cd" * 32,
                parent_run_id=second_run.id,
                source_asset_id=second_run.input_asset_id,
                source_hash=second_run.input_hash,
                model_frame_count=1,
                beat=ActivationArrayRef(
                    relative_path="beat.npy", sha256="ab" * 32, element_count=1
                ),
                downbeat=ActivationArrayRef(
                    relative_path="downbeat.npy", sha256="ef" * 32, element_count=1
                ),
                frame_mapping=_mapping(),
                output_semantics="test",
            ),
        )
        second = publish_decoded_result(
            second_run, _decoded(second_run.activation_artifact_id), repo
        )

        assert repo.get_result(first.id) == first
        assert repo.get_branch(branch.id) == branch
        assert len(repo.list_results_for_project(project.id)) == 2
        assert second.run_id == second_run.id

    def test_branch_carries_tempo_and_meter_maps(self, db_path: Path) -> None:
        _projects, project, repo, run = _setup(db_path)
        result = publish_decoded_result(run, _decoded(run.activation_artifact_id), repo)
        tempo = build_automatic_tempo_map(
            result.accepted_pulses,
            project_id=project.id,
            project_sample_rate=48_000,
            source_duration_frames=result.source_duration_frames,
        )
        meter = build_meter_map(
            [
                ManualMeterRegion(
                    start=MusicalPosition(numerator=0, denominator=1),
                    candidate=manual_candidate(4, 4, [1, 1, 1, 1]),
                )
            ]
        )
        branch = create_branch_from_result(result, repo, tempo_map=tempo, meter_map=meter)
        assert branch.grid_validity is GridValidity.VALID
        assert len(branch.tempo_anchors) == len(tempo.anchors)
        assert len(branch.meter_regions) == 1
        assert branch.meter_regions[0].end is None
        assert branch.tempo_anchors[0].branch_id == branch.id
        assert branch.meter_regions[0].branch_id == branch.id

        uncertain = build_meter_map(
            [
                ManualMeterRegion(
                    start=MusicalPosition(numerator=0, denominator=1),
                    candidate=manual_candidate(4, 4, [1, 1, 1, 1]),
                    uncertain=True,
                )
            ]
        )
        branch_uncertain = create_branch_from_result(
            result, repo, tempo_map=tempo, meter_map=uncertain
        )
        assert branch_uncertain.grid_validity is GridValidity.UNCERTAIN

    def test_activate_result_and_branch(self, db_path: Path) -> None:
        projects, project, repo, run = _setup(db_path)
        result = publish_decoded_result(run, _decoded(run.activation_artifact_id), repo)
        activated = activate_result(projects, result)
        assert activated.rhythm_state.active_automatic_result_id == result.id
        assert activated.rhythm_state.display_mode is RhythmDisplayMode.AUTOMATIC

        branch = create_branch_from_result(result, repo)
        edited = activate_branch(projects, repo, branch.id)
        assert edited.rhythm_state.active_branch_id == branch.id
        assert edited.rhythm_state.active_automatic_result_id == result.id
        assert edited.rhythm_state.display_mode is RhythmDisplayMode.EDITED


class TestResultRecord:
    def test_complete_result_requires_references(self) -> None:
        with pytest.raises(ValidationError):
            RhythmResultRecord(
                id=uuid.uuid4(),
                project_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                activation_artifact_id=uuid.uuid4(),
                decoded_content_hash="ab" * 32,
                decoder_profile=BEAT_THIS_DECODER_PROFILE,
                input_role="original_mix",
                stage=RhythmResultStage.COMPLETE,
                status=RhythmResultStatus.VALID,
                source_duration_frames=100,
                created_at=NOW,
                content_hash="cd" * 32,
            )
