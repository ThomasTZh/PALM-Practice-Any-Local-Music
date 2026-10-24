"""Reproducible rhythm-analysis input preparation (M3.3, milestone3.md §5).

Reads an immutable project PCM asset and produces the pinned Beat This!
representation for one rhythm input role:

1. Optional explicit M1 stereo downmix for multichannel sources.
2. One continuous resample to 22,050 Hz using the versioned SWR profile
   (never per-chunk).
3. Mono sources duplicated to stereo; the adapter's own channel mean is
   the only further channel transform.
4. A deterministic transform identity covering source hash, role, downmix,
   model identity, adapter version, and the full input profile.

The source asset is never modified. Beat This! handles long tracks
internally with the upstream split/predict/aggregate strategy; no custom
chunking is introduced.
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
from basseparate.domain.representation import TimeMapping
from basseparate.domain.rhythm_input import (
    BEAT_THIS_INPUT_PROFILE,
    RhythmInputPlan,
    RhythmInputProfile,
)
from basseparate.media.decode import check_frame_alignment, validate_pcm
from basseparate.media.derived import (
    DEFAULT_DERIVED_TIMEOUT_SECONDS,
    DerivedProgress,
    downmix_monitoring,
    resample_playback,
)
from basseparate.media.downmix import manual_matrix, pan_expression, standard_51_matrix
from basseparate.media.preparation import ENDPOINT_TOLERANCE_FRAMES, sha256_file


class RhythmInputError(Exception):
    """The rhythm input selection or prepared output is invalid."""


class RhythmInputHashMismatchError(RhythmInputError):
    """The canonical source does not match the plan's recorded hash."""


class RhythmInputEndpointError(RhythmInputError):
    """The resampled input differs from the expected duration by too much."""


@dataclass(frozen=True)
class RhythmInputOutcome:
    """Validated, model-ready rhythm input produced by the engine."""

    final_path: Path
    content_hash: Sha256Hash
    transform_hash: Sha256Hash
    frame_count: int
    source_frame_count: int
    expected_frame_count: int
    endpoint_difference_frames: int
    max_amplitude: float
    pcm_byte_count: int
    time_mapping: TimeMapping
    profile: RhythmInputProfile
    ffmpeg_version: str
    downmix_mode: str | None


