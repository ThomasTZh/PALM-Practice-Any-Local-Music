"""Publish immutable automatic rhythm results and editable branches (M3.6 §8).

The automatic result is the auditable product of one completed activation
run plus one decoder profile. It is immutable. Branches are copies that
carry the parent result ID; corrections live in branches, and reruns
create new results without touching older results or branches.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime

from basseparate.domain.common import Uuid
from basseparate.domain.meter import MeterMap
from basseparate.domain.project import ProjectRecord
from basseparate.domain.rhythm import (
    ZERO_MUSICAL_POSITION,
    BarOriginState,
    GridValidity,
    MeterRegion,
    ProjectRhythmState,
    PulseAcceptance,
    RhythmAnalysisRun,
    RhythmAnalysisStatus,
    RhythmBranchRecord,
    RhythmDisplayMode,
    RhythmOrigin,
    RhythmPulse,
    TempoAnchor,
)
from basseparate.domain.rhythm_decode import DecodedPulse, DecodedRhythmResult
from basseparate.domain.rhythm_result import (
    RhythmResultRecord,
    RhythmResultStage,
    RhythmResultStatus,
    result_content_hash,
)
from basseparate.domain.tempo import TempoMap
from basseparate.storage.repository import ProjectRepository, RhythmRepository


class RhythmResultError(Exception):
    """The automatic result cannot be published or used."""


def _now() -> datetime:
    return datetime.now(UTC)


def _pulse_from_decoded(
    pulse: DecodedPulse, *, parent_id: Uuid, acceptance: PulseAcceptance
) -> RhythmPulse:
    return RhythmPulse(
        id=pulse.id,
        parent_id=parent_id,
        source_frame=pulse.source_frame,
        model_frame_index=int(math.floor(pulse.model_frame + 0.5)),
        role=pulse.role,
        acceptance=acceptance,
        confidence=pulse.confidence,
        origin=RhythmOrigin.AUTOMATIC,
        tempo_anchor_id=None,
    )


def _copy_pulse(pulse: RhythmPulse, *, parent_id: Uuid) -> RhythmPulse:
    return pulse.model_copy(update={"parent_id": parent_id, "tempo_anchor_id": None})


def publish_decoded_result(
    run: RhythmAnalysisRun,
    decoded: DecodedRhythmResult,
    repository: RhythmRepository,
    *,
    warnings: list[str] | None = None,
    result_id: Uuid | None = None,
    created_at: datetime | None = None,
) -> RhythmResultRecord:
    """Publish the decoded stage as an immutable automatic result (§8.1-§8.2).

    Idempotent for the same (run, stage, decoded content): repeating the
    call returns the stored result. A different decoded content for the
    same run/stage is rejected because the result is immutable.
    """
    if run.status is not RhythmAnalysisStatus.COMPLETED:
        raise RhythmResultError("only a completed rhythm run can publish a result")
    if (
        run.activation_artifact_id is None
        or run.activation_artifact_id != decoded.activation_artifact_id
    ):
        raise RhythmResultError("the decoded activation does not belong to the run")
    existing = repository.get_result_for_run_stage(run.id, RhythmResultStage.DECODED)
    if existing is not None:
        if existing.decoded_content_hash == decoded.content_hash:
            return existing
        raise RhythmResultError("a different decoded result already exists for this run")

    ident = result_id or uuid.uuid4()
    accepted = [
        _pulse_from_decoded(pulse, parent_id=ident, acceptance=PulseAcceptance.ACCEPTED)
        for pulse in decoded.accepted_pulses
    ]
    candidates = [
        _pulse_from_decoded(pulse, parent_id=ident, acceptance=PulseAcceptance.CANDIDATE)
        for pulse in decoded.candidate_pulses
    ]
    stage = RhythmResultStage.DECODED
    status = RhythmResultStatus.DECODED
    record = RhythmResultRecord(
        id=ident,
        project_id=run.project_id,
        run_id=run.id,
        activation_artifact_id=decoded.activation_artifact_id,
        decoded_content_hash=decoded.content_hash,
        decoder_profile=decoded.decoder_profile,
        input_role=run.input_role,
        stage=stage,
        status=status,
        accepted_pulses=accepted,
        candidate_pulses=candidates,
        warnings=warnings or [],
        created_at=created_at or _now(),
        source_duration_frames=decoded.source_duration_frames,
        content_hash=result_content_hash(
            run_id=run.id,
            activation_artifact_id=decoded.activation_artifact_id,
            decoded_content_hash=decoded.content_hash,
            decoder_profile=decoded.decoder_profile,
            accepted_pulses=accepted,
            candidate_pulses=candidates,
            stage=stage,
            status=status,
            source_duration_frames=decoded.source_duration_frames,
        ),
    )
    return repository.create_result(record)


def _tempo_anchors(tempo_map: TempoMap, branch_id: Uuid) -> list[TempoAnchor]:
    return [
        TempoAnchor(
            id=anchor.id,
            branch_id=branch_id,
            source_frame=anchor.source_frame,
            musical_position=anchor.musical_position,
            lock_state=anchor.lock_state,
            origin=anchor.origin,
            pulse_id=anchor.pulse_id,
            confidence=anchor.confidence,
            created_at=anchor.created_at,
            updated_at=anchor.updated_at,
        )
        for anchor in tempo_map.anchors
    ]


def _meter_regions(meter_map: MeterMap, branch_id: Uuid) -> list[MeterRegion]:
    regions: list[MeterRegion] = []
    for index, region in enumerate(meter_map.regions):
        end = meter_map.regions[index + 1].start if index + 1 < len(meter_map.regions) else None
        regions.append(
            MeterRegion(
                id=uuid.uuid4(),
                branch_id=branch_id,
                start=region.start,
                end=end,
                numerator=region.candidate.numerator,
                denominator=region.candidate.denominator,
                grouping=region.candidate.grouping,
                display_tempo_unit=region.candidate.display_tempo_unit,
                confidence=region.confidence,
                alternatives=region.alternatives,
                grid_validity=(GridValidity.UNCERTAIN if region.uncertain else GridValidity.VALID),
                origin=region.origin,
            )
        )
    return regions


def create_branch_from_result(
    result: RhythmResultRecord,
    repository: RhythmRepository,
    *,
    branch_id: Uuid | None = None,
    created_at: datetime | None = None,
    tempo_map: TempoMap | None = None,
    meter_map: MeterMap | None = None,
    bar_origin: BarOriginState | None = None,
) -> RhythmBranchRecord:
    """Create an editable branch that references an automatic result (§8.3).

    Accepted and candidate pulses are copied with this branch as parent.
    Optional tempo-map/meter-map artifacts are converted into branch
    anchors/regions; without both, the branch starts explicitly unmapped.
    """
    ident = branch_id or uuid.uuid4()
    now = created_at or _now()
    pulses = [_copy_pulse(pulse, parent_id=ident) for pulse in result.accepted_pulses] + [
        _copy_pulse(pulse, parent_id=ident) for pulse in result.candidate_pulses
    ]
    anchors = _tempo_anchors(tempo_map, ident) if tempo_map is not None else []
    regions = _meter_regions(meter_map, ident) if meter_map is not None else []
    if anchors and regions:
        validity = (
            GridValidity.UNCERTAIN
            if any(region.grid_validity is GridValidity.UNCERTAIN for region in regions)
            else GridValidity.VALID
        )
    else:
        validity = GridValidity.UNMAPPED
    branch = RhythmBranchRecord(
        id=ident,
        project_id=result.project_id,
        parent_automatic_result_id=result.id,
        revision=0,
        source_duration_frames=result.source_duration_frames,
        pulses=pulses,
        tempo_anchors=anchors,
        meter_regions=regions,
        bar_origin=(
            bar_origin
            if bar_origin is not None
            else BarOriginState(first_numbered_bar_position=ZERO_MUSICAL_POSITION)
        ),
        grid_validity=validity,
        created_at=now,
        updated_at=now,
    )
    return repository.create_branch(branch)


def activate_result(projects: ProjectRepository, result: RhythmResultRecord) -> ProjectRecord:
    """Select an automatic result for display/practice (Auto mode)."""
    project = projects.get_project(result.project_id)
    if project is None:
        raise RhythmResultError("the result's project does not exist")
    state = ProjectRhythmState.model_validate(
        {
            **project.rhythm_state.model_dump(),
            "active_automatic_result_id": result.id,
            "display_mode": RhythmDisplayMode.AUTOMATIC.value,
        }
    )
    return projects.set_rhythm_state(project.id, state)


def activate_branch(
    projects: ProjectRepository, repository: RhythmRepository, branch_id: Uuid
) -> ProjectRecord:
    """Select an edited branch for display/practice (Edited mode)."""
    branch = repository.get_branch(branch_id)
    if branch is None:
        raise RhythmResultError("the rhythm branch does not exist")
    project = projects.get_project(branch.project_id)
    if project is None:
        raise RhythmResultError("the branch's project does not exist")
    state = ProjectRhythmState.model_validate(
        {
            **project.rhythm_state.model_dump(),
            "active_branch_id": branch.id,
            "active_automatic_result_id": branch.parent_automatic_result_id,
            "display_mode": RhythmDisplayMode.EDITED.value,
        }
    )
    return projects.set_rhythm_state(project.id, state)
