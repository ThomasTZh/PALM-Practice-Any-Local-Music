"""Tempo-map mapping, pulse units, and reinterpretation (M3.7, §9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from fractions import Fraction

import pytest

from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.rhythm import (
    AnchorLockState,
    MeterTempoUnit,
    MusicalPosition,
    PulseAcceptance,
    PulseRole,
    RhythmOrigin,
    RhythmPulse,
)
from basseparate.domain.tempo import (
    PULSE_UNIT_DOTTED_QUARTER,
    PULSE_UNIT_EIGHTH,
    PULSE_UNIT_HALF,
    PULSE_UNIT_QUARTER,
    TempoMapRangeError,
    denominator_pulse_hypothesis,
    grouping_pulse_hypothesis,
)
from basseparate.rhythm.tempo import (
    TempoMapBuildError,
    TempoMapConflictError,
    bpm_for_display_unit,
    build_automatic_tempo_map,
    build_manual_tempo_map,
    map_round_trip_error_frames,
    reinterpret_tempo_map,
)


def pos(numerator: int, denominator: int = 1) -> MusicalPosition:
    return MusicalPosition(numerator=numerator, denominator=denominator)


NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
RATE = 48_000
PROJECT_ID = uuid.uuid4()


def _pulse(source: int, index: int = 0) -> RhythmPulse:
    return RhythmPulse(
        id=uuid.uuid4(),
        parent_id=uuid.uuid4(),
        source_frame=source,
        model_frame_index=index,
        role=PulseRole.BEAT,
        acceptance=PulseAcceptance.ACCEPTED,
        confidence=Confidence(kind=ConfidenceKind.HEURISTIC, value=0.9),
        origin=RhythmOrigin.AUTOMATIC,
    )


def _pulses(count: int = 11, interval: int = 24_000) -> list[RhythmPulse]:
    return [_pulse(index * interval, index) for index in range(count)]


def _map(pulses: list[RhythmPulse] | None = None, hypothesis=PULSE_UNIT_QUARTER):
    return build_automatic_tempo_map(
        pulses or _pulses(),
        project_id=PROJECT_ID,
        project_sample_rate=RATE,
        source_duration_frames=300_000,
        hypothesis=hypothesis,
        created_at=NOW,
    )


class TestMapping:
    def test_one_anchor_per_pulse_and_constant_bpm(self) -> None:
        map_ = _map()
        assert len(map_.anchors) == 11
        assert [anchor.source_frame for anchor in map_.anchors] == [
            index * 24_000 for index in range(11)
        ]
        assert [anchor.musical_position for anchor in map_.anchors] == [
            MusicalPosition(numerator=index, denominator=1) for index in range(11)
        ]
        assert len(map_.segments) == 10
        assert all(segment.quarter_note_bpm == pytest.approx(120.0) for segment in map_.segments)
        assert map_.summary_bpm == pytest.approx(120.0)
        assert map_.summary_unit is MeterTempoUnit.QUARTER
        assert map_.hypothesis.unit.value == "quarter"
        assert map_.alternatives
        assert all(anchor.pulse_id is not None for anchor in map_.anchors)

    def test_exact_source_to_musical_and_back(self) -> None:
        map_ = _map()
        assert map_.map_source_to_musical(12_000) == pos(1, 2)
        assert map_.map_source_to_musical(36_000) == pos(3, 2)
        assert map_.map_musical_to_source(pos(1, 2)) == 12_000
        assert map_.map_musical_to_source(pos(3, 2)) == 36_000
        assert map_.local_bpm_at_source(24_000) == pytest.approx(120.0)
        assert map_round_trip_error_frames(map_) <= 1

    def test_range_errors(self) -> None:
        map_ = _map()
        with pytest.raises(TempoMapRangeError):
            map_.map_source_to_musical(-1)
        with pytest.raises(TempoMapRangeError):
            map_.map_source_to_musical(240_001)
        with pytest.raises(TempoMapRangeError):
            map_.map_musical_to_source(pos(11, 1))
        # Edge extension is disabled by default: no silent extrapolation.
        assert map_.max_edge_extension_quarters == 0.0

    def test_half_time_and_eighth_pulse_units(self) -> None:
        half = _map(hypothesis=PULSE_UNIT_HALF)
        assert half.anchors[1].musical_position == pos(2, 1)
        assert half.segments[0].quarter_note_bpm == pytest.approx(240.0)
        eighth = _map(hypothesis=PULSE_UNIT_EIGHTH)
        assert eighth.anchors[1].musical_position == pos(1, 2)
        assert eighth.segments[0].quarter_note_bpm == pytest.approx(60.0)
        dotted = _map(hypothesis=PULSE_UNIT_DOTTED_QUARTER)
        assert dotted.anchors[1].musical_position == pos(3, 2)
        assert dotted.segments[0].quarter_note_bpm == pytest.approx(180.0)

    def test_grouping_and_denominator_units(self) -> None:
        grouping = grouping_pulse_hypothesis([2, 2, 3], 8)
        assert [d.as_quarter_notes() for d in grouping.distances] == [
            Fraction(1),
            Fraction(1),
            Fraction(3, 2),
        ]
        map_ = _map(pulses=_pulses(4, 10_000), hypothesis=grouping)
        assert [anchor.musical_position for anchor in map_.anchors] == [
            pos(0, 1),
            pos(1, 1),
            pos(2, 1),
            pos(7, 2),
        ]
        eighth = denominator_pulse_hypothesis(8)
        assert eighth.distances[0] == pos(1, 2)

    def test_manual_sparse_map(self) -> None:
        map_ = build_manual_tempo_map(
            [(0, pos(0, 1)), (48_000, pos(4, 1))],
            project_id=PROJECT_ID,
            project_sample_rate=RATE,
            source_duration_frames=100_000,
            created_at=NOW,
        )
        assert len(map_.anchors) == 2
        assert map_.anchors[0].origin is RhythmOrigin.MANUAL
        assert map_.segments[0].quarter_note_bpm == pytest.approx(240.0)
        assert map_.map_source_to_musical(24_000) == pos(2, 1)
        assert map_.map_musical_to_source(pos(2, 1)) == 24_000

    def test_invalid_maps_rejected(self) -> None:
        with pytest.raises(TempoMapBuildError):
            _map(pulses=[_pulse(0)])
        with pytest.raises(TempoMapBuildError):
            _map(pulses=[_pulse(0), _pulse(0)])
        with pytest.raises(TempoMapBuildError):
            build_manual_tempo_map(
                [(0, pos(0, 1)), (0, pos(1, 1))],
                project_id=PROJECT_ID,
                project_sample_rate=RATE,
                source_duration_frames=10,
            )
        with pytest.raises(TempoMapBuildError):
            build_manual_tempo_map(
                [(0, pos(0, 1)), (48_000, pos(0, 1))],
                project_id=PROJECT_ID,
                project_sample_rate=RATE,
                source_duration_frames=100_000,
            )


class TestReinterpretation:
    def test_half_time_whole_map(self) -> None:
        original = _map()
        changed = reinterpret_tempo_map(
            original,
            start_anchor_id=original.anchors[0].id,
            end_anchor_id=original.anchors[-1].id,
            mode="half_time",
            updated_at=NOW,
        )
        assert [a.source_frame for a in changed.anchors] == [
            a.source_frame for a in original.anchors
        ]
        assert [a.musical_position for a in changed.anchors] == [
            pos(index * 2, 1) for index in range(11)
        ]
        assert changed.summary_bpm == pytest.approx(240.0)
        assert changed.diagnostics["reinterpretation"] == "half_time"

    def test_double_time_region_keeps_neighbours(self) -> None:
        original = _map()
        changed = reinterpret_tempo_map(
            original,
            start_anchor_id=original.anchors[2].id,
            end_anchor_id=original.anchors[6].id,
            mode="double_time",
        )
        positions = [a.musical_position for a in changed.anchors]
        assert positions[2] == pos(2, 1)
        assert positions[6] == pos(4, 1)
        assert positions[1] == pos(1, 1)
        assert positions[7] == pos(7, 1)
        assert positions == [
            pos(0),
            pos(1),
            pos(2),
            pos(5, 2),
            pos(3),
            pos(7, 2),
            pos(4),
            pos(7),
            pos(8),
            pos(9),
            pos(10),
        ]

    def test_locked_anchor_conflict(self) -> None:
        original = _map()
        locked = original.model_copy(
            update={
                "anchors": [
                    anchor.model_copy(update={"lock_state": AnchorLockState.LOCKED})
                    if index == 5
                    else anchor
                    for index, anchor in enumerate(original.anchors)
                ]
            }
        )
        with pytest.raises(TempoMapConflictError, match="locked"):
            reinterpret_tempo_map(
                locked,
                start_anchor_id=locked.anchors[0].id,
                end_anchor_id=locked.anchors[-1].id,
                mode="half_time",
            )

    def test_locked_end_and_reversal(self) -> None:
        original = _map()
        locked_end = original.model_copy(
            update={
                "anchors": [
                    *original.anchors[:-1],
                    original.anchors[-1].model_copy(update={"lock_state": AnchorLockState.LOCKED}),
                ]
            }
        )
        with pytest.raises(TempoMapConflictError):
            reinterpret_tempo_map(
                locked_end,
                start_anchor_id=locked_end.anchors[0].id,
                end_anchor_id=locked_end.anchors[-1].id,
                mode="half_time",
            )
        with pytest.raises(TempoMapConflictError):
            reinterpret_tempo_map(
                original,
                start_anchor_id=original.anchors[3].id,
                end_anchor_id=original.anchors[1].id,
                mode="half_time",
            )


def test_display_unit_conversion() -> None:
    assert bpm_for_display_unit(120, MeterTempoUnit.QUARTER) == pytest.approx(120)
    assert bpm_for_display_unit(120, MeterTempoUnit.HALF) == pytest.approx(60)
    assert bpm_for_display_unit(120, MeterTempoUnit.DOTTED_QUARTER) == pytest.approx(80)
    assert bpm_for_display_unit(120, MeterTempoUnit.EIGHTH) == pytest.approx(240)


def test_segments_are_cached_for_repeated_mapping() -> None:
    """Meter inference maps thousands of positions; rebuilding segments per
    call made five-minute finalization take ~60 s instead of under a second."""
    import uuid as _uuid

    from basseparate.domain.confidence import Confidence, ConfidenceKind
    from basseparate.domain.rhythm import (
        PulseAcceptance,
        PulseRole,
        RhythmOrigin,
        RhythmPulse,
    )
    from basseparate.rhythm.tempo import build_automatic_tempo_map

    confidence = Confidence(kind=ConfidenceKind.HEURISTIC, value=0.9)
    pulses = [
        RhythmPulse(
            id=_uuid.uuid4(),
            parent_id=_uuid.uuid4(),
            source_frame=index * 24_000,
            model_frame_index=index,
            role=PulseRole.BEAT,
            acceptance=PulseAcceptance.ACCEPTED,
            confidence=confidence,
            origin=RhythmOrigin.AUTOMATIC,
        )
        for index in range(64)
    ]
    tempo_map = build_automatic_tempo_map(
        pulses,
        project_id=_uuid.uuid4(),
        project_sample_rate=48_000,
        source_duration_frames=64 * 24_000,
    )
    assert tempo_map.segments is tempo_map.segments
    assert tempo_map._segment_source_starts is tempo_map._segment_source_starts
