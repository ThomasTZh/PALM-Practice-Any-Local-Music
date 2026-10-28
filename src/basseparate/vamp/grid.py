"""Convert validated Vamp features into the app's rhythm-branch model."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.project import ProjectRecord
from basseparate.domain.rhythm import (
    ZERO_MUSICAL_POSITION,
    BarOriginState,
    GridValidity,
    MeterRegion,
    MeterTempoUnit,
    MusicalPosition,
    PulseAcceptance,
    PulseRole,
    RhythmBranchRecord,
    RhythmOrigin,
    RhythmPulse,
    TempoAnchor,
)
from basseparate.vamp.features import SUPPORTED_BPB, VampAnalysis


class VampGridError(ValueError):
    """Vamp features cannot produce a usable grid."""


def _auto_confidence() -> Confidence:
    return Confidence(
        value=0.9,
        kind=ConfidenceKind.HEURISTIC,
        method="vamp-qm-barbeattracker",
        calibrated=False,
    )


def build_branch_from_vamp(
    project: ProjectRecord,
    analysis: VampAnalysis,
    *,
    now: datetime | None = None,
) -> RhythmBranchRecord:
    """Build a valid branch from QM beats and bars.

    The first bar (or the first beat when no bars are present) is the
    musical origin. Beats before it are dropped. Every retained beat gets a
    tempo anchor; bar starts are downbeat pulses.
    """
    timestamp = now or datetime.now(UTC)
    if project.duration_frames is None or project.sample_rate is None:
        raise VampGridError("a ready project with source timing is required")
    if analysis.bpb not in SUPPORTED_BPB:
        raise VampGridError(
            "bpb must be one of " + ", ".join(str(value) for value in sorted(SUPPORTED_BPB))
        )
    if analysis.sample_rate != project.sample_rate:
        raise VampGridError("Vamp sample rate does not match the project sample rate")
    beats = analysis.beats
    if not beats:
        raise VampGridError("Vamp returned no beats")
    bars = analysis.bars
    origin_seconds = bars[0].time_seconds if bars else beats[0].time_seconds
    origin_frame = round(origin_seconds * project.sample_rate)
    origin_frame = max(0, min(project.duration_frames, origin_frame))
    bar_frames = {
        min(project.duration_frames, round(bar.time_seconds * project.sample_rate)): bar
        for bar in bars
    }
    event_frames = {
        min(project.duration_frames, round(beat.time_seconds * project.sample_rate))
        for beat in beats
        if round(beat.time_seconds * project.sample_rate) >= origin_frame
    }
    event_frames.update(bar_frames)
    frames = sorted(frame for frame in event_frames if 0 <= frame <= project.duration_frames)
    if not frames:
        raise VampGridError("Vamp returned no beats inside the project")
    if bars and origin_frame not in frames:
        frames.insert(0, origin_frame)

    branch_id = uuid4()
    confidence = _auto_confidence()
    pulses: list[RhythmPulse] = []
    anchors: list[TempoAnchor] = []
    for index, frame in enumerate(frames):
        anchor_id = uuid4()
        is_downbeat = frame in bar_frames or (not bars and index == 0)
        pulse = RhythmPulse(
            id=uuid4(),
            parent_id=branch_id,
            source_frame=frame,
            role=PulseRole.DOWNBEAT if is_downbeat else PulseRole.BEAT,
            acceptance=PulseAcceptance.ACCEPTED,
            confidence=confidence,
            origin=RhythmOrigin.AUTOMATIC,
            tempo_anchor_id=anchor_id,
        )
        anchor = TempoAnchor(
            id=anchor_id,
            branch_id=branch_id,
            source_frame=frame,
            musical_position=MusicalPosition(numerator=index, denominator=1),
            origin=RhythmOrigin.AUTOMATIC,
            pulse_id=pulse.id,
            confidence=confidence,
            created_at=timestamp,
            updated_at=timestamp,
        )
        pulses.append(pulse)
        anchors.append(anchor)

    region = MeterRegion(
        id=uuid4(),
        branch_id=branch_id,
        start=ZERO_MUSICAL_POSITION,
        numerator=analysis.bpb,
        denominator=4,
        grouping=[1] * analysis.bpb,
        display_tempo_unit=MeterTempoUnit.QUARTER,
        confidence=confidence,
        origin=RhythmOrigin.AUTOMATIC,
    )
    return RhythmBranchRecord(
        id=branch_id,
        project_id=project.id,
        parent_automatic_result_id=None,
        source_duration_frames=project.duration_frames,
        pulses=pulses,
        tempo_anchors=anchors,
        meter_regions=[region],
        bar_origin=BarOriginState(first_numbered_bar_position=ZERO_MUSICAL_POSITION),
        grid_validity=GridValidity.VALID,
        review_summary={
            "accepted": len(pulses),
            "beats": sum(pulse.role is PulseRole.BEAT for pulse in pulses),
            "downbeats": sum(pulse.role is PulseRole.DOWNBEAT for pulse in pulses),
        },
        created_at=timestamp,
        updated_at=timestamp,
    )
