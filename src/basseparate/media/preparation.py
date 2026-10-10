"""Separation input preparation (M2.4, milestone2.md §6).

Turns a project's canonical PCM source into a deterministic, model-ready
prepared input plus a versioned global normalization profile:

1. pre-check the source file hash (§6.2.2);
2. multichannel: the explicit M1.7 stereo downmix (``downmix_spec``);
3. resample the whole reference exactly once to the model rate with the
   versioned M1.7 SWR profile;
4. mono: duplicate to stereo for model input (§6.1);
5. validate the final bytes (alignment, finiteness, hash, max amplitude);
6. check the duration within the documented resampling tolerance (§6.2.9);
7. compute the global normalization profile (streaming float64, §6.3–6.4).

The transform never trims, so the source time origin is preserved. The
service is stateless: identical source bytes and plan yield identical
prepared bytes and transform identity, so the content-addressed asset
store deduplicates re-runs (§6.2.6). The main environment stays
torch/demucs-free: numpy plus the M1.7 ffmpeg driver only.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from basseparate.domain.common import Sha256Hash
from basseparate.domain.preparation import (
    NORMALIZATION_PROFILE_VERSION,
    ChannelStats,
    DownmixSpec,
    NormalizationProfile,
    ReferenceMixPlan,
)
from basseparate.media.decode import validate_pcm
from basseparate.media.derived import (
    DEFAULT_DERIVED_TIMEOUT_SECONDS,
    DerivedProgress,
    downmix_monitoring,
    resample_playback,
)
from basseparate.media.downmix import (
    manual_matrix,
    pan_expression,
    standard_51_matrix,
)

#: Identity of the prepared-input transform recipe (feeds transform_hash).
SEPARATION_INPUT_RECIPE = "separation-input-v1"

#: The M1.7 SWR resampler profile (pinned options, spec §9.5).
RESAMPLER_PROFILE_ID = "swr-v1(filter_size=64,exact_rational=1,dither_method=0)"

#: Caps the window pre-scale: 1 / max(rms_reference, epsilon) (spec §6.4.6).
NORMALIZATION_EPSILON = 1e-4

#: Channel-mean variance below this fraction of the full-channel variance
#: triggers the documented full-channel normalization fallback
#: (strong anti-phase; spec §6.4.3).
FALLBACK_RATIO = 1e-2

#: Maximum |actual − expected| resampled frame count (spec §6.2.9).
ENDPOINT_TOLERANCE_FRAMES = 2

_HASH_CHUNK_SIZE = 2**20
_PROFILE_CHUNK_SIZE = 4 * 1024 * 1024


class PreparationError(Exception):
    """Base error for separation input preparation failures."""


class SourceHashMismatchError(PreparationError):
    """The source file does not match the plan's expected content hash."""


class EndpointToleranceError(PreparationError):
    """The resampled duration is outside the documented tolerance."""


