"""Project record schema (M0.4, extended M1.1).

An empty project is a valid, persisted state. All source fields
(sample_rate, duration_frames, channel count/layout, stream index,
decode profile, asset references) are present together or all null.

Import-job state is deliberately separate from project source
readiness: a project may have usable canonical audio while waveform
generation is still running (``waveform_status == "pending"``).
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from basseparate import PROJECT_SCHEMA_VERSION
from basseparate.domain.common import Revision, SamplePosition, SampleRate, UtcTimestamp, Uuid
from basseparate.domain.marker import MarkerRecord
from basseparate.domain.practice import PracticeState
from basseparate.domain.rhythm import ProjectRhythmState

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

NameStr = str

MAX_CHANNEL_COUNT = 8
MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 192_000


class ProjectStatus(StrEnum):
    EMPTY = "empty"
    READY = "ready"


class WaveformStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"
    READY = "ready"


def _validate_name(name: str) -> str:
    trimmed = name.strip()
    if not 1 <= len(trimmed) <= 200:
        raise ValueError(
            f"project name must be 1-200 characters after trimming, got {len(trimmed)}"
        )
    if _CONTROL_CHAR_RE.search(trimmed):
        raise ValueError("project name must not contain embedded control characters")
    return trimmed


class SelectionRange(BaseModel):
    """A frame selection ``[start, end)`` in source frames (M1.15 §17.5)."""

    model_config = ConfigDict(frozen=True)

    start: SamplePosition
    end: SamplePosition

    def model_post_init(self, __context: object) -> None:
        if self.end < self.start:
            raise ValueError("selection end must be >= selection start")


class ViewportState(BaseModel):
    """A persisted editor viewport, width-free (M1.15 §17.5)."""

    model_config = ConfigDict(frozen=True)

    start_frame: SamplePosition
    frames_per_css_pixel: float = Field(gt=0)


class ChannelDisplay(BaseModel):
    """Channel display (amplitude) settings (M1.15 §17.5).

    ``scales`` are per-channel display amplitudes (editor range
    0.25-16); at most one entry per source channel.
    """

    model_config = ConfigDict(frozen=True)

    linked: bool = True
    scales: list[float] = Field(default_factory=list, max_length=MAX_CHANNEL_COUNT)

    @field_validator("scales")
    @classmethod
    def _validate_scales(cls, v: list[float]) -> list[float]:
        for scale in v:
            if not 0.25 <= scale <= 16.0:
                raise ValueError(f"channel scale {scale} is outside 0.25-16")
        return v


class WorkingState(BaseModel):
    """Per-project working state persisted by autosave (M1.15 §17.5).

    Frame-valued fields are validated against the project's
    ``duration_frames`` by ``ProjectRecord``.
    """

    model_config = ConfigDict(frozen=True)

    selection: SelectionRange | None = None
    viewport: ViewportState | None = None
    channel_display: ChannelDisplay = Field(default_factory=ChannelDisplay)
    monitoring_volume: float = Field(default=1.0, ge=0.0, le=2.0)
    last_position_frames: SamplePosition = 0
    follow_playhead: bool = True


class ProjectRecord(BaseModel):
    """A persisted working project.

    An empty project has ``status == "empty"`` and all source fields
    null. A ready project has the original-file asset, the canonical
    PCM asset, and complete source timing/channel metadata.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=False)

    schema_version: int = Field(
        default=PROJECT_SCHEMA_VERSION,
        ge=1,
        description="Project schema version",
    )
    id: Uuid
    name: NameStr = Field(min_length=1, max_length=200)
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    revision: Revision = Field(default=0)
    status: ProjectStatus = ProjectStatus.EMPTY

    # Source readiness (all present together or all null).
    source_asset_id: Uuid | None = None
    canonical_asset_id: Uuid | None = None
    monitoring_asset_id: Uuid | None = None
    #: User-selected left/right source channels for monitoring when the
    #: source layout is unknown (M1.7, milestone1.md §9.3). Present
    #: together; null when the layout uses the standard matrix or no
    #: selection has been made.
    monitoring_left_channel: int | None = Field(default=None, ge=0, le=MAX_CHANNEL_COUNT - 1)
    monitoring_right_channel: int | None = Field(default=None, ge=0, le=MAX_CHANNEL_COUNT - 1)
    source_stream_index: int | None = Field(default=None, ge=0)
    sample_rate: SampleRate | None = Field(
        default=None,
        description="Selected source stream sample rate in Hz",
    )
    duration_frames: SamplePosition | None = Field(
        default=None,
        description="Decoded frame count of the canonical audio (authoritative)",
    )
    source_channel_count: int | None = Field(default=None, ge=1, le=MAX_CHANNEL_COUNT)
    source_channel_layout: str | None = Field(default=None, min_length=1, max_length=64)
    decode_profile_version: int | None = Field(default=None, ge=1)
    waveform_status: WaveformStatus = WaveformStatus.NONE
    source_metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Source metadata summary (format, title, artist, ...)",
    )

    # Markers and working state (M1.15, milestone1.md §17).
    markers: list[MarkerRecord] = Field(default_factory=list)
    working_state: WorkingState = Field(default_factory=WorkingState)
    #: Mixer and practice state (M2.1, milestone2.md §3.5). Defaulted so
    #: pre-M2 projects deserialize unchanged.
    practice_state: PracticeState = Field(default_factory=PracticeState)
    #: Musical-grid display and practice settings (M3.1, milestone3.md
    #: §3.10). Defaulted so pre-M3 projects deserialize unchanged.
    rhythm_state: ProjectRhythmState = Field(default_factory=ProjectRhythmState)
    #: Undo/redo availability, computed by the repository on read
    #: (M1.15 §17.4); not stored, defaults to "none available".
    can_undo: bool = False
    can_redo: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def _trim_and_validate_name(cls, v: str) -> str:
        return _validate_name(v)

    def model_post_init(self, __context: object) -> None:
        self._check_source_fields_together()
        self._check_status_consistency()
        self._check_sample_rate_bounds()
        self._check_markers_and_working_state()

    def _check_source_fields_together(self) -> None:
        optional_source_fields: tuple[object, ...] = (
            self.source_asset_id,
            self.canonical_asset_id,
            self.source_stream_index,
            self.sample_rate,
            self.duration_frames,
            self.source_channel_count,
            self.source_channel_layout,
            self.decode_profile_version,
        )
        present = [f is not None for f in optional_source_fields]
        if any(present) and not all(present):
            missing = [
                name
                for name, value in zip(
                    (
                        "source_asset_id",
                        "canonical_asset_id",
                        "source_stream_index",
                        "sample_rate",
                        "duration_frames",
                        "source_channel_count",
                        "source_channel_layout",
                        "decode_profile_version",
                    ),
                    optional_source_fields,
                    strict=True,
                )
                if value is None
            ]
            raise ValueError(
                "all source fields must be present together or all null; missing: "
                + ", ".join(missing)
            )
        if self.monitoring_asset_id is not None and self.canonical_asset_id is None:
            raise ValueError("monitoring_asset_id requires canonical_asset_id")
        monitoring_channels = (self.monitoring_left_channel, self.monitoring_right_channel)
        if any(c is not None for c in monitoring_channels) and not all(
            c is not None for c in monitoring_channels
        ):
            raise ValueError(
                "monitoring_left_channel and monitoring_right_channel must be "
                "present together or both null"
            )
        if any(c is not None for c in monitoring_channels) and self.source_channel_count is None:
            raise ValueError("monitoring channel selection requires a source channel count")
        for column, channel in zip(
            ("monitoring_left_channel", "monitoring_right_channel"),
            monitoring_channels,
            strict=True,
        ):
            if (
                channel is not None
                and self.source_channel_count is not None
                and channel >= self.source_channel_count
            ):
                raise ValueError(
                    f"{column} {channel} is outside the source's "
                    f"{self.source_channel_count} channels"
                )
        if self.waveform_status != WaveformStatus.NONE and self.canonical_asset_id is None:
            raise ValueError("waveform_status requires canonical_asset_id")

    def _check_status_consistency(self) -> None:
        if self.status == ProjectStatus.READY and self.source_asset_id is None:
            raise ValueError("a ready project must have source and canonical assets")
        if self.status == ProjectStatus.EMPTY and self.source_asset_id is not None:
            raise ValueError("an empty project must not have source fields")

    def _check_sample_rate_bounds(self) -> None:
        if self.sample_rate is not None and not (
            MIN_SAMPLE_RATE <= self.sample_rate <= MAX_SAMPLE_RATE
        ):
            raise ValueError(
                f"source sample rate {self.sample_rate} Hz is outside the supported "
                f"range {MIN_SAMPLE_RATE}-{MAX_SAMPLE_RATE} Hz"
            )

    def _check_markers_and_working_state(self) -> None:
        if self.status == ProjectStatus.EMPTY and self.markers:
            raise ValueError("an empty project must not have markers")
        duration = self.duration_frames
        if duration is None:
            return
        for marker in self.markers:
            if marker.project_id != self.id:
                raise ValueError(f"marker {marker.id} belongs to another project")
            if marker.position_frames > duration:
                raise ValueError(
                    f"marker {marker.id} at frame {marker.position_frames} exceeds "
                    f"the project duration {duration}"
                )
        state = self.working_state
        if state.last_position_frames > duration:
            raise ValueError(
                f"working-state position {state.last_position_frames} exceeds the "
                f"project duration {duration}"
            )
        if state.selection is not None and state.selection.end > duration:
            raise ValueError(
                f"selection end {state.selection.end} exceeds the project duration "
                f"{duration}"
            )
        if state.viewport is not None and state.viewport.start_frame > duration:
            raise ValueError(
                f"viewport start {state.viewport.start_frame} exceeds the project "
                f"duration {duration}"
            )
