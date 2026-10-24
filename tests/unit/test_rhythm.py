"""Rhythm domain models (M3.1, milestone3.md §3).

Covers the exact musical-position primitive, meter/grouping/tempo-unit
validation, analysis run and activation artifact invariants, and the
cross-record checks of an editable rhythm branch.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from fractions import Fraction

import pytest
from pydantic import ValidationError

from basseparate.domain.confidence import Confidence, ConfidenceKind, ReviewState
from basseparate.domain.project import ProjectRecord
from basseparate.domain.rhythm import (
    ZERO_MUSICAL_POSITION,
    ActivationArrayRef,
    ActivationArtifactManifest,
    ActivationFrameMapping,
    AnchorLockState,
    BarOriginState,
    CountInMode,
    CountInRepetition,
    CountInSettings,
    GridValidity,
    MeterHypothesis,
    MeterRegion,
    MeterTempoUnit,
    MetronomeSettings,
    MetronomeSubdivision,
    MusicalInterval,
    MusicalPosition,
    ProjectRhythmState,
    PulseAcceptance,
    PulseRole,
    RhythmAnalysisRun,
    RhythmAnalysisStatus,
    RhythmBranchRecord,
    RhythmDisplayMode,
    RhythmInputRole,
    RhythmOrigin,
    RhythmPulse,
    SnapMode,
    TempoAnchor,
    compare_musical_positions,
    tempo_unit_quarter_length,
)
from basseparate.domain.separation import DeviceType

HASH_A = "ab" * 32
HASH_B = "cd" * 32
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def pos(numerator: int, denominator: int = 1) -> MusicalPosition:
    return MusicalPosition(numerator=numerator, denominator=denominator)


def confidence(value: float = 0.9) -> Confidence:
    return Confidence(kind=ConfidenceKind.PROBABILITY, value=value)


def meter_region(
    branch_id: uuid.UUID,
    *,
    region_id: uuid.UUID | None = None,
    start: MusicalPosition | None = None,
    end: MusicalPosition | None = None,
    numerator: int = 4,
    denominator: int = 4,
    grouping: list[int] | None = None,
    unit: MeterTempoUnit = MeterTempoUnit.QUARTER,
) -> MeterRegion:
    return MeterRegion(
        id=region_id or uuid.uuid4(),
        branch_id=branch_id,
        start=start or ZERO_MUSICAL_POSITION,
        end=end,
        numerator=numerator,
        denominator=denominator,
        grouping=grouping or [1, 1, 1, 1],
        display_tempo_unit=unit,
        origin=RhythmOrigin.MANUAL,
    )


def tempo_anchor(
    branch_id: uuid.UUID,
    source_frame: int,
    musical_position: MusicalPosition,
    *,
    origin: RhythmOrigin = RhythmOrigin.MANUAL,
    confidence_value: Confidence | None = None,
) -> TempoAnchor:
    return TempoAnchor(
        id=uuid.uuid4(),
        branch_id=branch_id,
        source_frame=source_frame,
        musical_position=musical_position,
        lock_state=AnchorLockState.UNLOCKED,
        origin=origin,
        confidence=confidence_value,
        created_at=NOW,
        updated_at=NOW,
    )


def pulse(branch_id: uuid.UUID, source_frame: int = 0) -> RhythmPulse:
    return RhythmPulse(
        id=uuid.uuid4(),
        parent_id=branch_id,
        source_frame=source_frame,
        model_frame_index=1,
        role=PulseRole.BEAT,
        acceptance=PulseAcceptance.ACCEPTED,
        confidence=confidence(),
        origin=RhythmOrigin.AUTOMATIC,
    )


def branch(
    *,
    branch_id: uuid.UUID | None = None,
    parent_automatic_result_id: uuid.UUID | None = None,
    pulses: list[RhythmPulse] | None = None,
    anchors: list[TempoAnchor] | None = None,
    regions: list[MeterRegion] | None = None,
    validity: GridValidity = GridValidity.VALID,
    duration_frames: int = 48_000,
) -> RhythmBranchRecord:
    ident = branch_id or uuid.uuid4()
    return RhythmBranchRecord(
        id=ident,
        project_id=uuid.uuid4(),
        parent_automatic_result_id=parent_automatic_result_id,
        source_duration_frames=duration_frames,
        pulses=pulses if pulses is not None else [pulse(ident)],
        tempo_anchors=anchors
        if anchors is not None
        else [
            tempo_anchor(ident, 0, pos(0)),
            tempo_anchor(ident, 48_000, pos(2)),
        ],
        meter_regions=regions if regions is not None else [meter_region(ident)],
        bar_origin=BarOriginState(first_numbered_bar_position=pos(0)),
        grid_validity=validity,
        created_at=NOW,
        updated_at=NOW,
    )


# --- MusicalPosition -----------------------------------------------------


class TestMusicalPosition:
    def test_reduces_and_canonicalizes_zero(self) -> None:
        assert pos(2, 4).numerator == 1
        assert pos(2, 4).denominator == 2
        assert (pos(0, 5).numerator, pos(0, 5).denominator) == (0, 1)
        assert (pos(-2, 4).numerator, pos(-2, 4).denominator) == (-1, 2)

    def test_serializes_as_an_exact_fraction(self) -> None:
        payload = pos(3, 2).model_dump(mode="json")
        assert payload == {"numerator": 3, "denominator": 2}

    def test_rejects_invalid_components(self) -> None:
        with pytest.raises(ValidationError):
            MusicalPosition(numerator=1, denominator=0)
        with pytest.raises(ValidationError):
            MusicalPosition(numerator=1.5, denominator=1)  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            MusicalPosition(numerator=2**53, denominator=1)

    def test_exact_compare_and_arithmetic(self) -> None:
        assert compare_musical_positions(pos(1, 3), pos(1, 2)) < 0
        assert compare_musical_positions(pos(2, 4), pos(1, 2)) == 0
        assert pos(1, 2).add(pos(1, 3)) == pos(5, 6)
        assert pos(1, 2).difference(pos(1, 3)) == pos(1, 6)
        assert pos(-1, 4).is_negative

    def test_interval_requires_strict_order(self) -> None:
        interval = MusicalInterval(start=pos(0), end=pos(4))
        assert interval.end == pos(4)
        with pytest.raises(ValidationError):
            MusicalInterval(start=pos(4), end=pos(4))


# --- Meter and tempo units ----------------------------------------------


class TestMeterRegion:
    def test_primary_pulses_derive_from_grouping(self) -> None:
        branch_id = uuid.uuid4()
        assert meter_region(branch_id).primary_pulse_starts == [0, 1, 2, 3]
        compound = meter_region(
            branch_id,
            numerator=6,
            denominator=8,
            grouping=[3, 3],
            unit=MeterTempoUnit.DOTTED_QUARTER,
        )
        assert compound.primary_pulse_starts == [0, 3]
        assert compound.bar_length_quarters.numerator == 3

    def test_tempo_unit_must_match_grouping(self) -> None:
        branch_id = uuid.uuid4()
        with pytest.raises(ValidationError):
            meter_region(branch_id, unit=MeterTempoUnit.DOTTED_QUARTER)
        irregular = meter_region(
            branch_id,
            numerator=7,
            denominator=8,
            grouping=[2, 2, 3],
            unit=MeterTempoUnit.QUARTER,
        )
        assert irregular.primary_pulse_starts == [0, 2, 4]

    def test_grouping_and_bounds(self) -> None:
        branch_id = uuid.uuid4()
        with pytest.raises(ValidationError):
            meter_region(branch_id, grouping=[1, 1, 1])
        with pytest.raises(ValidationError):
            meter_region(branch_id, numerator=0)
        with pytest.raises(ValidationError):
            meter_region(branch_id, start=pos(-1))
        with pytest.raises(ValidationError):
            meter_region(branch_id, start=pos(2), end=pos(1))
        with pytest.raises(ValidationError):
            meter_region(branch_id, unit=None)  # type: ignore[arg-type]

    def test_hypothesis_validates_grouping(self) -> None:
        hypothesis = MeterHypothesis(
            numerator=6,
            denominator=8,
            grouping=[3, 3],
            confidence=confidence(0.6),
        )
        assert hypothesis.grouping == [3, 3]
        with pytest.raises(ValidationError):
            MeterHypothesis(
                numerator=6,
                denominator=8,
                grouping=[2, 2],
                confidence=confidence(),
            )

    def test_tempo_unit_lengths(self) -> None:
        assert tempo_unit_quarter_length(MeterTempoUnit.QUARTER) == 1
        assert tempo_unit_quarter_length(MeterTempoUnit.DOTTED_QUARTER).numerator == 3
        assert tempo_unit_quarter_length(MeterTempoUnit.DOTTED_QUARTER).denominator == 2


# --- Analysis run and activation artifact --------------------------------


def run(**overrides: object) -> RhythmAnalysisRun:
    data: dict[str, object] = {
        "id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "input_asset_id": uuid.uuid4(),
        "input_hash": HASH_A,
        "input_role": RhythmInputRole.ORIGINAL_MIX,
        "model_manifest_id": "beat_this_final0",
        "model_manifest_hash": HASH_B,
        "model_preset": "final0",
        "adapter_version": "adapter-1",
        "preprocessing_profile": "beat-input-v1",
        "preprocessing_version": 1,
        "requested_device": DeviceType.CPU,
        "status": RhythmAnalysisStatus.QUEUED,
    }
    data.update(overrides)
    return RhythmAnalysisRun.model_validate(data)  # type: ignore[arg-type]


class TestRhythmAnalysisRun:
    def test_queued_run_has_no_timing(self) -> None:
        queued = run()
        assert queued.started_at is None
        assert queued.activation_artifact_id is None

    def test_completed_run_requires_artifact_and_endpoints(self) -> None:
        with pytest.raises(ValidationError):
            run(status=RhythmAnalysisStatus.COMPLETED)
        completed = run(
            status=RhythmAnalysisStatus.COMPLETED,
            started_at=NOW,
            ended_at=NOW,
            activation_artifact_id=uuid.uuid4(),
        )
        assert completed.activation_artifact_id is not None

    def test_terminal_state_requires_end(self) -> None:
        with pytest.raises(ValidationError):
            run(status=RhythmAnalysisStatus.FAILED, started_at=NOW)

    def test_cuda_requires_device_uuid(self) -> None:
        with pytest.raises(ValidationError):
            run(
                status=RhythmAnalysisStatus.RUNNING,
                started_at=NOW,
                actual_device=DeviceType.CUDA,
            )
        busy = run(
            status=RhythmAnalysisStatus.RUNNING,
            started_at=NOW,
            requested_device=DeviceType.CUDA,
            actual_device=DeviceType.CUDA,
            device_uuid="GPU-0dab3af3-1111-2222-3333-444455556666",
        )
        assert busy.device_uuid is not None

    def test_queued_run_cannot_have_an_actual_device(self) -> None:
        with pytest.raises(ValidationError):
            run(actual_device=DeviceType.CPU)


class TestActivationArtifact:
    def _manifest(self, **overrides: object) -> ActivationArtifactManifest:
        data: dict[str, object] = {
            "artifact_id": uuid.uuid4(),
            "content_hash": HASH_A,
            "parent_run_id": uuid.uuid4(),
            "source_asset_id": uuid.uuid4(),
            "source_hash": HASH_B,
            "model_frame_count": 100,
            "beat": ActivationArrayRef(
                relative_path="rhythm/beats.npy", sha256=HASH_A, element_count=100
            ),
            "downbeat": ActivationArrayRef(
                relative_path="rhythm/downbeats.npy", sha256=HASH_B, element_count=100
            ),
            "frame_mapping": ActivationFrameMapping(
                model_sample_rate=22_050,
                project_sample_rate=48_000,
                frame_hop=512,
            ),
            "output_semantics": "sigmoid activation per model frame",
        }
        data.update(overrides)
        return ActivationArtifactManifest.model_validate(data)  # type: ignore[arg-type]

    def test_round_trip_and_frame_mapping(self) -> None:
        manifest = self._manifest()
        mapping = manifest.frame_mapping
        value = mapping.source_frame(2)
        assert value == Fraction(2 * 512 * 48_000, 22_050)

    def test_arrays_must_be_distinct_and_match_length(self) -> None:
        with pytest.raises(ValidationError):
            self._manifest(
                beat=ActivationArrayRef(
                    relative_path="rhythm/downbeats.npy", sha256=HASH_A, element_count=100
                )
            )
        with pytest.raises(ValidationError):
            self._manifest(
                beat=ActivationArrayRef(
                    relative_path="rhythm/beats.npy", sha256=HASH_A, element_count=99
                )
            )

    @pytest.mark.parametrize(
        "path",
        ["/abs/beats.npy", "../beats.npy", "rhythm\\beats.npy", "rhythm/beats.bin"],
    )
    def test_array_paths_are_safe(self, path: str) -> None:
        with pytest.raises(ValidationError):
            ActivationArrayRef(relative_path=path, sha256=HASH_A, element_count=1)


# --- Branch invariants ---------------------------------------------------


class TestRhythmBranch:
    def test_valid_branch_round_trip(self) -> None:
        original = branch()
        parsed = RhythmBranchRecord.model_validate_json(original.model_dump_json())
        assert parsed == original
        assert parsed.grid_validity is GridValidity.VALID
        assert parsed.pulses[0].review_state is ReviewState.UNREVIEWED

    def test_duplicate_ids_rejected(self) -> None:
        ident = uuid.uuid4()
        duplicated = pulse(ident)
        with pytest.raises(ValidationError):
            branch(branch_id=ident, pulses=[duplicated, duplicated])

    def test_anchor_branch_and_order(self) -> None:
        branch_id = uuid.uuid4()
        with pytest.raises(ValidationError):
            branch(
                branch_id=branch_id,
                anchors=[
                    tempo_anchor(uuid.uuid4(), 0, pos(0)),
                    tempo_anchor(branch_id, 100, pos(1)),
                ],
            )
        with pytest.raises(ValidationError):
            branch(
                branch_id=branch_id,
                anchors=[
                    tempo_anchor(branch_id, 100, pos(1)),
                    tempo_anchor(branch_id, 0, pos(0)),
                ],
            )
        with pytest.raises(ValidationError):
            branch(
                branch_id=branch_id,
                anchors=[
                    tempo_anchor(branch_id, 0, pos(0)),
                    tempo_anchor(branch_id, 0, pos(1)),
                ],
            )
        with pytest.raises(ValidationError):
            branch(
                branch_id=branch_id,
                anchors=[
                    tempo_anchor(branch_id, 0, pos(0)),
                    tempo_anchor(branch_id, 48_001, pos(1)),
                ],
            )

    def test_automatic_anchor_requires_confidence(self) -> None:
        branch_id = uuid.uuid4()
        with pytest.raises(ValidationError):
            branch(
                branch_id=branch_id,
                anchors=[tempo_anchor(branch_id, 0, pos(0), origin=RhythmOrigin.AUTOMATIC)],
            )
        with pytest.raises(ValidationError):
            tempo_anchor(branch_id, 0, pos(-1))

    def test_pulse_parent_and_anchor_links(self) -> None:
        branch_id = uuid.uuid4()
        stranger = pulse(uuid.uuid4())
        with pytest.raises(ValidationError):
            branch(branch_id=branch_id, pulses=[stranger])
        child = pulse(branch_id)
        child = child.model_copy(update={"tempo_anchor_id": uuid.uuid4()})
        with pytest.raises(ValidationError):
            branch(branch_id=branch_id, pulses=[child])

    def test_meter_regions_must_be_ordered_bar_boundaries(self) -> None:
        branch_id = uuid.uuid4()
        first = meter_region(branch_id)
        good = meter_region(branch_id, start=pos(4), region_id=uuid.uuid4())
        record = branch(branch_id=branch_id, regions=[first, good])
        assert len(record.meter_regions) == 2
        with pytest.raises(ValidationError):
            branch(
                branch_id=branch_id,
                regions=[
                    meter_region(branch_id),
                    meter_region(branch_id, start=pos(3)),
                ],
            )
        with pytest.raises(ValidationError):
            branch(
                branch_id=branch_id,
                regions=[
                    meter_region(branch_id, end=pos(4)),
                    meter_region(branch_id, start=pos(8)),
                ],
            )

    def test_valid_grid_requires_anchor_and_meter(self) -> None:
        with pytest.raises(ValidationError):
            branch(anchors=[])
        with pytest.raises(ValidationError):
            branch(regions=[])
        empty = branch(pulses=[], anchors=[], regions=[], validity=GridValidity.UNMAPPED)
        assert empty.grid_validity is GridValidity.UNMAPPED

    def test_unmetered_grid_allows_anchors_without_meter(self) -> None:
        record = branch(regions=[], validity=GridValidity.UNMETERED)
        assert record.tempo_anchors


# --- Project state -------------------------------------------------------


class TestProjectRhythmState:
    def test_defaults(self) -> None:
        state = ProjectRhythmState()
        assert state.display_mode is RhythmDisplayMode.AUTOMATIC
        assert state.snap_mode is SnapMode.BEAT
        assert state.metronome == MetronomeSettings()
        assert state.metronome.subdivision is MetronomeSubdivision.PRIMARY
        assert state.count_in == CountInSettings()
        assert state.count_in.mode is CountInMode.OFF
        assert state.count_in.repetition is CountInRepetition.ONCE

    def test_edited_mode_requires_branch(self) -> None:
        with pytest.raises(ValidationError):
            ProjectRhythmState(display_mode=RhythmDisplayMode.EDITED)
        state = ProjectRhythmState(
            display_mode=RhythmDisplayMode.EDITED,
            active_branch_id=uuid.uuid4(),
        )
        assert state.active_branch_id is not None

    def test_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ProjectRhythmState(lane_height=0.1)
        with pytest.raises(ValidationError):
            ProjectRhythmState(metronome=MetronomeSettings(volume=3.0))

    def test_project_record_default_and_round_trip(self) -> None:
        project = ProjectRecord(
            id=uuid.uuid4(),
            name="Song",
            created_at=NOW,
            updated_at=NOW,
        )
        assert project.rhythm_state == ProjectRhythmState()
        project = project.model_copy(
            update={"rhythm_state": ProjectRhythmState(lane_visible=False, snap_mode=SnapMode.BAR)}
        )
        parsed = ProjectRecord.model_validate_json(project.model_dump_json())
        assert parsed.rhythm_state.lane_visible is False
        assert parsed.rhythm_state.snap_mode is SnapMode.BAR
