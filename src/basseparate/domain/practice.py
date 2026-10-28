"""Mixer and practice state (M2.1, milestone2.md §3.5).

Per-project state for the practice workflow: which source the transport
plays (original mix vs. separated stems), the active separation result set,
per-track mixer settings, master/monitoring gain, playback speed, and saved
practice loops. Persisted on the project record so it survives restarts and
is carried by portable projects.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from basseparate.domain.common import Revision, SamplePosition, UtcTimestamp, Uuid
from basseparate.domain.rhythm import LoopAnchorMode, MusicalPosition
from basseparate.domain.separation import StemRole

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_LOOP_NAME_LENGTH = 80

#: Upper bound on a project's Song Map sections.
MAX_SECTIONS = 500

#: Default loop color (M2.11, spec §13.1): amber, distinct from the
#: marker default (rose).
DEFAULT_LOOP_COLOR = "#f59e0b"

#: Repeat-count bounds (spec §13.1): ``None`` means infinite; a finite
#: count is the total number of passes.
MAX_LOOP_REPEAT = 9999

#: Shortest interval that may be *repeated* for practice (spec §13.3.3).
#: Shorter loops can be saved (and auditioned) but not enabled.
MIN_REPEATABLE_LOOP_SECONDS = 0.1

#: Playback speed bounds (spec §2, §11.6): 0.25x to 2.0x, pitch preserved.
MIN_PLAYBACK_SPEED = 0.25
MAX_PLAYBACK_SPEED = 2.0

#: Master gain and per-track gain bounds: 0.0 (exact silence is ``mute``,
#: §10.3.3) to +12 dB (10^(12/20), §10.3.2).
MAX_GAIN = 10.0 ** (12.0 / 20.0)

#: Per-track display height bounds (editor range).
MIN_DISPLAY_HEIGHT = 0.25
MAX_DISPLAY_HEIGHT = 2.0


def _validate_loop_name(name: str) -> str:
    trimmed = name.strip()
    if not 1 <= len(trimmed) <= MAX_LOOP_NAME_LENGTH:
        raise ValueError(
            f"loop name must be 1-{MAX_LOOP_NAME_LENGTH} characters "
            f"after trimming, got {len(trimmed)}"
        )
    if _CONTROL_CHAR_RE.search(trimmed):
        raise ValueError("loop name must not contain embedded control characters")
    return trimmed


class SongSection(BaseModel):
    """A named, non-overlapping Song Map section in source frames.

    Sections are ordered by ``start_frames`` in ``PracticeState``. The
    source-frame bounds are authoritative; display seconds are derived.
    """

    model_config = ConfigDict(frozen=True)

    id: Uuid
    name: str = Field(min_length=1, max_length=MAX_LOOP_NAME_LENGTH)
    start_frames: SamplePosition
    end_frames: SamplePosition
    color: str = Field(default="#22c55e", pattern=r"^#[0-9a-fA-F]{6}$")
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, v: str) -> str:
        return _validate_loop_name(v)

    def model_post_init(self, __context: object) -> None:
        if self.end_frames <= self.start_frames:
            raise ValueError("section end_frames must be strictly greater than start_frames")


class PlaybackMode(StrEnum):
    """Which source the transport plays (spec §3.5)."""

    ORIGINAL = "original"
    BASS_PAIR = "bass_pair"
    FOUR_STEMS = "four_stems"


#: Modes that require an active separation result set.
_STEM_MODES = frozenset({PlaybackMode.BASS_PAIR, PlaybackMode.FOUR_STEMS})


class TrackSettings(BaseModel):
    """Mixer settings for one stem track (spec §3.5)."""

    model_config = ConfigDict(frozen=True)

    gain: float = Field(default=1.0, ge=0.0, le=MAX_GAIN)
    mute: bool = False
    solo: bool = False
    balance: float = Field(default=0.0, ge=-1.0, le=1.0)
    visible: bool = True
    display_height: float = Field(default=1.0, ge=MIN_DISPLAY_HEIGHT, le=MAX_DISPLAY_HEIGHT)
    #: Track color (spec §10.2). The domain is palette-agnostic: the
    #: frontend applies the role-palette color as the displayed initial
    #: value.
    color: str = Field(default="#8fa3bf", pattern=r"^#[0-9a-fA-F]{6}$")


class PracticeLoop(BaseModel):
    """A saved practice loop with integer source-frame boundaries (spec §13.1).

    ``repeat_count`` is the total number of passes (not "extra repeats");
    ``None`` means infinite. ``boundary_fade`` enables the short output
    fades at the join (§13.6); disabling them gives exact boundary
    audition. The boundaries are exact source frames and are never
    expanded (§13.3.5–6).
    """

    model_config = ConfigDict(frozen=True)

    id: Uuid
    name: str = Field(min_length=1, max_length=MAX_LOOP_NAME_LENGTH)
    start_frames: SamplePosition
    end_frames: SamplePosition
    color: str = Field(default=DEFAULT_LOOP_COLOR, pattern=r"^#[0-9a-fA-F]{6}$")
    repeat_count: int | None = Field(default=None, ge=1, le=MAX_LOOP_REPEAT)
    boundary_fade: bool = True
    #: M3.13: source-anchored (default) or musical-grid anchored.
    anchor_mode: LoopAnchorMode = LoopAnchorMode.SOURCE
    start_musical: MusicalPosition | None = None
    end_musical: MusicalPosition | None = None
    #: Last resolution through the active branch; cached, never authoritative
    #: in musical mode.
    resolved_source_start: SamplePosition | None = None
    resolved_source_end: SamplePosition | None = None
    grid_branch_id: Uuid | None = None
    grid_branch_revision: Revision | None = None
    unresolved: bool = False
    #: Linked Song Map section for a section loop. Optional: pre-M4
    #: loops and free-form loops have no section.
    section_id: Uuid | None = None
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, v: str) -> str:
        return _validate_loop_name(v)

    def model_post_init(self, __context: object) -> None:
        if self.end_frames <= self.start_frames:
            raise ValueError("loop end_frames must be strictly greater than start_frames")
        if (self.start_musical is None) != (self.end_musical is None):
            raise ValueError("loop musical boundaries must be present together")
        if self.start_musical is not None and self.end_musical is not None and (
            self.end_musical.numerator * self.start_musical.denominator
            <= self.start_musical.numerator * self.end_musical.denominator
        ):
            raise ValueError("loop end_musical must be after start_musical")
        if self.anchor_mode is LoopAnchorMode.MUSICAL and (
            self.start_musical is None or self.end_musical is None
        ):
            raise ValueError("a musical loop needs musical start and end")
        if (self.resolved_source_start is None) != (self.resolved_source_end is None):
            raise ValueError("resolved source boundaries must be present together")
        if (
            self.resolved_source_start is not None
            and self.resolved_source_end is not None
            and self.resolved_source_end <= self.resolved_source_start
        ):
            raise ValueError("resolved loop end must be after its start")


class PracticeState(BaseModel):
    """Per-project mixer and practice state (spec §3.5).

    ``tracks`` is keyed by stem role value (``StemRole``). Stem playback
    modes require an active result set; ``original`` plays the source mix
    and may still remember the last result set.
    """

    model_config = ConfigDict(frozen=True)

    playback_mode: PlaybackMode = PlaybackMode.ORIGINAL
    active_result_set_id: Uuid | None = None
    tracks: dict[str, TrackSettings] = Field(default_factory=dict, max_length=8)
    master_gain: float = Field(default=1.0, ge=0.0, le=MAX_GAIN)
    #: Monitoring-path limiter, on by default (spec §10.6.3). Monitoring
    #: only: it never touches stored samples.
    monitoring_limiter: bool = True
    playback_speed: float = Field(
        default=1.0, ge=MIN_PLAYBACK_SPEED, le=MAX_PLAYBACK_SPEED
    )
    loops: list[PracticeLoop] = Field(default_factory=list)
    active_loop_id: Uuid | None = None
    loop_enabled: bool = False
    sections: list[SongSection] = Field(default_factory=list, max_length=MAX_SECTIONS)
    active_section_id: Uuid | None = None

    @field_validator("tracks")
    @classmethod
    def _validate_track_keys(cls, v: dict[str, TrackSettings]) -> dict[str, TrackSettings]:
        role_values = {role.value for role in StemRole}
        for key in v:
            if key not in role_values:
                raise ValueError(f"track key {key!r} is not a stem role")
        return v

    @field_validator("sections")
    @classmethod
    def _validate_sections(cls, v: list[SongSection]) -> list[SongSection]:
        previous_end: int | None = None
        for section in v:
            if previous_end is not None and section.start_frames < previous_end:
                raise ValueError("sections must be in order and must not overlap")
            previous_end = section.end_frames
        return v

    @model_validator(mode="after")
    def _check_mode_and_loop(self) -> PracticeState:
        if self.playback_mode in _STEM_MODES and self.active_result_set_id is None:
            raise ValueError(
                f"{self.playback_mode.value} mode requires an active result set"
            )
        if self.active_loop_id is not None and not any(
            loop.id == self.active_loop_id for loop in self.loops
        ):
            raise ValueError("active_loop_id must reference an existing loop")
        if self.loop_enabled and self.active_loop_id is None:
            raise ValueError("loop_enabled requires an active loop")
        section_ids = {section.id for section in self.sections}
        if self.active_section_id is not None and self.active_section_id not in section_ids:
            raise ValueError("active_section_id must reference an existing section")
        for loop in self.loops:
            if loop.section_id is not None and loop.section_id not in section_ids:
                raise ValueError("loop section_id must reference an existing section")
        return self