@dataclass(frozen=True)
class PreparedInputOutcome:
    """Validated output of the preparation pipeline.

    The caller owns ``final_path`` (publication to the asset store is
    M2.5/M2.17 work). All other intermediates have been removed.
    """

    final_path: Path
    content_hash: str
    transform_hash: str
    frame_count: int
    source_frame_count: int
    endpoint_difference_frames: int
    max_amplitude: float
    pcm_byte_count: int
    profile: NormalizationProfile
    ffmpeg_version: str
    downmix_mode: str | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def transform_identity_hash(plan: ReferenceMixPlan, model_rate: int) -> str:
    """Deterministic identity of the transform recipe (spec §6.2.7).

    Pure function of the plan and the model rate: identical source and
    plan ⇒ identical transform identity (the acceptance criterion).
    """
    recipe = {
        "recipe": SEPARATION_INPUT_RECIPE,
        "kind": plan.kind,
        "source_hash": plan.source_hash,
        "model_rate": model_rate,
        "channel_layout": 2,
        "downmix": (
            None
            if plan.downmix is None
            else {
                "mode": plan.downmix.mode,
                "left_channel": plan.downmix.left_channel,
                "right_channel": plan.downmix.right_channel,
            }
        ),
        "resampler": RESAMPLER_PROFILE_ID,
        "mono_duplication": plan.kind == "mono",
    }
    payload = json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_normalization_profile(
    pcm_path: Path,
    sample_rate: int,
    channel_count: int,
    prepared_input_hash: str,
) -> NormalizationProfile:
    """One streaming pass over the prepared input; float64 accumulators.

    Computes both statistic domains — full-channel (every sample of every
    channel) and channel-mean (per-frame mean over channels) — and
    classifies the input (spec §6.4): exact silence takes the zero-stem
    shortcut (scale 0, no inference); a channel-mean variance below
    ``FALLBACK_RATIO`` of the full-channel variance (strong anti-phase)
    selects the documented full-channel reference; otherwise the
    channel-mean reference is used. The pre-scale is bounded by
    ``NORMALIZATION_EPSILON`` so a near-zero reference never yields an
    unbounded model input.
    """
    n_frames = 0
    sum_full = 0.0
    sumsq_full = 0.0
    sum_mean = 0.0
    sumsq_mean = 0.0
    max_abs = 0.0

    with pcm_path.open("rb") as handle:
        while True:
            chunk = handle.read(_PROFILE_CHUNK_SIZE)
            if not chunk:
                break
            if len(chunk) % (4 * channel_count) != 0:
                raise PreparationError(
                    f"PCM file {pcm_path.name} is not frame-aligned "
                    f"for {channel_count} channels"
                )
            block = np.frombuffer(chunk, dtype="<f4").astype(np.float64)
            block = block.reshape(-1, channel_count)
            if not np.isfinite(block).all():
                raise PreparationError(f"PCM file {pcm_path.name} contains non-finite samples")
            n_frames += block.shape[0]
            sum_full += float(block.sum())
            sumsq_full += float(np.square(block).sum())
            block_max = float(np.abs(block).max())
            if block_max > max_abs:
                max_abs = block_max
            frame_mean = block.mean(axis=1)
            sum_mean += float(frame_mean.sum())
            sumsq_mean += float(np.square(frame_mean).sum())

    if n_frames == 0:
        raise PreparationError(f"PCM file {pcm_path.name} is empty")

    n_samples = n_frames * channel_count
    full_mean = sum_full / n_samples
    full_rms = float(np.sqrt(sumsq_full / n_samples))
    var_full = max(sumsq_full / n_samples - full_mean * full_mean, 0.0)
    mean_mean = sum_mean / n_frames
    mean_rms = float(np.sqrt(sumsq_mean / n_frames))
    var_mean = max(sumsq_mean / n_frames - mean_mean * mean_mean, 0.0)

    if max_abs == 0.0:
        mode: str = "exact_silence"
        reference: str = "full_channel"
        scale = 0.0
    elif var_mean < FALLBACK_RATIO * var_full:
        mode = "full_channel_fallback"
        reference = "full_channel"
        scale = 1.0 / max(full_rms, NORMALIZATION_EPSILON)
    else:
        mode = "normal"
        reference = "channel_mean"
        scale = 1.0 / max(mean_rms, NORMALIZATION_EPSILON)

    return NormalizationProfile(
        version=NORMALIZATION_PROFILE_VERSION,
        prepared_input_hash=Sha256Hash(prepared_input_hash),
        frame_count=n_frames,
        channel_count=channel_count,
        max_abs=max_abs,
        channel_mean=ChannelStats(mean=mean_mean, rms=mean_rms),
        full_channel=ChannelStats(mean=full_mean, rms=full_rms),
        mode=mode,
        reference=reference,
        scale=scale,
        epsilon=NORMALIZATION_EPSILON,
    )


def _pan_spec_for(downmix: DownmixSpec) -> str:
    if downmix.mode == "standard_5_1":
        left, right = standard_51_matrix()
    else:
        assert downmix.left_channel is not None and downmix.right_channel is not None
        left, right = manual_matrix(downmix.left_channel, downmix.right_channel)
    return pan_expression(left, right)


def _expected_channels(kind: str, source_channels: int) -> int:
    if kind == "mono":
        return 1
    if kind == "stereo":
        return 2
    return source_channels


