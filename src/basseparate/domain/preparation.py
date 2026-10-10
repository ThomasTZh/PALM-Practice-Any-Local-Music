"""Separation input preparation records (M2.4, milestone2.md §6).

A *reference mix plan* records which canonical asset a separation is
computed from and, for multichannel sources, the explicit M1 stereo
downmix used — the UI can therefore identify multichannel separation as
separation of the stereo downmix (§6.1).

A *prepared input* is the model-ready transform of that reference mix:
resampled exactly once to the model rate, in the model channel layout
(stereo; mono duplicated for model input), with a deterministic transform
identity, content hash, and source-time mapping. The transform never
trims, so the time origin is preserved and the mapping is the pure rate
ratio carried by ``TimeMapping`` (§6.2).

A *normalization profile* is the versioned, whole-track set of
normalization statistics used by bounded processing: the same statistics
apply to every window, so window scales stay consistent across the track
(§6.3). Degenerate inputs are classified explicitly: exact silence takes
the zero-stem shortcut without inference, and a near-zero channel-mean
level (strong anti-phase) falls back to the full-channel reference with a
documented epsilon, so the model input is never divided by a near-zero
value (§6.4).
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import SamplePosition, SampleRate, Sha256Hash, UtcTimestamp, Uuid
from basseparate.domain.representation import TimeMapping

ReferenceMixKind = Literal["stereo", "mono", "multichannel"]
DownmixMode = Literal["standard_5_1", "manual"]
ProfileMode = Literal["normal", "full_channel_fallback", "exact_silence"]
ProfileReference = Literal["channel_mean", "full_channel"]

#: Version of the normalization profile format and its epsilon policy.
NORMALIZATION_PROFILE_VERSION = "v1"


class DownmixSpec(BaseModel):
    """The explicit M1 stereo downmix applied to a multichannel source.

    ``standard_5_1`` uses the fixed row-normalized matrix; ``manual``
    records the user's left/right source-channel selection. Speaker
    identities are never guessed from the channel count alone (M1.7).
    """

    model_config = ConfigDict(frozen=True)

    mode: DownmixMode
    left_channel: int | None = Field(default=None, ge=0, le=15)
    right_channel: int | None = Field(default=None, ge=0, le=15)

    @model_validator(mode="after")
    def _check_channel_selections(self) -> DownmixSpec:
        if self.mode == "manual":
            if self.left_channel is None or self.right_channel is None:
                raise ValueError("a manual downmix requires both channel selections")
        elif self.left_channel is not None or self.right_channel is not None:
            raise ValueError("a standard_5_1 downmix must not carry channel selections")
        return self


class ReferenceMixPlan(BaseModel):
    """Which canonical asset is the separation reference mix (§6.1).

    Stereo sources use the canonical stereo PCM; mono sources use the
    canonical mono PCM (duplicated only for model input); multichannel
    sources use the explicit M1 stereo downmix and must say so.
    """

    model_config = ConfigDict(frozen=True)

    kind: ReferenceMixKind
    asset_id: Uuid
    source_hash: Sha256Hash
    downmix: DownmixSpec | None = None

    @model_validator(mode="after")
    def _check_downmix(self) -> ReferenceMixPlan:
        if self.kind == "multichannel" and self.downmix is None:
            raise ValueError(
                "a multichannel reference mix requires an explicit downmix spec"
            )
        if self.kind in ("stereo", "mono") and self.downmix is not None:
            raise ValueError("stereo and mono reference mixes must not carry a downmix spec")
        return self


class ChannelStats(BaseModel):
    """Whole-track mean and RMS of one statistic domain (float64 values)."""

    model_config = ConfigDict(frozen=True)

    mean: float
    rms: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _check_finite(self) -> ChannelStats:
        if not (math.isfinite(self.mean) and math.isfinite(self.rms)):
            raise ValueError("channel stats must be finite")
        return self


class NormalizationProfile(BaseModel):
    """Versioned global normalization statistics for bounded processing.

    ``reference`` selects which statistic domain the adapter must use as
    the window pre-scale: ``channel_mean`` (the normal path) or
    ``full_channel`` (the anti-phase fallback). ``scale`` is the bounded
    pre-scale factor ``1 / max(rms_reference, epsilon)``; it is exactly
    zero for the exact-silence shortcut, which emits zero stems without
    inference (§6.4 rules 1–2 and 6).
    """

    model_config = ConfigDict(frozen=True)

    version: str = Field(
        default=NORMALIZATION_PROFILE_VERSION, min_length=1, max_length=16
    )
    prepared_input_hash: Sha256Hash
    frame_count: SamplePosition
    channel_count: int = Field(ge=1, le=8)
    max_abs: float = Field(ge=0.0)
    channel_mean: ChannelStats
    full_channel: ChannelStats
    mode: ProfileMode
    reference: ProfileReference
    scale: float = Field(ge=0.0)
    epsilon: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _check_mode_consistency(self) -> NormalizationProfile:
        if not (math.isfinite(self.scale) and math.isfinite(self.max_abs)):
            raise ValueError("profile scale and max_abs must be finite")
        if (self.mode == "exact_silence") != (self.scale == 0.0):
            raise ValueError("scale is zero if and only if the mode is exact_silence")
        if self.mode == "exact_silence" and self.max_abs != 0.0:
            raise ValueError("exact_silence requires max_abs to be zero")
        if self.mode == "full_channel_fallback" and self.reference != "full_channel":
            raise ValueError("full_channel_fallback must use the full_channel reference")
        if self.mode == "normal" and self.reference != "channel_mean":
            raise ValueError("normal mode must use the channel_mean reference")
        return self


class PreparedInput(BaseModel):
    """The prepared, model-ready separation input and its identity (§6.2).

    ``transform_hash`` identifies the transform recipe (version, source
    hash, model rate, channel layout, downmix spec, resampler profile);
    ``content_hash`` identifies the prepared bytes. Identical source and
    plan therefore yield an identical prepared input, which the
    content-addressed asset store deduplicates (§6.2.6).
    """

    model_config = ConfigDict(frozen=True)

    asset_id: Uuid
    content_hash: Sha256Hash
    transform_hash: Sha256Hash
    sample_rate: SampleRate
    channel_count: int = Field(ge=1, le=8)
    frame_count: SamplePosition
    source_asset_id: Uuid
    source_hash: Sha256Hash
    source_rate: SampleRate
    source_frame_count: SamplePosition
    endpoint_difference_frames: int = Field(
        ge=-16,
        le=16,
        description="Actual output frames minus the expected resampled count; "
        "the preparation service enforces the tighter documented tolerance",
    )
    time_mapping: TimeMapping
    created_at: UtcTimestamp
