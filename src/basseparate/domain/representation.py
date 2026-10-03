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


class MonitoringDownmixResult(BaseModel):
    """Validated outcome of a monitoring downmix to stereo (M1.7).

    The staged PCM file at ``staging_pcm_path`` holds ``pcm_byte_count``
    bytes of interleaved little-endian float32 stereo. The publisher moves
    it into the content-addressed asset store.
    """

    model_config = ConfigDict(frozen=True)

    frame_count: int = Field(ge=1, description="Output sample frames (stereo)")
    sample_rate: SampleRate
    channel_count: int = Field(default=2, ge=2, le=2)
    content_hash: Sha256Hash
    max_amplitude: float = Field(ge=0.0, description="Max absolute sample value (may exceed 1.0)")
    pcm_byte_count: int = Field(ge=4)
    source_frame_count: int = Field(ge=1)
    downmix_mode: Literal["standard_5_1", "manual"]
    #: The effective left/right source channels (0/1 FL/FR for standard 5.1,
    #: the user selection for manual mode).
    left_channel: int = Field(ge=0, le=7)
    right_channel: int = Field(ge=0, le=7)
    ffmpeg_version: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(default=1, ge=1, description="Downmix profile version")
    staging_pcm_path: str = Field(min_length=1, description="Absolute path of the staged PCM")


class PlaybackRateResult(BaseModel):
    """Validated outcome of a playback-rate conversion (M1.7).

    The staged PCM file at ``staging_pcm_path`` holds ``pcm_byte_count``
    bytes of interleaved little-endian float32 at ``sample_rate``.
    """

    model_config = ConfigDict(frozen=True)

    frame_count: int = Field(ge=1, description="Output sample frames")
    sample_rate: SampleRate = Field(description="Target (playback) sample rate in Hz")
    channel_count: int = Field(ge=1, le=8)
    content_hash: Sha256Hash
    max_amplitude: float = Field(ge=0.0, description="Max absolute sample value (may exceed 1.0)")
    pcm_byte_count: int = Field(ge=4)
    source_frame_count: int = Field(ge=1)
    source_sample_rate: SampleRate
    target_sample_rate: SampleRate
    expected_frame_count: int = Field(
        ge=1,
        description="round(source_frame_count × target / source)",
    )
    endpoint_difference_frames: int = Field(
        description="actual minus expected; rational-rounding residue (spec §9.6.5)"
    )
    ffmpeg_version: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(default=1, ge=1, description="Resampler profile version")
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


def compute_downmix_key(
    source_sha256: Sha256Hash,
    mode: str,
    left_channel: int,
    right_channel: int,
    left_matrix: list[tuple[int, float]],
    right_matrix: list[tuple[int, float]],
    matrix_version: int,
    profile_version: int,
    ffmpeg_version: str,
) -> Sha256Hash:
    """v2 monitoring-downmix transform key (M1.7).

    Identifies the transformation: input hash + downmix matrix (channel
    indices and coefficients) + implementation versions (spec §8.2, §9.3).
    """
    document = {
        "v": 2,
        "kind": "monitoring_downmix",
        "source_sha256": source_sha256,
        "mode": mode,
        "left_channel": left_channel,
        "right_channel": right_channel,
        "matrix": {
            "L": [[ch, coef] for ch, coef in left_matrix],
            "R": [[ch, coef] for ch, coef in right_matrix],
        },
        "matrix_version": matrix_version,
        "profile_version": profile_version,
        "ffmpeg_version": ffmpeg_version,
        "sample_format": "f32le",
    }
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_playback_key(
    source_sha256: Sha256Hash,
    source_sample_rate: int,
    target_sample_rate: int,
    profile_version: int,
    ffmpeg_version: str,
) -> Sha256Hash:
    """v2 playback-rate transform key (M1.7).

    Identifies the transformation: input hash + rate pair + the versioned
    SWR resampler profile (spec §8.2, §9.5).
    """
    document = {
        "v": 2,
        "kind": "playback_rate",
        "source_sha256": source_sha256,
        "source_sample_rate": source_sample_rate,
        "target_sample_rate": target_sample_rate,
        "resampler": "swr",
        "filter_size": 64,
        "exact_rational": True,
        "dither": "none",
        "async": "none",
        "profile_version": profile_version,
        "ffmpeg_version": ffmpeg_version,
        "sample_format": "f32le",
    }
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
