"""Tempo map domain (M3.7, milestone3.md §9).

A tempo map is a strictly monotonic piecewise-linear mapping between
source frames and exact rational musical positions. Each adjacent pair of
tempo anchors defines one segment; interpolation is exact (Fraction), and
rounding to an integer source frame happens only at a discrete event or
boundary.

Pulse-unit hypotheses convert neutral decoded pulses into musical
distances (quarter, half, eighth, dotted quarter, denominator unit, or an
irregular grouping sequence). They are versioned and stored with the map;
the selected interpretation and its alternatives remain inspectable.
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from enum import StrEnum
from fractions import Fraction
from functools import cached_property
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import (
    SamplePosition,
    SampleRate,
    UtcTimestamp,
    Uuid,
)
from basseparate.domain.confidence import Confidence
from basseparate.domain.rhythm import (
    AnchorLockState,
    MeterTempoUnit,
    MusicalPosition,
    RhythmOrigin,
)

MAX_TEMPO_ANCHORS = 10_000
MAX_PULSE_DISTANCES = 64


class PulseUnit(StrEnum):
    """Pulse-unit interpretation families (§9.2)."""

    QUARTER = "quarter"
    HALF = "half"
    EIGHTH = "eighth"
    DOTTED_QUARTER = "dotted_quarter"
    DENOMINATOR_UNIT = "denominator_unit"
    GROUPING = "grouping"


class PulseUnitHypothesis(BaseModel):
    """One interpretation of what musical distance a pulse represents."""

    model_config = ConfigDict(frozen=True)

    unit: PulseUnit
    label: str = Field(min_length=1, max_length=120)
    distances: list[MusicalPosition] = Field(
        min_length=1,
        max_length=MAX_PULSE_DISTANCES,
        description="Quarter-note distance for each successive pulse in the sequence",
    )
    requires_meter: bool = False
    rationale: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check_distances(self) -> PulseUnitHypothesis:
        for distance in self.distances:
            if distance.numerator <= 0:
                raise ValueError("pulse-unit distances must be positive")
        return self

    def distance_for(self, pulse_index: int) -> MusicalPosition:
        """Distance from pulse ``pulse_index`` to the next pulse."""
        return self.distances[pulse_index % len(self.distances)]


def _pos(numerator: int, denominator: int = 1) -> MusicalPosition:
    return MusicalPosition(numerator=numerator, denominator=denominator)


PULSE_UNIT_QUARTER = PulseUnitHypothesis(
    unit=PulseUnit.QUARTER,
    label="Quarter-note pulse",
    distances=[_pos(1)],
    rationale="Default when pulse evidence and meter do not justify another unit.",
)
PULSE_UNIT_HALF = PulseUnitHypothesis(
    unit=PulseUnit.HALF,
    label="Half-note pulse (half-time interpretation)",
    distances=[_pos(2)],
    rationale="Each detected pulse spans two quarter notes.",
)
PULSE_UNIT_EIGHTH = PulseUnitHypothesis(
    unit=PulseUnit.EIGHTH,
    label="Eighth-note pulse (double-time interpretation)",
    distances=[_pos(1, 2)],
    requires_meter=True,
    rationale="Each detected pulse spans half a quarter note.",
)
PULSE_UNIT_DOTTED_QUARTER = PulseUnitHypothesis(
    unit=PulseUnit.DOTTED_QUARTER,
    label="Dotted-quarter pulse (compound meter)",
    distances=[_pos(3, 2)],
    requires_meter=True,
    rationale="Standard compound-meter primary pulse.",
)

STANDARD_PULSE_UNIT_HYPOTHESES: tuple[PulseUnitHypothesis, ...] = (
    PULSE_UNIT_QUARTER,
    PULSE_UNIT_HALF,
    PULSE_UNIT_EIGHTH,
    PULSE_UNIT_DOTTED_QUARTER,
)


def denominator_pulse_hypothesis(denominator: int) -> PulseUnitHypothesis:
    """One pulse per denominator unit (e.g. eighth notes in 7/8)."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    return PulseUnitHypothesis(
        unit=PulseUnit.DENOMINATOR_UNIT,
        label=f"One pulse per 1/{denominator} note",
        distances=[_pos(4, denominator)],
        requires_meter=True,
        rationale="Denominator-unit pulse evidence under a known meter.",
    )


