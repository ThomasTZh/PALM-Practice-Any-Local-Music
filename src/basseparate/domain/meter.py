"""Meter inference and regions (M3.8, milestone3.md §10).

Meter is inferred separately from beat detection: accepted pulses and the
tempo map provide timing, accent/onset features provide metrical evidence,
and a versioned scoring profile compares explicit candidates. Ambiguity is
preserved as alternatives and an explicit uncertain/unmetered state.

Manual regions may use any positive numerator/denominator and grouping;
the only boundary rule is that a new region starts on a whole bar of the
preceding interpretation.
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import Sha256Hash, UtcTimestamp, Uuid
from basseparate.domain.confidence import Confidence, ConfidenceKind, ReviewState
from basseparate.domain.rhythm import (
    ActivationArrayRef,
    GridValidity,
    Grouping,
    MeterDenominator,
    MeterHypothesis,
    MeterNumerator,
    MeterTempoUnit,
    MusicalPosition,
    RhythmOrigin,
)
from basseparate.domain.tempo import TempoMap

METER_FEATURE_PROFILE_VERSION = 1
METER_FEATURE_FRAME_RATE = 50.0
METER_FEATURE_SAMPLE_RATE = 22_050
METER_FEATURE_HOP = 441
MAX_METER_REGIONS = 1_000


class MeterFeatureProfile(BaseModel):
    """Versioned, bounded-memory meter evidence profile (§10.2)."""

    model_config = ConfigDict(frozen=True)

    profile_id: str = "meter-features-v1"
    version: int = METER_FEATURE_PROFILE_VERSION
    sample_rate: int = METER_FEATURE_SAMPLE_RATE
    frame_hop: int = METER_FEATURE_HOP
    frame_rate: float = METER_FEATURE_FRAME_RATE
    envelope_window_seconds: float = 0.02
    spectral_fft_size: int = 1_024
    smoothing_frames: int = 1
    normalization_percentile: float = 95.0

    @model_validator(mode="after")
    def _check(self) -> MeterFeatureProfile:
        if self.sample_rate <= 0 or self.frame_hop <= 0:
            raise ValueError("feature sample rate and hop must be positive")
        if abs(self.sample_rate / self.frame_hop - self.frame_rate) > 1e-9:
            raise ValueError("feature frame_rate must equal sample_rate / frame_hop")
        if self.spectral_fft_size < self.frame_hop:
            raise ValueError("fft size must be at least one frame hop")
        return self


METER_FEATURE_PROFILE = MeterFeatureProfile()

ACCENT_FILE = "accent.npy"
ONSET_FILE = "onset.npy"


class MeterFeatureArtifact(BaseModel):
    """Compact accent/onset arrays plus their provenance (§10.2)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    source_hash: Sha256Hash
    profile: MeterFeatureProfile
    frame_count: int = Field(gt=0)
    accent: ActivationArrayRef
    onset: ActivationArrayRef
    content_hash: Sha256Hash
    created_at: UtcTimestamp

    @model_validator(mode="after")
    def _check_arrays(self) -> MeterFeatureArtifact:
        if self.accent.element_count != self.frame_count:
            raise ValueError("accent length must equal frame_count")
        if self.onset.element_count != self.frame_count:
            raise ValueError("onset length must equal frame_count")
        if self.accent.relative_path == self.onset.relative_path:
            raise ValueError("accent and onset must use distinct files")
        return self


class MeterCandidate(BaseModel):
    """One meter hypothesis with its notation grouping (§10.3)."""

    model_config = ConfigDict(frozen=True)

    numerator: MeterNumerator
    denominator: MeterDenominator
    grouping: Grouping
    display_tempo_unit: MeterTempoUnit
    label: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _check_grouping(self) -> MeterCandidate:
        if sum(self.grouping) != self.numerator:
            raise ValueError("grouping must sum to the meter numerator")
        return self

    @property
    def pulses_per_bar(self) -> int:
        return len(self.grouping)

    @property
    def bar_length_quarters(self) -> Fraction:
        return Fraction(4 * self.numerator, self.denominator)


def _candidate(
    numerator: int,
    denominator: int,
    grouping: list[int],
    unit: MeterTempoUnit,
    label: str,
) -> MeterCandidate:
    return MeterCandidate(
        numerator=numerator,
        denominator=denominator,
        grouping=grouping,
        display_tempo_unit=unit,
        label=label,
    )