def rhythm_input_transform_hash(
    plan: RhythmInputPlan, profile: RhythmInputProfile = BEAT_THIS_INPUT_PROFILE
) -> Sha256Hash:
    """Deterministic cache/transform identity for one rhythm input (§5.7).

    Pure function of the source identity, role, downmix, model identity,
    adapter, and the complete input profile. It intentionally excludes the
    asset row ID so identical content re-imported under a new ID can reuse
    the same prepared representation.
    """
    payload = {
        "recipe": profile.recipe,
        "profile_version": profile.profile_version,
        "profile": profile.model_dump(mode="json"),
        "input_role": plan.input_role.value,
        "source_hash": plan.source_hash,
        "downmix": plan.downmix.model_dump(mode="json") if plan.downmix else None,
        "model_id": plan.model_id,
        "model_manifest_hash": plan.model_manifest_hash,
        "adapter_version": plan.adapter_version,
        "source_sample_rate": plan.sample_rate,
        "source_channels": plan.channel_count,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _pan_spec(plan: RhythmInputPlan) -> str:
    assert plan.downmix is not None
    if plan.downmix.mode == "standard_5_1":
        left, right = standard_51_matrix()
    else:
        assert plan.downmix.left_channel is not None
        assert plan.downmix.right_channel is not None
        left, right = manual_matrix(
            plan.downmix.left_channel, plan.downmix.right_channel
        )
    return pan_expression(left, right)


async def prepare_rhythm_input(
    *,
    plan: RhythmInputPlan,
    source_path: Path,
    work_dir: Path,
    max_threads: int = 4,
    estimated_duration_seconds: float | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[DerivedProgress], None] | None = None,
    timeout_seconds: float = DEFAULT_DERIVED_TIMEOUT_SECONDS,
) -> RhythmInputOutcome:
    """Prepare the pinned rhythm-analysis representation (§5.4-§5.6).

    ``work_dir`` receives staging files; on success only the final prepared
    PCM remains (the caller owns it), and every staging file is removed on
    failure. The source is read-only.
    """
    if plan.sample_rate <= 0 or plan.channel_count <= 0:
        raise RhythmInputError("source sample rate and channel count must be positive")
    try:
        check_frame_alignment(source_path.stat().st_size, plan.channel_count)
    except Exception as exc:
        raise RhythmInputError(f"source PCM is not frame-aligned: {exc}") from exc
    actual_hash = await asyncio.to_thread(sha256_file, source_path)
    if actual_hash != plan.source_hash:
        raise RhythmInputHashMismatchError(
            f"source hash mismatch: expected {plan.source_hash}, got {actual_hash}"
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    downmix_path = work_dir / "downmix.pcm"
    resampled_path = work_dir / "resampled.pcm"
    final_path = work_dir / "rhythm-input.pcm"
    intermediates: list[Path] = []
    downmix_mode: str | None = None
    try:
        current_path = source_path
        current_channels = plan.channel_count
        if plan.downmix is not None:
            await downmix_monitoring(
                source_path=source_path,
                output_path=downmix_path,
                sample_rate=plan.sample_rate,
                channel_count=plan.channel_count,
                pan_spec=_pan_spec(plan),
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
            source_rate=plan.sample_rate,
            target_rate=BEAT_THIS_INPUT_PROFILE.model_sample_rate,
            channel_count=current_channels,
            max_threads=max_threads,
            estimated_duration_seconds=estimated_duration_seconds,
            cancel_event=cancel_event,
            on_progress=on_progress,
            timeout_seconds=timeout_seconds,
        )
        intermediates.append(resampled_path)

        if current_channels == 1:
            mono = np.fromfile(resampled_path, dtype="<f4")
            stereo = np.empty((mono.size, 2), dtype="<f4")
            stereo[:, 0] = mono
            stereo[:, 1] = mono
            final_path.write_bytes(np.ascontiguousarray(stereo).tobytes())
        else:
            resampled_path.replace(final_path)

        check_frame_alignment(
            final_path.stat().st_size, BEAT_THIS_INPUT_PROFILE.prepared_channels
        )
        content_hash, max_amplitude = await asyncio.to_thread(
            validate_pcm, final_path, BEAT_THIS_INPUT_PROFILE.prepared_channels
        )
        if abs(resampled.endpoint_difference_frames) > ENDPOINT_TOLERANCE_FRAMES:
            raise RhythmInputEndpointError(
                f"resampled duration differs by "
                f"{resampled.endpoint_difference_frames} frames; tolerance is "
                f"±{ENDPOINT_TOLERANCE_FRAMES}"
            )
        return RhythmInputOutcome(
            final_path=final_path,
            content_hash=content_hash,
            transform_hash=rhythm_input_transform_hash(plan),
            frame_count=resampled.frame_count,
            source_frame_count=resampled.source_frame_count,
            expected_frame_count=resampled.expected_frame_count,
            endpoint_difference_frames=resampled.endpoint_difference_frames,
            max_amplitude=max_amplitude,
            pcm_byte_count=final_path.stat().st_size,
            time_mapping=TimeMapping(
                project_rate=plan.sample_rate,
                representation_rate=BEAT_THIS_INPUT_PROFILE.model_sample_rate,
            ),
            profile=BEAT_THIS_INPUT_PROFILE,
            ffmpeg_version=resampled.ffmpeg_version,
            downmix_mode=downmix_mode,
        )
    except BaseException:
        for path in (downmix_path, resampled_path, final_path):
            with contextlib.suppress(OSError):
                path.unlink()
        raise
    finally:
        for path in intermediates:
            if path != final_path:
                with contextlib.suppress(OSError):
                    path.unlink()
