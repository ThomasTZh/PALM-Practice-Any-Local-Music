"""Rhythm domain models (M3.1, milestone3.md §3).

Milestone 3 layers a musical coordinate system on top of source time.
Source frames stay authoritative for audio; musical positions are exact
reduced rational quarter-note coordinates, so bar and meter arithmetic
never accumulates floating-point drift.

This module defines the shared primitives and the durable record shapes:
analysis runs, activation artifacts, pulses, tempo anchors, meter
regions, bar-origin/pickup state, editable rhythm branches, and the
project-level rhythm state. Automatic results are published in M3.6;
this package provides the records and schema they build on.
"""

from __future__ import annotations

from enum import StrEnum
from fractions import Fraction
from math import gcd
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from basseparate.domain.common import (
    JS_SAFE_INTEGER_MAX,
    HalfOpenInterval,
    Revision,
    SamplePosition,
    SampleRate,
    Sha256Hash,
    UtcTimestamp,
    Uuid,
)
from basseparate.domain.confidence import Confidence, ReviewState
from basseparate.domain.separation import DeviceType

#: Bounded collections keep the branch record (and its JSON) bounded.
MAX_PULSES = 50_000
MAX_TEMPO_ANCHORS = 10_000
MAX_METER_REGIONS = 1_000
MAX_GROUPING_PARTS = 64
MAX_METER_NUMERATOR = 256
MAX_METER_DENOMINATOR = 1024
MAX_METER_ALTERNATIVES = 8
MAX_RUN_WARNINGS = 128
MAX_WARNING_LENGTH = 500

#: Version of the activation artifact manifest format.
ACTIVATION_FORMAT_VERSION = 1

#: Bounds on the metronome volume, matching the project master-gain range.
MAX_METRONOME_VOLUME = 2.0
MIN_RHYTHM_LANE_HEIGHT = 0.25
MAX_RHYTHM_LANE_HEIGHT = 2.0


class MusicalPosition(BaseModel):
    """Exact reduced rational musical position in quarter-note units.

    The denominator is always positive; the sign lives on the numerator.
    Zero is always ``0/1``. Normalized components stay within the
    JavaScript safe-integer range so the browser never receives a value
    it cannot represent exactly.
    """

    model_config = ConfigDict(frozen=True)

    numerator: StrictInt = Field(description="Signed quarter-note numerator")
    denominator: StrictInt = Field(gt=0, description="Positive denominator")

    def model_post_init(self, __context: object) -> None:
        numerator = self.numerator
        denominator = self.denominator
        if abs(numerator) > JS_SAFE_INTEGER_MAX:
            raise ValueError("musical position numerator exceeds the safe-integer range")
        if denominator > JS_SAFE_INTEGER_MAX:
            raise ValueError("musical position denominator exceeds the safe-integer range")
        divisor = gcd(abs(numerator), denominator)
        numerator //= divisor
        denominator //= divisor
        if numerator == 0:
            denominator = 1
        if abs(numerator) > JS_SAFE_INTEGER_MAX or denominator > JS_SAFE_INTEGER_MAX:
            raise ValueError("normalized musical position exceeds the safe-integer range")
        object.__setattr__(self, "numerator", numerator)
        object.__setattr__(self, "denominator", denominator)

    def as_quarter_notes(self) -> Fraction:
        """Exact quarter-note value (Python-only; never serialized)."""
        return Fraction(self.numerator, self.denominator)

    @property
    def is_negative(self) -> bool:
        """Whether the position lies before the quarter-note origin."""
        return self.numerator < 0

    def add(self, other: MusicalPosition) -> MusicalPosition:
        """Exact sum of two musical positions."""
        left = self.as_quarter_notes() + other.as_quarter_notes()
        return MusicalPosition(numerator=left.numerator, denominator=left.denominator)

    def difference(self, other: MusicalPosition) -> MusicalPosition:
        """Exact ``self - other`` as a musical position."""
        left = self.as_quarter_notes() - other.as_quarter_notes()
        return MusicalPosition(numerator=left.numerator, denominator=left.denominator)