DEFAULT_METER_CANDIDATES: tuple[MeterCandidate, ...] = (
    _candidate(2, 4, [1, 1], MeterTempoUnit.QUARTER, "2/4"),
    _candidate(3, 4, [1, 1, 1], MeterTempoUnit.QUARTER, "3/4"),
    _candidate(4, 4, [1, 1, 1, 1], MeterTempoUnit.QUARTER, "4/4"),
    _candidate(6, 8, [3, 3], MeterTempoUnit.DOTTED_QUARTER, "6/8 (3+3)"),
    _candidate(9, 8, [3, 3, 3], MeterTempoUnit.DOTTED_QUARTER, "9/8 (3+3+3)"),
    _candidate(12, 8, [3, 3, 3, 3], MeterTempoUnit.DOTTED_QUARTER, "12/8 (3+3+3+3)"),
    _candidate(5, 4, [2, 3], MeterTempoUnit.QUARTER, "5/4 (2+3)"),
    _candidate(5, 4, [3, 2], MeterTempoUnit.QUARTER, "5/4 (3+2)"),
    _candidate(7, 8, [2, 2, 3], MeterTempoUnit.QUARTER, "7/8 (2+2+3)"),
    _candidate(7, 8, [2, 3, 2], MeterTempoUnit.QUARTER, "7/8 (2+3+2)"),
    _candidate(7, 8, [3, 2, 2], MeterTempoUnit.QUARTER, "7/8 (3+2+2)"),
)


class MeterScoreComponents(BaseModel):
    """Component scores retained for diagnostics (§10.4)."""

    model_config = ConfigDict(frozen=True)

    downbeat: float = Field(ge=0.0, le=1.0)
    beat: float = Field(ge=0.0, le=1.0)
    accent: float = Field(ge=0.0, le=1.0)
    subdivision: float = Field(ge=0.0, le=1.0)
    stability: float = Field(ge=0.0, le=1.0)
    missing_pulse: float = Field(ge=0.0, le=1.0)
    transition: float = Field(default=1.0, ge=0.0, le=1.0)
    total: float = Field(ge=0.0, le=1.0)


class MeterScoringProfile(BaseModel):
    """Versioned weights and decision margins."""

    model_config = ConfigDict(frozen=True)

    profile_id: str = "meter-score-v1"
    version: int = 1
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "downbeat": 0.30,
            "beat": 0.15,
            "accent": 0.20,
            "subdivision": 0.10,
            "stability": 0.15,
            "missing_pulse": 0.10,
        }
    )
    uncertain_margin: float = Field(default=0.04, ge=0.0, le=1.0)
    unmetered_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    min_bars: int = Field(default=2, ge=1)

    @model_validator(mode="after")
    def _check_weights(self) -> MeterScoringProfile:
        if not self.weights or any(value < 0 for value in self.weights.values()):
            raise ValueError("meter score weights must be nonnegative")
        if abs(sum(self.weights.values()) - 1.0) > 1e-6:
            raise ValueError("meter score weights must sum to 1")
        return self


METER_SCORING_PROFILE = MeterScoringProfile()


class MeterAlternative(BaseModel):
    """A runner-up candidate with its score and phase (§10.6)."""

    model_config = ConfigDict(frozen=True)

    candidate: MeterCandidate
    phase: int = Field(ge=0)
    score: MeterScoreComponents


class MeterSelection(BaseModel):
    """One automatic meter region decision (currently one per result)."""

    model_config = ConfigDict(frozen=True)

    candidate: MeterCandidate
    phase: int = Field(ge=0)
    start: MusicalPosition
    end: MusicalPosition
    bars: int = Field(ge=0)
    score: MeterScoreComponents
    alternatives: list[MeterAlternative] = Field(default_factory=list, max_length=8)
    uncertain: bool = False
    unmetered: bool = False
    confidence: Confidence

    @model_validator(mode="after")
    def _check(self) -> MeterSelection:
        if self.unmetered and self.bars > 0:
            raise ValueError("an unmetered selection must not claim bars")
        if self.candidate.grouping and sum(self.candidate.grouping) != self.candidate.numerator:
            raise ValueError("candidate grouping is inconsistent")
        return self


