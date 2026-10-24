"""Deterministic rhythm corpus (M3.19 §21.1-§21.2).

Cases are described by tempo and meter metadata only; audio and
activation arrays are generated in tests, never committed. The corpus is
shared with the TypeScript mapping tests through
``tests/fixtures/rhythm-corpus.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.meter import (
    ManualMeterRegion,
    MeterMap,
    build_meter_map,
    manual_candidate,
)
from basseparate.domain.rhythm import (
    ZERO_MUSICAL_POSITION,
    BarOriginState,
    MusicalPosition,
    PulseAcceptance,
    PulseRole,
    RhythmOrigin,
    RhythmPulse,
)
from basseparate.domain.tempo import PULSE_UNIT_QUARTER, TempoMap, TempoMapAnchor

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
SAMPLE_RATE = 48_000


@dataclass(frozen=True)
class TempoSegment:
    bpm: float
    bars: int


@dataclass(frozen=True)
class MeterChange:
    at_bar: int
    numerator: int
    denominator: int
    grouping: tuple[int, ...]


@dataclass(frozen=True)
class RhythmCase:
    """One synthetic rhythm case (tempo/meter description)."""

    id: str
    title: str
    bpm: float
    numerator: int
    denominator: int
    grouping: tuple[int, ...]
    bars: int = 8
    pickup_beats: int = 0
    start_bar_offset: int = 0
    missing_beats: tuple[int, ...] = ()
    extra_offbeats: tuple[int, ...] = ()
    silence_before_beat: int = 0
    meter_changes: tuple[MeterChange, ...] = ()
    tempo_segments: tuple[TempoSegment, ...] = ()
    subdivision: bool = False

    def confidence(self) -> Confidence:
        return Confidence(kind=ConfidenceKind.HEURISTIC, value=0.9)


def _musical(quarters: Fraction) -> MusicalPosition:
    return MusicalPosition(numerator=quarters.numerator, denominator=quarters.denominator)


def _bar_length_quarters(case: RhythmCase) -> Fraction:
    return Fraction(4 * case.numerator, case.denominator)


def _beat_quarters(case: RhythmCase) -> Fraction:
    return Fraction(4, case.denominator)


def build_case(
    case: RhythmCase,
) -> tuple[TempoMap, MeterMap, list[RhythmPulse], BarOriginState]:
    """Build the pulse/activation-free ground truth for one case."""
    pulse_quarters = _beat_quarters(case)
    project_id = __import__("uuid").UUID(int=0)

    frames_per_quarter = Fraction(SAMPLE_RATE * 60) / Fraction(case.bpm).limit_denominator(1000)

    anchors: list[TempoMapAnchor] = []
    pulses: list[RhythmPulse] = []
    frames = Fraction(0)
    quarter = Fraction(0)
    bar = 0
    beat_in_bar = 0
    meter_regions = [
        ManualMeterRegion(
            start=ZERO_MUSICAL_POSITION,
            candidate=manual_candidate(case.numerator, case.denominator, list(case.grouping)),
            origin=RhythmOrigin.AUTOMATIC,
            confidence=case.confidence(),
        )
    ]
    change_by_bar = {change.at_bar: change for change in case.meter_changes}
    bpm = case.bpm
    segment_index = 0
    segment_bar = 0

    total_beats = case.bars * case.numerator
    for beat_index in range(total_beats):
        if case.tempo_segments and segment_index < len(case.tempo_segments):
            current = case.tempo_segments[segment_index]
            if (
                bar >= segment_bar + current.bars
                and segment_index + 1 < len(case.tempo_segments)
            ):
                segment_index += 1
                segment_bar = bar
                bpm = case.tempo_segments[segment_index].bpm
                frames_per_quarter = (
                    Fraction(SAMPLE_RATE * 60) / Fraction(bpm).limit_denominator(1000)
                )
        if bar in change_by_bar and beat_in_bar == 0:
            change = change_by_bar[bar]
            start = _musical(quarter)
            meter_regions.append(
                ManualMeterRegion(
                    start=start,
                    candidate=manual_candidate(
                        change.numerator, change.denominator, list(change.grouping)
                    ),
                    origin=RhythmOrigin.AUTOMATIC,
                    confidence=case.confidence(),
                )
            )
            pulse_quarters = Fraction(4, change.denominator)
        if beat_index in case.missing_beats:
            frames += pulse_quarters * frames_per_quarter
            quarter += pulse_quarters
            beat_in_bar += 1
            continue
        source_frame = int(frames)
        role = PulseRole.DOWNBEAT if beat_in_bar == 0 else PulseRole.BEAT
        pulse = RhythmPulse(
            id=__import__("uuid").uuid4(),
            parent_id=project_id,
            source_frame=source_frame,
            model_frame_index=beat_index,
            role=role,
            acceptance=PulseAcceptance.ACCEPTED,
            confidence=case.confidence(),
            origin=RhythmOrigin.AUTOMATIC,
        )
        pulses.append(pulse)
        anchors.append(
            TempoMapAnchor(
                id=__import__("uuid").uuid4(),
                source_frame=source_frame,
                musical_position=_musical(quarter),
                origin=RhythmOrigin.AUTOMATIC,
                pulse_id=pulse.id,
                confidence=pulse.confidence,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        frames += pulse_quarters * frames_per_quarter
        quarter += pulse_quarters
        beat_in_bar += 1
        if beat_in_bar >= case.numerator:
            beat_in_bar = 0
            bar += 1

    duration = int(frames) + SAMPLE_RATE
    tempo_map = TempoMap(
        id=__import__("uuid").uuid4(),
        project_id=project_id,
        project_sample_rate=SAMPLE_RATE,
        source_duration_frames=duration,
        hypothesis=PULSE_UNIT_QUARTER,
        alternatives=[],
        anchors=anchors,
        summary_bpm=case.bpm,
        created_at=NOW,
    )
    meter_map = build_meter_map(meter_regions)
    leading_quarters = (
        Fraction(case.pickup_beats) + Fraction(case.start_bar_offset)
    ) * _beat_quarters(case)
    if leading_quarters > 0:
        bar = Fraction(4 * case.numerator, case.denominator)
        origin_quarters = bar * ((leading_quarters + bar - 1) // bar)
    else:
        origin_quarters = Fraction(0)
    origin = BarOriginState(
        first_numbered_bar_position=_musical(origin_quarters),
        pickup=None,
    )
    return tempo_map, meter_map, pulses, origin


def _case(
    ident: str,
    title: str,
    bpm: float,
    numerator: int,
    denominator: int,
    grouping: tuple[int, ...],
    **kwargs: object,
) -> RhythmCase:
    return RhythmCase(
        id=ident,
        title=title,
        bpm=bpm,
        numerator=numerator,
        denominator=denominator,
        grouping=grouping,
        **kwargs,  # type: ignore[arg-type]
    )


def corpus_cases() -> tuple[RhythmCase, ...]:
    """The 21 deterministic cases required by §21.1."""
    return (
        _case("4-4-constant", "4/4 clicks at 120", 120, 4, 4, (1, 1, 1, 1)),
        _case("3-4-constant", "3/4 clicks at 90", 90, 3, 4, (1, 1, 1)),
        _case("6-8-compound", "6/8 3+3 at 100", 100, 6, 8, (3, 3)),
        _case("9-8-compound", "9/8 3+3+3 at 110", 110, 9, 8, (3, 3, 3)),
        _case("12-8-compound", "12/8 compound at 96", 96, 12, 8, (3, 3, 3, 3)),
        _case("5-4-a", "5/4 2+3 at 100", 100, 5, 4, (2, 3)),
        _case("5-4-b", "5/4 3+2 at 100", 100, 5, 4, (3, 2)),
        _case("7-8-223", "7/8 2+2+3", 120, 7, 8, (2, 2, 3)),
        _case("7-8-232", "7/8 2+3+2", 120, 7, 8, (2, 3, 2)),
        _case("7-8-322", "7/8 3+2+2", 120, 7, 8, (3, 2, 2)),
        _case(
            "tempo-ramp",
            "linear tempo ramp",
            100,
            4,
            4,
            (1, 1, 1, 1),
            tempo_segments=(TempoSegment(90, 2), TempoSegment(120, 2), TempoSegment(150, 4)),
        ),
        _case(
            "tempo-jump",
            "piecewise tempo jump",
            100,
            4,
            4,
            (1, 1, 1, 1),
            tempo_segments=(TempoSegment(100, 4), TempoSegment(140, 4)),
        ),
        _case("humanized", "humanized timing", 120, 4, 4, (1, 1, 1, 1), bars=4),
        _case(
            "half-time",
            "half-time ambiguity",
            60,
            4,
            4,
            (1, 1, 1, 1),
            subdivision=True,
        ),
        _case("pickup", "one-beat pickup", 120, 4, 4, (1, 1, 1, 1), pickup_beats=1),
        _case(
            "mid-bar-start",
            "project starts mid-bar",
            120,
            4,
            4,
            (1, 1, 1, 1),
            start_bar_offset=2,
        ),
        _case(
            "meter-4-4-to-3-4",
            "4/4 to 3/4",
            120,
            4,
            4,
            (1, 1, 1, 1),
            meter_changes=(MeterChange(4, 3, 4, (1, 1, 1)),),
        ),
        _case(
            "meter-4-4-to-6-8",
            "4/4 to 6/8",
            120,
            4,
            4,
            (1, 1, 1, 1),
            meter_changes=(MeterChange(4, 6, 8, (3, 3)),),
        ),
        _case(
            "silent-intro",
            "silent intro then rhythm",
            120,
            4,
            4,
            (1, 1, 1, 1),
            silence_before_beat=16,
        ),
        _case(
            "silent-break",
            "internal silent break",
            120,
            4,
            4,
            (1, 1, 1, 1),
            missing_beats=(12, 13, 14, 15),
        ),
        _case("missing-beats", "missing beats", 120, 4, 4, (1, 1, 1, 1), missing_beats=(5, 9)),
        _case("pure-silence", "pure silence", 120, 4, 4, (1, 1, 1, 1), bars=0),
        _case(
            "syncopation",
            "strong syncopation",
            120,
            4,
            4,
            (1, 1, 1, 1),
            extra_offbeats=(2, 6, 10),
        ),
        _case(
            "extra-offbeats",
            "extra offbeat transients",
            120,
            4,
            4,
            (1, 1, 1, 1),
            extra_offbeats=(1, 3, 7, 11),
        ),
    )


def golden_mapping() -> dict[str, object]:
    """Small non-audio mapping fixture shared with the TypeScript tests."""
    case = corpus_cases()[0]
    tempo_map, meter_map, pulses, _origin = build_case(case)
    anchors = [
        {
            "source_frame": anchor.source_frame,
            "musical_position": {
                "numerator": anchor.musical_position.numerator,
                "denominator": anchor.musical_position.denominator,
            },
        }
        for anchor in tempo_map.anchors[:5]
    ]
    samples = []
    for index in range(4):
        frame = tempo_map.anchors[index].source_frame + 12_000
        position = tempo_map.map_source_to_musical(frame)
        samples.append(
            {
                "source_frame": frame,
                "musical_position": {
                    "numerator": position.numerator,
                    "denominator": position.denominator,
                },
                "back_to_source": tempo_map.map_musical_to_source(position),
            }
        )
    return {
        "sample_rate": SAMPLE_RATE,
        "source_duration_frames": tempo_map.source_duration_frames,
        "anchors": anchors,
        "samples": samples,
        "first_bar": {
            "numerator": meter_map.regions[0].candidate.numerator,
            "denominator": meter_map.regions[0].candidate.denominator,
            "grouping": meter_map.regions[0].candidate.grouping,
        },
        "pulse_count": len(pulses),
    }


def write_fixtures(root: Path) -> None:
    import json

    root.mkdir(parents=True, exist_ok=True)
    (root / "golden-mapping.json").write_text(
        json.dumps(golden_mapping(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    cases = [
        {
            "id": case.id,
            "title": case.title,
            "bpm": case.bpm,
            "numerator": case.numerator,
            "denominator": case.denominator,
            "grouping": list(case.grouping),
            "bars": case.bars,
            "pickup_beats": case.pickup_beats,
            "meter_changes": [
                {
                    "at_bar": change.at_bar,
                    "numerator": change.numerator,
                    "denominator": change.denominator,
                    "grouping": list(change.grouping),
                }
                for change in case.meter_changes
            ],
        }
        for case in corpus_cases()
    ]
    (root / "rhythm-corpus.json").write_text(
        json.dumps({"cases": cases}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