def compare_musical_positions(left: MusicalPosition, right: MusicalPosition) -> int:
    """Three-way comparison (-1, 0, 1) using exact cross-multiplication."""
    left_value = left.as_quarter_notes()
    right_value = right.as_quarter_notes()
    return (left_value > right_value) - (left_value < right_value)


ZERO_MUSICAL_POSITION = MusicalPosition(numerator=0, denominator=1)


class MusicalInterval(BaseModel):
    """Half-open interval ``[start, end)`` in musical positions."""

    model_config = ConfigDict(frozen=True)

    start: MusicalPosition
    end: MusicalPosition

    @model_validator(mode="after")
    def _check_order(self) -> MusicalInterval:
        if compare_musical_positions(self.end, self.start) <= 0:
            raise ValueError("musical interval end must be strictly greater than start")
        return self


# --- Shared enums (milestone3.md §3.2) -----------------------------------


class PulseRole(StrEnum):
    """Evidence class of a rhythm pulse, independent of meter."""

    BEAT = "beat"
    DOWNBEAT = "downbeat"
    CANDIDATE = "candidate"
    UNKNOWN = "unknown"


class PulseAcceptance(StrEnum):
    """Whether a pulse currently contributes to the grid."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANDIDATE = "candidate"


class GridValidity(StrEnum):
    """Explicit validity of a rhythm branch over its mapped region."""

    VALID = "valid"
    UNCERTAIN = "uncertain"
    UNMETERED = "unmetered"
    UNMAPPED = "unmapped"


class AnchorLockState(StrEnum):
    """Whether a tempo anchor may be moved by automatic re-derivation."""

    UNLOCKED = "unlocked"
    LOCKED = "locked"


class LoopAnchorMode(StrEnum):
    """Authoritative coordinate pair for a practice loop (M3.13)."""

    SOURCE = "source"
    MUSICAL = "musical"


class RhythmOrigin(StrEnum):
    """Provenance of an editable rhythm object."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


class RhythmInputRole(StrEnum):
    """Input used for a rhythm analysis (milestone3.md §3.3)."""

    ORIGINAL_MIX = "original_mix"
    DRUM_STEM = "drum_stem"


class BeatModelPreset(StrEnum):
    """Beat This! preset names (milestone3.md §2)."""

    FINAL0 = "final0"
    SMALL0 = "small0"


class RhythmAnalysisStatus(StrEnum):
    """Rhythm analysis run lifecycle; mirrors the durable job states."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class RhythmDisplayMode(StrEnum):
    """Whether the project shows the automatic result or an edited branch."""

    AUTOMATIC = "automatic"
    EDITED = "edited"


class SnapMode(StrEnum):
    """Musical snapping modes (milestone3.md §14.1)."""

    OFF = "off"
    BEAT = "beat"
    HALF_BEAT = "half_beat"
    QUARTER_BEAT = "quarter_beat"
    BAR = "bar"
    EVENT = "event"


class MeterTempoUnit(StrEnum):
    """Note value used to display the local tempo (milestone3.md §9.6)."""

    WHOLE = "whole"
    HALF = "half"
    QUARTER = "quarter"
    EIGHTH = "eighth"
    SIXTEENTH = "sixteenth"
    DOTTED_WHOLE = "dotted_whole"
    DOTTED_HALF = "dotted_half"
    DOTTED_QUARTER = "dotted_quarter"
    DOTTED_EIGHTH = "dotted_eighth"
    DOTTED_SIXTEENTH = "dotted_sixteenth"


#: Exact length of each display unit in quarter notes.
_TEMPO_UNIT_QUARTER_LENGTHS: dict[MeterTempoUnit, Fraction] = {
    MeterTempoUnit.WHOLE: Fraction(4),
    MeterTempoUnit.HALF: Fraction(2),
    MeterTempoUnit.QUARTER: Fraction(1),
    MeterTempoUnit.EIGHTH: Fraction(1, 2),
    MeterTempoUnit.SIXTEENTH: Fraction(1, 4),
    MeterTempoUnit.DOTTED_WHOLE: Fraction(6),
    MeterTempoUnit.DOTTED_HALF: Fraction(3),
    MeterTempoUnit.DOTTED_QUARTER: Fraction(3, 2),
    MeterTempoUnit.DOTTED_EIGHTH: Fraction(3, 4),
    MeterTempoUnit.DOTTED_SIXTEENTH: Fraction(3, 8),
}


def tempo_unit_quarter_length(unit: MeterTempoUnit) -> Fraction:
    """Exact quarter-note length of a display tempo unit."""
    return _TEMPO_UNIT_QUARTER_LENGTHS[unit]


class MetronomeSubdivision(StrEnum):
    """Metronome subdivision modes (milestone3.md §16.6)."""

    PRIMARY = "primary"
    DENOMINATOR = "denominator"
    HALF_BEAT = "half_beat"
    QUARTER_BEAT = "quarter_beat"


class CountInMode(StrEnum):
    """Count-in length (milestone3.md §17.1)."""

    OFF = "off"
    ONE_BAR = "one_bar"
    TWO_BARS = "two_bars"


class CountInRepetition(StrEnum):
    """Whether count-in repeats with every loop pass (milestone3.md §17.9)."""

    ONCE = "once"
    EVERY_REPEAT = "every_repeat"


class SelectedRhythmObjectKind(StrEnum):
    """Kinds that can be the project's last selected rhythm object."""

    PULSE = "pulse"
    TEMPO_ANCHOR = "tempo_anchor"
    METER_REGION = "meter_region"


