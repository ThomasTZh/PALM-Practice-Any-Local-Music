"""Audio representation metadata (M1.1).

A *representation* is a decoded or derived PCM asset tied to a parent
asset. The canonical representation preserves the selected source
stream's sample rate and channels. Derived representations (monitoring
downmix, playback-rate conversion) record their transform identity and
time mapping so they can be validated and deduplicated.

Milestone 1 encodings are fixed: interleaved little-endian float32.
"""

from __future__ import annotations

import hashlib
import json
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


class CanonicalDecodeResult(BaseModel):
    """Validated outcome of decoding the selected stream to canonical PCM (M1.5).

    The staged PCM file at ``staging_pcm_path`` holds ``pcm_byte_count`` bytes
    of interleaved little-endian float32. The publisher moves it into the
    content-addressed asset store.
    """

    model_config = ConfigDict(frozen=True)

    frame_count: int = Field(ge=1, description="Decoded sample frames (all channels)")
    sample_rate: SampleRate
    channel_count: int = Field(ge=1, le=8)
    channel_layout: str | None = Field(default=None, min_length=1, max_length=64)
    content_hash: Sha256Hash
    max_amplitude: float = Field(ge=0.0, description="Max absolute sample value (may exceed 1.0)")
    pcm_byte_count: int = Field(ge=4)
    decoded_duration_seconds: float = Field(ge=0.0)
    estimated_duration_seconds: float | None = Field(default=None, ge=0.0)
    duration_discrepancy_seconds: float | None = Field(
        default=None, description="decoded minus estimated; None when unknown"
    )
    source_start_timestamp_seconds: float | None = Field(default=None, ge=0.0)
    decoder_warnings: tuple[str, ...] = Field(
        default=(), description="Decoder warning lines (truncated media is never silent)"
    )
    timing_repair_warnings: tuple[str, ...] = Field(
        default=(), description="Gap-padding/overlap-trim repair notices"
    )
    ffmpeg_version: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(default=1, ge=1, description="Decode profile version")
    staging_pcm_path: str = Field(min_length=1, description="Absolute path of the staged PCM")


def compute_transform_key(
    source_sha256: Sha256Hash,
    stream_index: int,
    profile_version: int,
    ffmpeg_version: str,
) -> Sha256Hash:
    """v1 canonical-decode transform key (M1.5).

    SHA-256 over a canonical JSON document identifying the transformation.
    M1.6 formalizes the full key content and the dedup policy; the layout is
    chosen now so M1.5 assets are already content-addressed.
    """
    document = {
        "v": 1,
        "source_sha256": source_sha256,
        "stream_index": stream_index,
        "profile_version": profile_version,
        "ffmpeg_version": ffmpeg_version,
        "sample_format": "f32le",
        "channel_policy": "preserve",
        "timestamp_policy": "decoder-default",
        "resample_policy": "async-fill-trim",
    }
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