class AutomaticMeterResult(BaseModel):
    """Versioned automatic meter inference output (§10.5-§10.6)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    project_id: Uuid
    tempo_map_id: Uuid
    feature_artifact_id: Uuid
    profile: MeterScoringProfile
    feature_profile: MeterFeatureProfile
    selections: list[MeterSelection] = Field(min_length=1, max_length=MAX_METER_REGIONS)
    warnings: list[str] = Field(default_factory=list)
    content_hash: Sha256Hash
    created_at: UtcTimestamp

    @model_validator(mode="after")
    def _check_regions(self) -> AutomaticMeterResult:
        previous_end: MusicalPosition | None = None
        for selection in self.selections:
            if previous_end is not None and (
                selection.start.numerator * previous_end.denominator
                <= previous_end.numerator * selection.start.denominator
            ):
                raise ValueError("meter selections must be strictly ordered")
            if (
                selection.end.numerator * selection.start.denominator
                <= selection.start.numerator * selection.end.denominator
            ):
                raise ValueError("meter selection end must be after start")
            previous_end = selection.end
        return self


def meter_result_content_hash(
    *,
    project_id: Uuid,
    tempo_map_id: Uuid,
    feature_artifact_id: Uuid,
    profile: MeterScoringProfile,
    feature_profile: MeterFeatureProfile,
    selections: list[MeterSelection],
) -> Sha256Hash:
    def candidate_data(candidate: MeterCandidate) -> dict[str, Any]:
        return candidate.model_dump(mode="json")

    payload = {
        "artifact": "automatic-meter-result",
        "version": 1,
        "project_id": str(project_id),
        "tempo_map_id": str(tempo_map_id),
        "feature_artifact_id": str(feature_artifact_id),
        "profile": profile.model_dump(mode="json"),
        "feature_profile": feature_profile.model_dump(mode="json"),
        "selections": [
            {
                "candidate": candidate_data(selection.candidate),
                "phase": selection.phase,
                "start": selection.start.model_dump(mode="json"),
                "end": selection.end.model_dump(mode="json"),
                "bars": selection.bars,
                "score": selection.score.model_dump(mode="json"),
                "uncertain": selection.uncertain,
                "unmetered": selection.unmetered,
            }
            for selection in selections
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def confidence_for_selection(
    score: MeterScoreComponents,
    *,
    uncertain: bool,
    alternatives: list[MeterAlternative],
) -> Confidence:
    """Uncalibrated heuristic confidence with alternatives preserved."""
    value = max(0.0, min(1.0, score.total))
    return Confidence(
        kind=ConfidenceKind.HEURISTIC,
        value=value,
        calibrated=False,
        method="meter-score-v1",
        alternatives=[
            {
                "label": alternative.candidate.label,
                "score": max(0.0, min(1.0, alternative.score.total)),
            }
            for alternative in alternatives
        ]
        or None,
        review_state=ReviewState.UNREVIEWED,
    )


class ManualMeterRegion(BaseModel):
    """One editable/manual meter region specification."""

    model_config = ConfigDict(frozen=True)

    start: MusicalPosition
    candidate: MeterCandidate
    origin: RhythmOrigin = RhythmOrigin.MANUAL
    confidence: Confidence | None = None
    uncertain: bool = False
    alternatives: list[MeterHypothesis] = Field(default_factory=list, max_length=8)


class MeterMap(BaseModel):
    """Validated meter regions over a tempo map (automatic or manual).

    Ends are derived from the next region; a region starts on a whole bar
    of the preceding interpretation. Bar phase through a change starts at
    beat 1 of the new meter.
    """

    model_config = ConfigDict(frozen=True)

    regions: list[ManualMeterRegion] = Field(min_length=1, max_length=MAX_METER_REGIONS)

    @model_validator(mode="after")
    def _check_boundaries(self) -> MeterMap:
        previous = None
        for region in self.regions:
            if region.start.is_negative:
                raise ValueError("a meter region start must be nonnegative")
            if previous is not None:
                if (
                    region.start.numerator * previous.start.denominator
                    <= previous.start.numerator * region.start.denominator
                ):
                    raise ValueError("meter regions must be strictly ordered")
                delta = region.start.as_quarter_notes() - previous.start.as_quarter_notes()
                bars = delta / previous.candidate.bar_length_quarters
                if bars.denominator != 1:
                    raise ValueError(
                        "a meter region must start on a whole bar of the preceding meter"
                    )
            previous = region
        return self

    def ends(self) -> list[MusicalPosition | None]:
        return [
            self.regions[index + 1].start if index + 1 < len(self.regions) else None
            for index in range(len(self.regions))
        ]

    def region_at(self, position: MusicalPosition) -> ManualMeterRegion | None:
        selected = None
        for region in self.regions:
            if (
                region.start.numerator * position.denominator
                <= position.numerator * region.start.denominator
            ):
                selected = region
            else:
                break
        return selected


def build_meter_map(regions: list[ManualMeterRegion]) -> MeterMap:
    return MeterMap(regions=regions)


def manual_candidate(
    numerator: int,
    denominator: int,
    grouping: list[int],
    display_unit: MeterTempoUnit | None = None,
) -> MeterCandidate:
    """Validate an arbitrary manual meter (§10.7)."""
    unit = display_unit or MeterTempoUnit.QUARTER
    label = f"{numerator}/{denominator}" + (
        f" ({'+'.join(str(part) for part in grouping)})" if grouping else ""
    )
    return MeterCandidate(
        numerator=numerator,
        denominator=denominator,
        grouping=grouping,
        display_tempo_unit=unit,
        label=label,
    )


def region_validity(meter_map: MeterMap) -> GridValidity:
    if any(region.uncertain for region in meter_map.regions):
        return GridValidity.UNCERTAIN
    return GridValidity.VALID


def meter_map_content_hash(meter_map: MeterMap) -> Sha256Hash:
    encoded = json.dumps(
        meter_map.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def segment_region(tempo_map: TempoMap, selection: MeterSelection) -> dict[str, Any]:
    """Diagnostics helper: resolved source boundaries for one selection."""
    return {
        "start_source": tempo_map.map_musical_to_source(selection.start),
        "end_source": tempo_map.map_musical_to_source(selection.end),
        "candidate": selection.candidate.label,
        "bars": selection.bars,
        "uncertain": selection.uncertain,
        "unmetered": selection.unmetered,
    }