# --- Shared integer and collection aliases ------------------------------


BarNumber = Annotated[
    StrictInt,
    Field(ge=-9_999, le=99_999, description="Signed bar display number"),
]
MeterNumerator = Annotated[
    StrictInt,
    Field(ge=1, le=MAX_METER_NUMERATOR, description="Positive meter numerator"),
]
MeterDenominator = Annotated[
    StrictInt,
    Field(ge=1, le=MAX_METER_DENOMINATOR, description="Positive meter denominator"),
]
GroupingPart = Annotated[StrictInt, Field(ge=1, le=MAX_METER_NUMERATOR)]
Grouping = Annotated[
    list[GroupingPart],
    Field(
        min_length=1,
        max_length=MAX_GROUPING_PARTS,
        description="Ordered grouping parts; their sum equals the numerator",
    ),
]
WarningText = Annotated[str, Field(min_length=1, max_length=MAX_WARNING_LENGTH)]


def _validate_grouping(grouping: list[int], numerator: int) -> None:
    if sum(grouping) != numerator:
        raise ValueError(
            f"grouping parts must sum to the meter numerator ({numerator}), got {sum(grouping)}"
        )


def _meter_allowed_tempo_lengths(denominator: int, grouping: list[int]) -> set[Fraction]:
    """Tempo units whose exact length matches a denominator unit or grouping part."""
    allowed = {Fraction(4, denominator)}
    allowed.update(Fraction(part * 4, denominator) for part in grouping)
    return allowed


# --- Analysis run and activation artifact (§3.3-§3.4) -------------------