def grouping_pulse_hypothesis(
    grouping: list[int], denominator: int
) -> PulseUnitHypothesis:
    """Pulses at grouping boundaries (e.g. 7/8 = 2+2+3)."""
    if denominator <= 0 or not grouping or any(part <= 0 for part in grouping):
        raise ValueError("grouping and denominator must describe a valid meter")
    distances = [_pos(part * 4, denominator) for part in grouping]
    return PulseUnitHypothesis(
        unit=PulseUnit.GROUPING,
        label=(
            f"Grouping pulses ({'+'.join(str(part) for part in grouping)}/{denominator})"
        ),
        distances=distances,
        requires_meter=True,
        rationale="Primary grouping boundaries of an irregular or compound meter.",
    )


class TempoMapRangeError(ValueError):
    """A source or musical position lies outside the mapped interval."""


class TempoMapAnchor(BaseModel):
    """One control point in an automatic or manual tempo map."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    source_frame: SamplePosition
    musical_position: MusicalPosition
    lock_state: AnchorLockState = AnchorLockState.UNLOCKED
    origin: RhythmOrigin = RhythmOrigin.AUTOMATIC
    pulse_id: Uuid | None = None
    confidence: Confidence | None = None
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    @model_validator(mode="after")
    def _check_position(self) -> TempoMapAnchor:
        if self.musical_position.is_negative:
            raise ValueError("a tempo anchor musical position must be nonnegative")
        return self


class TempoMapSegment(BaseModel):
    """One derived anchor-to-anchor segment (BPM is not authoritative)."""

    model_config = ConfigDict(frozen=True)

    source_start: SamplePosition
    source_end: SamplePosition
    musical_start: MusicalPosition
    musical_end: MusicalPosition
    quarter_note_bpm: float = Field(gt=0.0)
    source_seconds: float = Field(gt=0.0)


class TempoMap(BaseModel):
    """Strictly monotonic piecewise-linear source↔musical mapping (§9.1)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    project_id: Uuid
    project_sample_rate: SampleRate
    source_duration_frames: SamplePosition
    hypothesis: PulseUnitHypothesis
    alternatives: list[PulseUnitHypothesis] = Field(default_factory=list, max_length=8)
    anchors: list[TempoMapAnchor] = Field(
        min_length=2, max_length=MAX_TEMPO_ANCHORS
    )
    summary_bpm: float = Field(gt=0.0)
    summary_unit: MeterTempoUnit = MeterTempoUnit.QUARTER
    max_edge_extension_quarters: float = Field(default=0.0, ge=0.0)
    diagnostics: dict[str, float | int | str] = Field(default_factory=dict)
    created_at: UtcTimestamp

    @model_validator(mode="after")
    def _check_monotonic(self) -> TempoMap:
        previous_source = -1
        previous_musical: MusicalPosition | None = None
        for anchor in self.anchors:
            if anchor.source_frame <= previous_source:
                raise ValueError("tempo-map source positions must strictly increase")
            if anchor.source_frame > self.source_duration_frames:
                raise ValueError("a tempo anchor lies outside the source duration")
            if previous_musical is not None and (
                anchor.musical_position.numerator * previous_musical.denominator
                <= previous_musical.numerator * anchor.musical_position.denominator
            ):
                raise ValueError("tempo-map musical positions must strictly increase")
            previous_source = anchor.source_frame
            previous_musical = anchor.musical_position
        for segment in self.segments:
            if not math.isfinite(segment.quarter_note_bpm):
                raise ValueError("tempo-map segment BPM must be finite")
        if not math.isfinite(self.summary_bpm):
            raise ValueError("summary BPM must be finite")
        return self

    @cached_property
    def segments(self) -> list[TempoMapSegment]:
        result: list[TempoMapSegment] = []
        for left, right in zip(self.anchors, self.anchors[1:], strict=False):
            source_frames = right.source_frame - left.source_frame
            seconds = source_frames / self.project_sample_rate
            quarters = right.musical_position.as_quarter_notes() - (
                left.musical_position.as_quarter_notes()
            )
            bpm = float(60 * quarters / seconds)
            result.append(
                TempoMapSegment(
                    source_start=left.source_frame,
                    source_end=right.source_frame,
                    musical_start=left.musical_position,
                    musical_end=right.musical_position,
                    quarter_note_bpm=bpm,
                    source_seconds=seconds,
                )
            )
        return result

    @property
    def musical_start(self) -> MusicalPosition:
        return self.anchors[0].musical_position

    @property
    def musical_end(self) -> MusicalPosition:
        return self.anchors[-1].musical_position

    @cached_property
    def _segment_source_starts(self) -> list[int]:
        return [segment.source_start for segment in self.segments]

    @cached_property
    def _segment_musical_starts(self) -> list[Fraction]:
        return [segment.musical_start.as_quarter_notes() for segment in self.segments]

    def _segment_for_source(self, source_frame: int) -> TempoMapSegment:
        if source_frame < self.anchors[0].source_frame or source_frame > self.anchors[
            -1
        ].source_frame:
            raise TempoMapRangeError(
                f"source frame {source_frame} is outside the mapped tempo interval"
            )
        # Anchors are strictly increasing; binary-search the segment. A
        # boundary frame belongs to the segment that ends there, which is
        # equivalent for BPM and mapping purposes.
        index = bisect_right(self._segment_source_starts, source_frame)
        index = max(0, min(index - 1, len(self.segments) - 1))
        return self.segments[index]

    def _segment_for_musical(self, position: MusicalPosition) -> TempoMapSegment:
        start = self.musical_start.as_quarter_notes()
        end = self.musical_end.as_quarter_notes()
        value = position.as_quarter_notes()
        if value < start or value > end:
            raise TempoMapRangeError(
                "musical position is outside the mapped tempo interval"
            )
        index = bisect_right(self._segment_musical_starts, value)
        index = max(0, min(index - 1, len(self.segments) - 1))
        return self.segments[index]

    def map_source_to_musical(self, source_frame: int) -> MusicalPosition:
        """Exact musical position for a source frame (§9.1)."""
        segment = self._segment_for_source(source_frame)
        fraction = (
            segment.musical_start.as_quarter_notes()
            + Fraction(source_frame - segment.source_start, 1)
            * (
                segment.musical_end.as_quarter_notes()
                - segment.musical_start.as_quarter_notes()
            )
            / Fraction(segment.source_end - segment.source_start, 1)
        )
        return MusicalPosition(
            numerator=fraction.numerator, denominator=fraction.denominator
        )

    def source_fraction_for_musical(self, position: MusicalPosition) -> Fraction:
        """Exact fractional source frame for a musical position (no rounding)."""
        segment = self._segment_for_musical(position)
        return (
            Fraction(segment.source_start, 1)
            + (position.as_quarter_notes() - segment.musical_start.as_quarter_notes())
            * Fraction(segment.source_end - segment.source_start, 1)
            / (
                segment.musical_end.as_quarter_notes()
                - segment.musical_start.as_quarter_notes()
            )
        )

    def map_musical_to_source(
        self, position: MusicalPosition, *, rounding: Literal["half_up"] = "half_up"
    ) -> int:
        """Source frame for a musical position, rounded once (§9.1)."""
        if rounding != "half_up":
            raise ValueError(f"unsupported rounding mode {rounding!r}")
        fraction = self.source_fraction_for_musical(position)
        return int(math.floor(fraction + Fraction(1, 2)))

    def local_bpm_at_source(self, source_frame: int) -> float:
        """The local segment BPM (derived, never authoritative)."""
        return self._segment_for_source(source_frame).quarter_note_bpm


def summarize_bpm(segments: list[TempoMapSegment]) -> float:
    """Robust summary tempo: median segment BPM, not a replacement map."""
    if not segments:
        raise ValueError("a tempo map needs at least one segment")
    return float(statistics.median(segment.quarter_note_bpm for segment in segments))
