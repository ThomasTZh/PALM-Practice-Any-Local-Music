"""Decoded rhythm candidates (M3.5, milestone3.md §7).

The decoder is deliberately separate from neural inference: it consumes
an immutable activation artifact and a versioned decoder profile, so
postprocessing changes never require re-running Beat This! and raw
activations stay independent.

Accepted pulses are the initial objects for tempo-map construction;
candidate pulses retain ambiguous or low-confidence evidence for review.
Positions are source-aligned: model-time peaks map to exact fractional
source frames and round once at the final discrete boundary.
"""

from __future__ import annotations

from math import gcd
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import (
    JS_SAFE_INTEGER_MAX,
    SamplePosition,
    SampleRate,
    Sha256Hash,
    UtcTimestamp,
    Uuid,
)
from basseparate.domain.confidence import Confidence
from basseparate.domain.rhythm import PulseAcceptance, PulseRole

#: Initial decoder profile: the pinned Beat This! minimal postprocessor.
DECODER_PROFILE_ID = "beat-this-minimal-v1"
DECODER_PROFILE_VERSION = 1


class BeatDecoderProfile(BaseModel):
    """Explicit, versioned postprocessing parameters (§7.1, §7.7)."""

    model_config = ConfigDict(frozen=True)

    profile_id: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    peak_window_frames: int = Field(
        default=7,
        ge=3,
        le=51,
        description="Odd max-pool window used for local-maximum peak detection",
    )
    accepted_logit_threshold: float = Field(default=0.0)
    candidate_logit_threshold: float = Field(
        default=-2.0,
        description="Lower threshold for retained candidate peaks",
    )
    snap_downbeats_to_beats: bool = True
    rounding: Literal["half_up"] = "half_up"
    endpoint_tolerance_frames: int = Field(default=1, ge=0, le=4)
    max_tiny_interval_seconds: float = Field(default=0.1, gt=0.0)
    long_gap_median_factor: float = Field(default=4.0, gt=1.0)

    @model_validator(mode="after")
    def _check_thresholds(self) -> BeatDecoderProfile:
        if self.peak_window_frames % 2 != 1:
            raise ValueError("peak_window_frames must be odd")
        if self.candidate_logit_threshold > self.accepted_logit_threshold:
            raise ValueError("candidate_logit_threshold must not exceed accepted_logit_threshold")
        return self


BEAT_THIS_DECODER_PROFILE = BeatDecoderProfile(
    profile_id=DECODER_PROFILE_ID,
    version=DECODER_PROFILE_VERSION,
)


class SourceFrameFraction(BaseModel):
    """Exact fractional project source frame before final rounding."""

    model_config = ConfigDict(frozen=True)

    numerator: int = Field(ge=-JS_SAFE_INTEGER_MAX, le=JS_SAFE_INTEGER_MAX)
    denominator: int = Field(gt=0, le=JS_SAFE_INTEGER_MAX)

    def model_post_init(self, __context: object) -> None:
        divisor = gcd(abs(self.numerator), self.denominator)
        object.__setattr__(self, "numerator", self.numerator // divisor)
        object.__setattr__(self, "denominator", self.denominator // divisor)


class DecodedPulse(BaseModel):
    """One decoded beat/downbeat candidate, source-aligned (§7.2-§7.5)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    acceptance: PulseAcceptance
    role: PulseRole
    #: Fractional model frame used for mapping (deduplicated/snapped center).
    model_frame: float = Field(ge=0.0)
    #: Original detected peak frame before dedup/snap (diagnostics).
    peak_model_frame: float = Field(ge=0.0)
    source_frame: SamplePosition
    source_frame_fraction: SourceFrameFraction
    beat_logit: float | None = None
    downbeat_logit: float | None = None
    #: sigmoid of the role's selected logit; uncalibrated model score.
    probability: float = Field(ge=0.0, le=1.0)
    confidence: Confidence
    flags: list[str] = Field(default_factory=list, max_length=8)
    alternative_of: Uuid | None = None


class DecodedRhythmResult(BaseModel):
    """Versioned decoded output for one activation artifact (§7.4, §7.7)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    activation_artifact_id: Uuid
    activation_content_hash: Sha256Hash
    decoder_profile: BeatDecoderProfile
    project_sample_rate: SampleRate
    source_duration_frames: SamplePosition
    accepted_pulses: list[DecodedPulse] = Field(default_factory=list)
    candidate_pulses: list[DecodedPulse] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list, max_length=16)
    diagnostics: dict[str, float | int | str] = Field(default_factory=dict)
    created_at: UtcTimestamp
    content_hash: Sha256Hash

    @model_validator(mode="after")
    def _check_source_alignment(self) -> DecodedRhythmResult:
        sources = [pulse.source_frame for pulse in self.accepted_pulses]
        if len(set(sources)) != len(sources):
            raise ValueError("accepted pulses must not share a source frame")
        for pulse in self.accepted_pulses:
            if pulse.acceptance is not PulseAcceptance.ACCEPTED:
                raise ValueError("accepted layer may only contain accepted pulses")
            if pulse.source_frame > self.source_duration_frames:
                raise ValueError("an accepted pulse lies beyond the source duration")
        for pulse in self.candidate_pulses:
            if pulse.acceptance is PulseAcceptance.ACCEPTED:
                raise ValueError("candidate layer must not contain accepted pulses")
        return self