class RhythmAnalysisRun(BaseModel):
    """One execution of a rhythm model on a project input (§3.3)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    project_id: Uuid
    input_asset_id: Uuid
    input_hash: Sha256Hash
    input_role: RhythmInputRole
    model_manifest_id: str = Field(min_length=1, max_length=128)
    model_manifest_hash: Sha256Hash
    model_preset: BeatModelPreset
    adapter_version: str = Field(min_length=1, max_length=128)
    environment_fingerprint: dict[str, str] = Field(default_factory=dict)
    preprocessing_profile: str = Field(min_length=1, max_length=128)
    preprocessing_version: int = Field(ge=1)
    requested_device: DeviceType
    actual_device: DeviceType | None = None
    device_uuid: str | None = Field(default=None, min_length=1, max_length=128)
    precision: str = Field(default="float32", min_length=1, max_length=32)
    started_at: UtcTimestamp | None = None
    ended_at: UtcTimestamp | None = None
    status: RhythmAnalysisStatus = RhythmAnalysisStatus.QUEUED
    activation_artifact_id: Uuid | None = None
    decoded_result_id: Uuid | None = None
    warnings: list[WarningText] = Field(default_factory=list, max_length=MAX_RUN_WARNINGS)
    runtime_metrics: dict[str, float] = Field(default_factory=dict)
    peak_device_memory_bytes: int | None = Field(default=None, ge=0)
    peak_host_memory_bytes: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_lifecycle(self) -> RhythmAnalysisRun:
        if self.status is RhythmAnalysisStatus.QUEUED:
            if self.started_at is not None:
                raise ValueError("a queued run must not have started_at")
        elif self.status is RhythmAnalysisStatus.RUNNING and self.started_at is None:
            raise ValueError("a running run must have started_at")
        terminal = self.status in {
            RhythmAnalysisStatus.COMPLETED,
            RhythmAnalysisStatus.FAILED,
            RhythmAnalysisStatus.CANCELLED,
            RhythmAnalysisStatus.INTERRUPTED,
        }
        if terminal and self.ended_at is None:
            raise ValueError("a terminal run must have ended_at")
        if not terminal and self.ended_at is not None:
            raise ValueError("only a terminal run may have ended_at")
        if (
            self.started_at is not None
            and self.ended_at is not None
            and self.ended_at < self.started_at
        ):
            raise ValueError("ended_at must not precede started_at")
        if self.status is RhythmAnalysisStatus.COMPLETED:
            if self.activation_artifact_id is None:
                raise ValueError("a completed run must reference its activation artifact")
        else:
            if self.activation_artifact_id is not None:
                raise ValueError("only a completed run may reference an activation artifact")
            if self.decoded_result_id is not None:
                raise ValueError("only a completed run may reference a decoded result")
        if self.actual_device is DeviceType.CUDA:
            if self.device_uuid is None:
                raise ValueError("a cuda run must record its device uuid")
        elif self.device_uuid is not None:
            raise ValueError("a device uuid requires an actual cuda device")
        if self.status is RhythmAnalysisStatus.QUEUED and self.actual_device is not None:
            raise ValueError("a queued run must not have an actual device")
        return self


class ActivationArrayRef(BaseModel):
    """Reference to one immutable `.npy`-compatible activation array."""

    model_config = ConfigDict(frozen=True)

    relative_path: str = Field(min_length=1, max_length=255)
    sha256: Sha256Hash
    element_count: int = Field(ge=0)

    @field_validator("relative_path")
    @classmethod
    def _check_relative_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("activation paths must use '/' separators")
        path = PurePosixPath(value)
        if path.is_absolute():
            raise ValueError("activation paths must be relative")
        if ".." in path.parts:
            raise ValueError("activation paths must not traverse upward")
        if path.suffix != ".npy":
            raise ValueError("activation arrays must be .npy-compatible files")
        return value


class ActivationFrameMapping(BaseModel):
    """Exact model-frame to project-source-frame conversion metadata.

    ``source_frame = model_frame * frame_hop * project_sample_rate /
    model_sample_rate + offset_frames``. The rational part is kept exact
    until the caller needs an integer source frame.
    """

    model_config = ConfigDict(frozen=True)

    model_sample_rate: SampleRate
    project_sample_rate: SampleRate
    frame_hop: int = Field(ge=1)
    offset_frames: int = Field(default=0, ge=-JS_SAFE_INTEGER_MAX, le=JS_SAFE_INTEGER_MAX)

    def source_frame(self, model_frame: int) -> Fraction:
        """Exact project source frame for a model frame index."""
        if model_frame < 0:
            raise ValueError("model frame index must be nonnegative")
        return (
            Fraction(
                model_frame * self.frame_hop * self.project_sample_rate, self.model_sample_rate
            )
            + self.offset_frames
        )


class ActivationArtifactManifest(BaseModel):
    """Metadata for one immutable activation artifact (§3.4).

    The arrays live outside the project JSON; this manifest links them
    and records the exact provenance needed to interpret model frames.
    """

    model_config = ConfigDict(frozen=True)

    artifact_id: Uuid
    content_hash: Sha256Hash
    parent_run_id: Uuid
    source_asset_id: Uuid
    source_hash: Sha256Hash
    model_frame_count: int = Field(ge=0)
    beat: ActivationArrayRef
    downbeat: ActivationArrayRef
    dtype: Literal["float32"] = "float32"
    frame_mapping: ActivationFrameMapping
    preprocessing_transform: dict[str, str | int | float] = Field(default_factory=dict)
    output_semantics: str = Field(min_length=1, max_length=2_000)
    format_version: int = Field(default=ACTIVATION_FORMAT_VERSION, ge=1)

    @model_validator(mode="after")
    def _check_arrays(self) -> ActivationArtifactManifest:
        if self.beat.relative_path == self.downbeat.relative_path:
            raise ValueError("beat and downbeat activations must use distinct files")
        if self.beat.element_count != self.model_frame_count:
            raise ValueError("beat activation length must equal model_frame_count")
        if self.downbeat.element_count != self.model_frame_count:
            raise ValueError("downbeat activation length must equal model_frame_count")
        return self


# --- Pulses, tempo anchors, meter regions (§3.5-§3.7) -------------------


class RhythmPulse(BaseModel):
    """One beat/downbeat-like event in source time (§3.5)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    parent_id: Uuid = Field(
        description="Automatic result ID or edited branch ID that owns this pulse"
    )
    source_frame: SamplePosition
    model_frame_index: int | None = Field(default=None, ge=0)
    role: PulseRole
    acceptance: PulseAcceptance
    confidence: Confidence
    origin: RhythmOrigin
    tempo_anchor_id: Uuid | None = None
    review_state: ReviewState = ReviewState.UNREVIEWED


