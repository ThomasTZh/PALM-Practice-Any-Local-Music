"""Audio representation metadata (M1.1).

A *representation* is a decoded or derived PCM asset tied to a parent
asset. The canonical representation preserves the selected source
stream's sample rate and channels. Derived representations (monitoring
downmix, playback-rate conversion) record their transform identity and
time mapping so they can be validated and deduplicated.

Milestone 1 encodings are fixed: interleaved little-endian float32.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from basseparate.domain.common import (
    SamplePosition,
    SampleRate,
    Sha256Hash,
    UtcTimestamp,
    Uuid,
)


class RepresentationRole(StrEnum):
    CANONICAL = "canonical"
    MONITORING_DOWNMIX = "monitoring_downmix"
    PLAYBACK_RATE = "playback_rate"


PcmEncoding = Literal["f32le"]
Interleaving = Literal["interleaved"]


class TimeMapping(BaseModel):
    """Maps representation frames to project (source) frames.

    ``project_position = representation_frame × project_rate
    / representation_rate``. Fractional positions are retained
    internally; rounding happens only at readout/edit boundaries.
    """

    model_config = ConfigDict(frozen=True)

    project_rate: SampleRate = Field(description="Sample rate defining project time")
    representation_rate: SampleRate = Field(description="Sample rate of this representation")


class RepresentationProvenance(BaseModel):
    """Decoder/resampler identity for a representation."""

    model_config = ConfigDict(frozen=True)

    tool: str = Field(min_length=1, max_length=64, description="e.g. 'ffmpeg'")
    tool_version: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(ge=1, description="Decode/resampler profile version")
    created_at: UtcTimestamp


class AudioRepresentation(BaseModel):
    """Metadata for one decoded or derived PCM asset."""

    model_config = ConfigDict(frozen=True)

    asset_id: Uuid
    parent_asset_id: Uuid | None = Field(
        default=None,
        description="Asset this representation was derived from (original file "
        "for canonical, canonical for derived)",
    )
    role: RepresentationRole
    sample_rate: SampleRate
    channel_count: int = Field(ge=1, le=8)
    channel_layout: str | None = Field(default=None, min_length=1, max_length=64)
    frame_count: SamplePosition
    encoding: PcmEncoding = "f32le"
    interleaving: Interleaving = "interleaved"
    content_hash: Sha256Hash
    transform_key: Sha256Hash = Field(
        description="Hash of input hash + stream + parameters + implementation versions"
    )
    time_mapping: TimeMapping
    provenance: RepresentationProvenance

    @property
    def is_identity(self) -> bool:
        return self.time_mapping.project_rate == self.time_mapping.representation_rate
