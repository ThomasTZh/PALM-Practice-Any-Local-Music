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

    @field_validator("name", mode="before")
    @classmethod
    def _trim_and_validate_name(cls, v: str) -> str:
        return _validate_name(v)

    def model_post_init(self, __context: object) -> None:
        self._check_source_fields_together()
        self._check_status_consistency()
        self._check_sample_rate_bounds()

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