class TempoAnchor(BaseModel):
    """A control point between source frames and musical positions (§3.6)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    branch_id: Uuid
    source_frame: SamplePosition
    musical_position: MusicalPosition
    lock_state: AnchorLockState = AnchorLockState.UNLOCKED
    origin: RhythmOrigin
    pulse_id: Uuid | None = None
    confidence: Confidence | None = None
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    @model_validator(mode="after")
    def _check_origin_confidence(self) -> TempoAnchor:
        if self.musical_position.is_negative:
            raise ValueError("a tempo anchor musical position must be nonnegative")
        if self.origin is RhythmOrigin.AUTOMATIC and self.confidence is None:
            raise ValueError("an automatic tempo anchor must record its confidence")
        return self


class MeterHypothesis(BaseModel):
    """One candidate meter interpretation for an automatic region (§3.7)."""

    model_config = ConfigDict(frozen=True)

    numerator: MeterNumerator
    denominator: MeterDenominator
    grouping: Grouping
    confidence: Confidence

    @model_validator(mode="after")
    def _check_grouping(self) -> MeterHypothesis:
        _validate_grouping(self.grouping, self.numerator)
        return self


class MeterRegion(BaseModel):
    """A time-signature region anchored in musical position (§3.7).

    ``grouping`` defines the bar's primary pulses: each part is one
    primary-pulse span in denominator units. The ``primary_pulse_starts``
    property derives their offsets instead of storing a second copy.
    """

    model_config = ConfigDict(frozen=True)

    id: Uuid
    branch_id: Uuid
    start: MusicalPosition
    end: MusicalPosition | None = Field(
        default=None,
        description="End position; normally derived from the next region",
    )
    numerator: MeterNumerator
    denominator: MeterDenominator
    grouping: Grouping
    display_tempo_unit: MeterTempoUnit
    confidence: Confidence | None = None
    alternatives: list[MeterHypothesis] = Field(
        default_factory=list, max_length=MAX_METER_ALTERNATIVES
    )
    grid_validity: GridValidity = GridValidity.VALID
    origin: RhythmOrigin
    review_state: ReviewState = ReviewState.UNREVIEWED

    @model_validator(mode="after")
    def _check_region(self) -> MeterRegion:
        if self.start.is_negative:
            raise ValueError("a meter region start must be nonnegative")
        if self.end is not None and compare_musical_positions(self.end, self.start) <= 0:
            raise ValueError("a meter region end must be strictly after its start")
        _validate_grouping(self.grouping, self.numerator)
        unit_length = tempo_unit_quarter_length(self.display_tempo_unit)
        if unit_length not in _meter_allowed_tempo_lengths(self.denominator, self.grouping):
            raise ValueError(
                "display tempo unit is incompatible with the meter denominator/grouping"
            )
        return self

    @property
    def bar_length_quarters(self) -> Fraction:
        """Exact bar length in quarter notes."""
        return Fraction(4 * self.numerator, self.denominator)

    @property
    def primary_pulse_starts(self) -> list[int]:
        """Cumulative denominator-unit offsets where primary pulses begin."""
        starts: list[int] = []
        offset = 0
        for part in self.grouping:
            starts.append(offset)
            offset += part
        return starts


# --- Bar origin, pickup, and editable branch (§3.8-§3.9) ----------------


class BarOriginState(BaseModel):
    """Bar numbering origin and pickup/leading-unmapped state (§3.8)."""

    model_config = ConfigDict(frozen=True)

    first_numbered_bar_position: MusicalPosition = Field(
        description="Musical position of the first numbered bar's downbeat"
    )
    first_bar_number: BarNumber = 1
    pickup: MusicalInterval | None = Field(
        default=None,
        description="Pickup material immediately before the first numbered bar",
    )
    leading_unmapped_interval: HalfOpenInterval | None = Field(
        default=None,
        description="Source interval before a usable musical mapping",
    )

    @model_validator(mode="after")
    def _check_origin(self) -> BarOriginState:
        if self.first_numbered_bar_position.is_negative:
            raise ValueError("the first numbered bar position must be nonnegative")
        if self.pickup is not None:
            if self.pickup.start.is_negative:
                raise ValueError("a pickup must not start before the musical origin")
            if compare_musical_positions(self.pickup.end, self.first_numbered_bar_position) != 0:
                raise ValueError("a pickup must end exactly at the first numbered bar position")
        return self


class RhythmBranchRecord(BaseModel):
    """An editable rhythm grid derived from an automatic result (§3.9).

    The complete branch (pulses, anchors, meter regions) is persisted as
    one record. Source frames remain authoritative for audio; this record
    only adds the musical mapping and notation state.
    """

    model_config = ConfigDict(frozen=True)

    id: Uuid
    project_id: Uuid
    parent_automatic_result_id: Uuid | None = None
    revision: Revision = 0
    source_duration_frames: SamplePosition = Field(
        description="Project duration used to bound tempo anchors"
    )
    pulses: list[RhythmPulse] = Field(default_factory=list, max_length=MAX_PULSES)
    tempo_anchors: list[TempoAnchor] = Field(default_factory=list, max_length=MAX_TEMPO_ANCHORS)
    meter_regions: list[MeterRegion] = Field(default_factory=list, max_length=MAX_METER_REGIONS)
    bar_origin: BarOriginState
    grid_validity: GridValidity
    review_summary: dict[str, int] = Field(default_factory=dict)
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    @model_validator(mode="after")
    def _check_branch(self) -> RhythmBranchRecord:
        self._check_unique_ids()
        self._check_pulses()
        self._check_tempo_anchors()
        self._check_meter_regions()
        self._check_grid_validity()
        return self

    def _check_unique_ids(self) -> None:
        for name, ids in (
            ("pulse", [pulse.id for pulse in self.pulses]),
            ("tempo anchor", [anchor.id for anchor in self.tempo_anchors]),
            ("meter region", [region.id for region in self.meter_regions]),
        ):
            if len(set(ids)) != len(ids):
                raise ValueError(f"duplicate {name} id in one rhythm branch")

    def _check_pulses(self) -> None:
        allowed_parents = {self.id}
        if self.parent_automatic_result_id is not None:
            allowed_parents.add(self.parent_automatic_result_id)
        anchor_ids = {anchor.id for anchor in self.tempo_anchors}
        for pulse in self.pulses:
            if pulse.parent_id not in allowed_parents:
                raise ValueError("each pulse's parent must be this branch or its automatic result")
            if pulse.tempo_anchor_id is not None and pulse.tempo_anchor_id not in anchor_ids:
                raise ValueError("a pulse may only link to a tempo anchor in this branch")

    def _check_tempo_anchors(self) -> None:
        pulse_ids = {pulse.id for pulse in self.pulses}
        previous_source: int | None = None
        previous_musical: MusicalPosition | None = None
        for anchor in self.tempo_anchors:
            if anchor.branch_id != self.id:
                raise ValueError("a tempo anchor must belong to the branch it is stored in")
            if anchor.source_frame > self.source_duration_frames:
                raise ValueError("a tempo anchor lies outside the project source bounds")
            if previous_source is not None and anchor.source_frame <= previous_source:
                raise ValueError("tempo anchor source positions must strictly increase")
            if previous_musical is not None and (
                compare_musical_positions(anchor.musical_position, previous_musical) <= 0
            ):
                raise ValueError("tempo anchor musical positions must strictly increase")
            if anchor.pulse_id is not None and anchor.pulse_id not in pulse_ids:
                raise ValueError("a tempo anchor may only link to a pulse in this branch")
            previous_source = anchor.source_frame
            previous_musical = anchor.musical_position

    def _check_meter_regions(self) -> None:
        previous: MeterRegion | None = None
        for region in self.meter_regions:
            if region.branch_id != self.id:
                raise ValueError("a meter region must belong to the branch it is stored in")
            if previous is not None:
                if compare_musical_positions(region.start, previous.start) <= 0:
                    raise ValueError("meter regions must be strictly ordered")
                if previous.end is not None and (
                    compare_musical_positions(previous.end, region.start) != 0
                ):
                    raise ValueError(
                        "a meter region's stored end must equal the next region's start"
                    )
                delta = region.start.as_quarter_notes() - previous.start.as_quarter_notes()
                bars = delta / previous.bar_length_quarters
                if bars.denominator != 1:
                    raise ValueError(
                        "a meter region must begin on a whole bar boundary of the preceding meter"
                    )
            previous = region

    def _check_grid_validity(self) -> None:
        if self.grid_validity is GridValidity.VALID:
            if not self.tempo_anchors:
                raise ValueError("a valid grid requires at least one tempo anchor")
            if not self.meter_regions:
                raise ValueError("a valid grid requires at least one meter region")


# --- Project-level rhythm state (§3.10) ----------------------------------


class SelectedRhythmObject(BaseModel):
    """The last selected rhythm object, for editor restoration."""

    model_config = ConfigDict(frozen=True)

    kind: SelectedRhythmObjectKind
    id: Uuid


class MetronomeSettings(BaseModel):
    """Metronome preferences; audio behavior is implemented in M3.14."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    volume: float = Field(default=0.5, ge=0.0, le=MAX_METRONOME_VOLUME)
    accent_downbeats: bool = True
    subdivision: MetronomeSubdivision = MetronomeSubdivision.PRIMARY


