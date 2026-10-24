"""Rhythm-analysis input records (M3.3, milestone3.md §5).

A rhythm input plan records which project asset is analysed, in which
role (original mix or drum stem), and which explicit downmix applies for
a multichannel source. The audio itself is transformed into the pinned
Beat This! representation: 22,050 Hz, stereo PCM (the adapter averages
the two prepared channels to mono), no amplitude normalization, and the
upstream long-track chunk/aggregate strategy.

Source frames remain authoritative. The prepared representation only
adds a sample-rate mapping and a deterministic transformation identity
for caching.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import SampleRate, Sha256Hash, Uuid
from basseparate.domain.preparation import DownmixSpec
from basseparate.domain.rhythm import RhythmInputRole

#: Versioned recipe name recorded in the transform/cache key.
RHYTHM_INPUT_RECIPE = "rhythm-input-v1"

#: Version of the prepared-input profile.
RHYTHM_INPUT_PROFILE_VERSION = 1

#: Beat This! LogMelSpect geometry (pinned upstream, M3.2 registry).
BEAT_THIS_INPUT_SAMPLE_RATE = 22_050
BEAT_THIS_FRAME_HOP = 441
BEAT_THIS_FRAME_RATE = 50.0

#: The prepared representation keeps two channels so the adapter's own
#: documented channel mean is the only channel transform.
BEAT_THIS_PREPARED_CHANNELS = 2

#: Upstream long-track strategy: Spect2Frames split_predict_aggregate.
BEAT_THIS_LONG_TRACK_CHUNK_FRAMES = 1_500
BEAT_THIS_LONG_TRACK_BORDER_FRAMES = 6


class RhythmInputPlan(BaseModel):
    """One reproducible rhythm-analysis input selection (§5.1, §5.7)."""

    model_config = ConfigDict(frozen=True)

    input_role: RhythmInputRole
    asset_id: Uuid
    source_hash: Sha256Hash
    sample_rate: SampleRate
    channel_count: int = Field(ge=1, le=8)
    downmix: DownmixSpec | None = Field(
        default=None,
        description="Explicit M1 stereo downmix for a multichannel source",
    )
    model_id: str = Field(min_length=1, max_length=128)
    model_manifest_hash: Sha256Hash
    adapter_version: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _check_downmix(self) -> RhythmInputPlan:
        if self.channel_count > 2 and self.downmix is None:
            raise ValueError(
                "a multichannel rhythm input requires an explicit downmix spec"
            )
        if self.channel_count <= 2 and self.downmix is not None:
            raise ValueError("mono and stereo rhythm inputs must not carry a downmix")
        return self


class RhythmInputProfile(BaseModel):
    """The pinned model-input transform (§5.3, §5.5)."""

    model_config = ConfigDict(frozen=True)

    profile_version: int = Field(ge=1)
    recipe: str = Field(min_length=1, max_length=64)
    model_sample_rate: SampleRate
    prepared_channels: int = Field(ge=1, le=2)
    channel_transform: Literal["adapter_mean_over_prepared_channels"]
    amplitude_transform: Literal["none"]
    resampler_profile_version: int = Field(ge=1)
    frame_hop: int = Field(ge=1)
    frame_rate: float = Field(gt=0.0)
    long_track_strategy: Literal["upstream_split_predict_aggregate"]
    long_track_chunk_frames: int = Field(ge=1)
    long_track_border_frames: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_geometry(self) -> RhythmInputProfile:
        expected = self.model_sample_rate / self.frame_hop
        if abs(expected - self.frame_rate) > 1e-9:
            raise ValueError("frame_rate must equal model_sample_rate / frame_hop")
        return self


BEAT_THIS_INPUT_PROFILE = RhythmInputProfile(
    profile_version=RHYTHM_INPUT_PROFILE_VERSION,
    recipe=RHYTHM_INPUT_RECIPE,
    model_sample_rate=BEAT_THIS_INPUT_SAMPLE_RATE,
    prepared_channels=BEAT_THIS_PREPARED_CHANNELS,
    channel_transform="adapter_mean_over_prepared_channels",
    amplitude_transform="none",
    resampler_profile_version=1,
    frame_hop=BEAT_THIS_FRAME_HOP,
    frame_rate=BEAT_THIS_FRAME_RATE,
    long_track_strategy="upstream_split_predict_aggregate",
    long_track_chunk_frames=BEAT_THIS_LONG_TRACK_CHUNK_FRAMES,
    long_track_border_frames=BEAT_THIS_LONG_TRACK_BORDER_FRAMES,
)