async def prepare_separation_input(
    *,
    plan: ReferenceMixPlan,
    source_path: Path,
    source_rate: int,
    source_channels: int,
    model_rate: int,
    work_dir: Path,
    max_threads: int = 4,
    estimated_duration_seconds: float | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[DerivedProgress], None] | None = None,
    timeout_seconds: float = DEFAULT_DERIVED_TIMEOUT_SECONDS,
) -> PreparedInputOutcome:
    """Prepare the model-ready separation input (spec §6.2).

    ``work_dir`` receives the staging files; on success only the final
    file remains (the caller owns it), on failure every staging file is
    removed. The source file is never modified.
    """
    expected = _expected_channels(plan.kind, source_channels)
    if source_channels != expected:
        raise PreparationError(
            f"plan kind {plan.kind!r} does not match the source's "
            f"{source_channels} channels"
        )
    if model_rate <= 0:
        raise PreparationError(f"model rate must be positive, got {model_rate}")

    try:
        actual_hash = sha256_file(source_path)
    except OSError as exc:
        raise PreparationError(f"source PCM not found: {source_path.name}") from exc
    if actual_hash != plan.source_hash:
        raise SourceHashMismatchError(
            f"source hash mismatch: expected {plan.source_hash}, got {actual_hash}"
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    downmix_path = work_dir / "downmix.pcm"
    resampled_path = work_dir / "resampled.pcm"
    duplicated_path = work_dir / "prepared.pcm"
    intermediates: list[Path] = []
    final_path: Path | None = None
    try:
        current_path = source_path
        current_channels = source_channels
        downmix_mode: str | None = None

        if plan.downmix is not None:
            await downmix_monitoring(
                source_path=source_path,
                output_path=downmix_path,
                sample_rate=source_rate,
                channel_count=source_channels,
                pan_spec=_pan_spec_for(plan.downmix),
                max_threads=max_threads,
                estimated_duration_seconds=estimated_duration_seconds,
                cancel_event=cancel_event,
                on_progress=on_progress,
                timeout_seconds=timeout_seconds,
            )
            downmix_mode = plan.downmix.mode
            current_path = downmix_path
            current_channels = 2
            intermediates.append(downmix_path)

        resampled = await resample_playback(
            source_path=current_path,
            output_path=resampled_path,
            source_rate=source_rate,
            target_rate=model_rate,
            channel_count=current_channels,
            max_threads=max_threads,
            estimated_duration_seconds=estimated_duration_seconds,
            cancel_event=cancel_event,
            on_progress=on_progress,
            timeout_seconds=timeout_seconds,
        )

        if current_channels == 1:
            # Mono is duplicated to stereo for model input (§6.1): a
            # deterministic, byte-exact interleave.
            mono = np.fromfile(resampled_path, dtype="<f4")
            stereo = np.empty((mono.size, 2), dtype="<f4")
            stereo[:, 0] = mono
            stereo[:, 1] = mono
            duplicated_path.write_bytes(np.ascontiguousarray(stereo).tobytes())
            final_path = duplicated_path
            intermediates.append(resampled_path)
        else:
            final_path = resampled_path

        final_channels = 2 if current_channels == 1 else current_channels
        content_hash, max_amplitude = await asyncio.to_thread(
            validate_pcm, final_path, final_channels
        )

        endpoint_difference = resampled.endpoint_difference_frames
        if abs(endpoint_difference) > ENDPOINT_TOLERANCE_FRAMES:
            raise EndpointToleranceError(
                f"resampled duration differs by {endpoint_difference} frames; "
                f"tolerance is ±{ENDPOINT_TOLERANCE_FRAMES}"
            )

        profile = await asyncio.to_thread(
            compute_normalization_profile,
            final_path,
            model_rate,
            final_channels,
            content_hash,
        )

        transform_hash = transform_identity_hash(plan, model_rate)
        for path in intermediates:
            with contextlib.suppress(OSError):
                path.unlink()
        return PreparedInputOutcome(
            final_path=final_path,
            content_hash=content_hash,
            transform_hash=transform_hash,
            frame_count=resampled.frame_count,
            source_frame_count=resampled.source_frame_count,
            endpoint_difference_frames=endpoint_difference,
            max_amplitude=max_amplitude,
            pcm_byte_count=final_path.stat().st_size,
            profile=profile,
            ffmpeg_version=resampled.ffmpeg_version,
            downmix_mode=downmix_mode,
        )
    except Exception:
        for staging in [*intermediates, final_path]:
            if staging is not None:
                with contextlib.suppress(OSError):
                    staging.unlink()
        raise