class CountInSettings(BaseModel):
    """Count-in preferences; transport behavior is implemented in M3.15."""

    model_config = ConfigDict(frozen=True)

    mode: CountInMode = CountInMode.OFF
    repetition: CountInRepetition = CountInRepetition.ONCE


class ProjectRhythmState(BaseModel):
    """Project-level rhythm display and practice settings (§3.10)."""

    model_config = ConfigDict(frozen=True)

    active_automatic_result_id: Uuid | None = None
    active_branch_id: Uuid | None = None
    display_mode: RhythmDisplayMode = RhythmDisplayMode.AUTOMATIC
    lane_visible: bool = True
    lane_height: float = Field(default=1.0, ge=MIN_RHYTHM_LANE_HEIGHT, le=MAX_RHYTHM_LANE_HEIGHT)
    ruler_visible: bool = True
    snap_mode: SnapMode = SnapMode.BEAT
    metronome: MetronomeSettings = Field(default_factory=MetronomeSettings)
    count_in: CountInSettings = Field(default_factory=CountInSettings)
    last_selected: SelectedRhythmObject | None = None

    @model_validator(mode="after")
    def _check_display(self) -> ProjectRhythmState:
        if self.display_mode is RhythmDisplayMode.EDITED and self.active_branch_id is None:
            raise ValueError("the edited display mode requires an active rhythm branch")
        return self
