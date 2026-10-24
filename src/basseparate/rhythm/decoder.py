"""Beat/downbeat candidate decoder (M3.5, milestone3.md §7).

Reimplements the pinned Beat This! "minimal" postprocessor without torch:
local maxima over a 7-frame window, positive-logit acceptance, adjacent
peak deduplication, and downbeat snapping to the nearest beat. The result
is a versioned decoded artifact that references its activation artifact;
raw activations are never modified or regenerated.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from fractions import Fraction
from typing import Any

import numpy as np

from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.rhythm import (
    ActivationArtifactManifest,
    ActivationFrameMapping,
    PulseAcceptance,
    PulseRole,
)
from basseparate.domain.rhythm_decode import (
    BEAT_THIS_DECODER_PROFILE,
    BeatDecoderProfile,
    DecodedPulse,
    DecodedRhythmResult,
    SourceFrameFraction,
)
from basseparate.rhythm.activations import BEAT_FILE, DOWNBEAT_FILE, RhythmActivationStore


class RhythmDecodeError(Exception):
    """The activation input or decoder parameters are invalid."""


@dataclass(frozen=True)
class DecodeInput:
    """Activation arrays plus the identity of their artifact."""

    artifact_id: uuid.UUID
    content_hash: str
    frame_mapping: ActivationFrameMapping
    beat: np.ndarray
    downbeat: np.ndarray


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def _max_pool_1d(values: np.ndarray, window: int) -> np.ndarray:
    padding = window // 2
    length = values.size
    pooled = np.empty(length, dtype=values.dtype)
    for index in range(length):
        start = max(0, index - padding)
        stop = min(length, index + padding + 1)
        pooled[index] = values[start:stop].max()
    return pooled


def _peak_frames(
    values: np.ndarray, threshold: float, window: int, *, strict: bool = False
) -> list[Fraction]:
    """Local maxima above threshold, adjacent groups replaced by their mean.

    Accepted peaks use the upstream max-pool equality test (ties are later
    deduplicated). Candidate peaks use strict dominance so a flat low-level
    plateau (for example silence) does not become a mass of candidates.
    """
    if strict:
        strict_peaks = np.zeros(values.shape, dtype=bool)
        for index in range(values.size):
            value = values[index]
            if value <= threshold:
                continue
            left = values[index - 1] if index > 0 else -np.inf
            right = values[index + 1] if index + 1 < values.size else -np.inf
            if value > left and value > right:
                strict_peaks[index] = True
        peaks = strict_peaks
    else:
        peaks = (values == _max_pool_1d(values, window)) & (values > threshold)
    indices = [int(index) for index in np.flatnonzero(peaks)]
    if not indices:
        return []
    grouped: list[Fraction] = []
    group: list[int] = [indices[0]]
    for index in indices[1:]:
        if index - group[-1] <= 1:
            group.append(index)
        else:
            grouped.append(Fraction(sum(group), len(group)))
            group = [index]
    grouped.append(Fraction(sum(group), len(group)))
    return grouped


def _index_of(frame: Fraction) -> int:
    rounded = math.floor(frame + Fraction(1, 2))
    return max(0, int(rounded))


def _source_fraction(frame: Fraction, mapping: ActivationFrameMapping) -> Fraction:
    return (
        frame * mapping.frame_hop * mapping.project_sample_rate / mapping.model_sample_rate
        + mapping.offset_frames
    )


def _round_half_up(value: Fraction) -> int:
    return int(math.floor(value + Fraction(1, 2)))


def _confidence(logit: float) -> Confidence:
    return Confidence(
        kind=ConfidenceKind.HEURISTIC,
        value=_sigmoid(logit),
        calibrated=False,
        method="beat-this-minimal-logit-sigmoid-v1",
    )


def _canonical_pulse(pulse: DecodedPulse) -> dict[str, Any]:
    return {
        "acceptance": pulse.acceptance.value,
        "role": pulse.role.value,
        "model_frame": pulse.model_frame,
        "peak_model_frame": pulse.peak_model_frame,
        "source_frame": pulse.source_frame,
        "source_fraction": [
            pulse.source_frame_fraction.numerator,
            pulse.source_frame_fraction.denominator,
        ],
        "beat_logit": pulse.beat_logit,
        "downbeat_logit": pulse.downbeat_logit,
        "probability": pulse.probability,
        "flags": pulse.flags,
    }


def decoded_content_hash(
    input_identity: DecodeInput,
    profile: BeatDecoderProfile,
    project_sample_rate: int,
    source_duration_frames: int,
    accepted: list[DecodedPulse],
    candidates: list[DecodedPulse],
    flags: list[str],
) -> str:
    payload = {
        "decoder": "rhythm-decoder",
        "profile": profile.model_dump(mode="json"),
        "activation_content_hash": input_identity.content_hash,
        "project_sample_rate": project_sample_rate,
        "source_duration_frames": source_duration_frames,
        "accepted": [_canonical_pulse(pulse) for pulse in accepted],
        "candidates": [_canonical_pulse(pulse) for pulse in candidates],
        "flags": sorted(flags),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    import hashlib

    return hashlib.sha256(encoded).hexdigest()


def _reject_outside(
    pulse: DecodedPulse,
) -> bool:
    return "outside_source" in pulse.flags


def _make_pulse(
    *,
    role: PulseRole,
    acceptance: PulseAcceptance,
    model_frame: Fraction,
    peak_frame: Fraction,
    beat_logit: float | None,
    downbeat_logit: float | None,
    mapping: ActivationFrameMapping,
    source_duration_frames: int,
    endpoint_tolerance: int,
    flags: list[str],
) -> DecodedPulse:
    fraction = _source_fraction(model_frame, mapping)
    rounded = _round_half_up(fraction)
    pulse_flags = list(flags)
    if rounded < 0:
        pulse_flags.append("outside_source")
    elif rounded > source_duration_frames:
        if rounded <= source_duration_frames + endpoint_tolerance:
            rounded = source_duration_frames
            pulse_flags.append("clamped_endpoint")
        else:
            pulse_flags.append("outside_source")
    selected = downbeat_logit if role is PulseRole.DOWNBEAT else beat_logit
    if selected is None:
        raise RhythmDecodeError("a decoded pulse needs its role's activation logit")
    return DecodedPulse(
        id=uuid.uuid4(),
        acceptance=acceptance,
        role=role,
        model_frame=float(model_frame),
        peak_model_frame=float(peak_frame),
        source_frame=max(0, rounded),
        source_frame_fraction=SourceFrameFraction(
            numerator=fraction.numerator, denominator=fraction.denominator
        ),
        beat_logit=beat_logit,
        downbeat_logit=downbeat_logit,
        probability=_sigmoid(selected),
        confidence=_confidence(selected),
        flags=pulse_flags[:8],
    )


def decode_arrays(
    decode_input: DecodeInput,
    *,
    project_sample_rate: int,
    source_duration_frames: int,
    profile: BeatDecoderProfile = BEAT_THIS_DECODER_PROFILE,
) -> DecodedRhythmResult:
    """Decode Beat This! activations into accepted and candidate pulses."""
    beat = decode_input.beat
    downbeat = decode_input.downbeat
    if beat.ndim != 1 or downbeat.ndim != 1:
        raise RhythmDecodeError("activation arrays must be one-dimensional")
    if beat.size == 0 or beat.size != downbeat.size:
        raise RhythmDecodeError("activation arrays must be non-empty and equal length")
    if beat.dtype != np.float32 or downbeat.dtype != np.float32:
        raise RhythmDecodeError("activation arrays must be float32")
    if not np.isfinite(beat).all() or not np.isfinite(downbeat).all():
        raise RhythmDecodeError("activation arrays contain non-finite values")

    beat_peaks = _peak_frames(beat, profile.accepted_logit_threshold, profile.peak_window_frames)
    downbeat_peaks = _peak_frames(
        downbeat, profile.accepted_logit_threshold, profile.peak_window_frames
    )
    beat_candidates = _peak_frames(
        beat, profile.candidate_logit_threshold, profile.peak_window_frames, strict=True
    )
    downbeat_candidates = _peak_frames(
        downbeat,
        profile.candidate_logit_threshold,
        profile.peak_window_frames,
        strict=True,
    )

    # Upstream minimal postprocessing snaps each downbeat to the nearest beat.
    downbeat_effective: list[tuple[Fraction, Fraction]] = []
    for peak in downbeat_peaks:
        if beat_peaks and profile.snap_downbeats_to_beats:
            nearest = min(beat_peaks, key=lambda candidate: abs(candidate - peak))
            downbeat_effective.append((nearest, peak))
        else:
            downbeat_effective.append((peak, peak))

    accepted: list[DecodedPulse] = []
    downbeat_positions = {effective for effective, _peak in downbeat_effective}
    for frame in beat_peaks:
        logit = float(beat[_index_of(frame)])
        if frame in downbeat_positions:
            continue  # merged into the downbeat pulse below
        accepted.append(
            _make_pulse(
                role=PulseRole.BEAT,
                acceptance=PulseAcceptance.ACCEPTED,
                model_frame=frame,
                peak_frame=frame,
                beat_logit=logit,
                downbeat_logit=None,
                mapping=decode_input.frame_mapping,
                source_duration_frames=source_duration_frames,
                endpoint_tolerance=profile.endpoint_tolerance_frames,
                flags=[],
            )
        )
    for effective, peak in downbeat_effective:
        pulse = _make_pulse(
            role=PulseRole.DOWNBEAT,
            acceptance=PulseAcceptance.ACCEPTED,
            model_frame=effective,
            peak_frame=peak,
            beat_logit=float(beat[_index_of(effective)]) if beat.size else None,
            downbeat_logit=float(downbeat[_index_of(peak)]),
            mapping=decode_input.frame_mapping,
            source_duration_frames=source_duration_frames,
            endpoint_tolerance=profile.endpoint_tolerance_frames,
            flags=["downbeat_snapped"] if effective != peak else [],
        )
        accepted.append(pulse)

    candidates: list[DecodedPulse] = []

    def add_candidates(
        frames: list[Fraction], values: np.ndarray, role: PulseRole, threshold: float
    ) -> None:
        accepted_frames = [pulse.model_frame for pulse in accepted]
        accepted_peaks = [pulse.peak_model_frame for pulse in accepted]
        for frame in frames:
            logit = float(values[_index_of(frame)])
            if logit <= threshold:
                continue
            if any(abs(float(frame) - value) < 1e-6 for value in accepted_frames):
                continue
            if any(abs(float(frame) - value) < 1e-6 for value in accepted_peaks):
                continue
            beat_logit = logit if role is PulseRole.BEAT else None
            downbeat_logit = logit if role is PulseRole.DOWNBEAT else None
            flags = ["low_confidence"] if logit <= profile.accepted_logit_threshold else []
            candidates.append(
                _make_pulse(
                    role=role,
                    acceptance=PulseAcceptance.CANDIDATE,
                    model_frame=frame,
                    peak_frame=frame,
                    beat_logit=beat_logit,
                    downbeat_logit=downbeat_logit,
                    mapping=decode_input.frame_mapping,
                    source_duration_frames=source_duration_frames,
                    endpoint_tolerance=profile.endpoint_tolerance_frames,
                    flags=flags,
                )
            )

    add_candidates(beat_candidates, beat, PulseRole.BEAT, profile.candidate_logit_threshold)
    add_candidates(
        downbeat_candidates, downbeat, PulseRole.DOWNBEAT, profile.candidate_logit_threshold
    )

    # Endpoint failures and source-frame collisions are retained as candidates.
    in_range: list[DecodedPulse] = []
    for pulse in accepted:
        if _reject_outside(pulse):
            candidates.append(pulse.model_copy(update={"acceptance": PulseAcceptance.CANDIDATE}))
        else:
            in_range.append(pulse)
    accepted = []

    by_source: dict[int, list[DecodedPulse]] = {}
    for pulse in in_range:
        by_source.setdefault(pulse.source_frame, []).append(pulse)
    for _source_frame, group in sorted(by_source.items()):
        group.sort(key=lambda pulse: pulse.probability, reverse=True)
        keep = group[0]
        accepted.append(keep)
        for loser in group[1:]:
            candidates.append(
                loser.model_copy(
                    update={
                        "acceptance": PulseAcceptance.CANDIDATE,
                        "flags": [*loser.flags, "source_collision"][:8],
                        "alternative_of": keep.id,
                    }
                )
            )

    accepted.sort(key=lambda pulse: pulse.source_frame)
    candidates.sort(key=lambda pulse: (pulse.source_frame, pulse.model_frame))
    flags = _plausibility_flags(accepted, candidates, profile, project_sample_rate)
    diagnostics = _diagnostics(
        accepted, candidates, profile, beat_peaks, downbeat_peaks, project_sample_rate
    )
    content_hash = decoded_content_hash(
        decode_input,
        profile,
        project_sample_rate,
        source_duration_frames,
        accepted,
        candidates,
        flags,
    )
    return DecodedRhythmResult(
        id=uuid.uuid4(),
        activation_artifact_id=decode_input.artifact_id,
        activation_content_hash=decode_input.content_hash,
        decoder_profile=profile,
        project_sample_rate=project_sample_rate,
        source_duration_frames=source_duration_frames,
        accepted_pulses=accepted,
        candidate_pulses=candidates,
        flags=flags,
        diagnostics=diagnostics,
        created_at=datetime.now(UTC),
        content_hash=content_hash,
    )


def _plausibility_flags(
    accepted: list[DecodedPulse],
    candidates: list[DecodedPulse],
    profile: BeatDecoderProfile,
    project_sample_rate: int,
) -> list[str]:
    flags: list[str] = []
    if not accepted:
        flags.append("no_accepted_pulses")
    intervals = [
        (right.source_frame - left.source_frame) / project_sample_rate
        for left, right in zip(accepted, accepted[1:], strict=False)
    ]
    if intervals:
        median = sorted(intervals)[len(intervals) // 2]
        if any(interval < profile.max_tiny_interval_seconds for interval in intervals):
            flags.append("tiny_interval")
        if median > 0 and any(
            interval > profile.long_gap_median_factor * median for interval in intervals
        ):
            flags.append("long_gap")
        mean = sum(intervals) / len(intervals)
        variance = sum((interval - mean) ** 2 for interval in intervals) / len(intervals)
        if mean > 0 and math.sqrt(variance) / mean > 0.35:
            flags.append("tempo_instability")
    if any(pulse.role is PulseRole.DOWNBEAT for pulse in accepted):
        if not any(pulse.role is PulseRole.BEAT for pulse in accepted):
            flags.append("downbeats_without_beats")
        if any(pulse.probability < 0.75 for pulse in accepted if pulse.role is PulseRole.DOWNBEAT):
            flags.append("weak_downbeat")
    if any(pulse.acceptance is PulseAcceptance.CANDIDATE for pulse in candidates):
        flags.append("candidates_present")
    return flags[:16]


def _diagnostics(
    accepted: list[DecodedPulse],
    candidates: list[DecodedPulse],
    profile: BeatDecoderProfile,
    beat_peaks: list[Fraction],
    downbeat_peaks: list[Fraction],
    project_sample_rate: int,
) -> dict[str, float | int | str]:
    intervals = [
        (right.source_frame - left.source_frame) / project_sample_rate
        for left, right in zip(accepted, accepted[1:], strict=False)
    ]
    median = sorted(intervals)[len(intervals) // 2] if intervals else 0.0
    return {
        "decoder_profile": profile.profile_id,
        "decoder_version": profile.version,
        "accepted_count": len(accepted),
        "candidate_count": len(candidates),
        "beat_peak_count": len(beat_peaks),
        "downbeat_peak_count": len(downbeat_peaks),
        "downbeat_count": sum(1 for pulse in accepted if pulse.role is PulseRole.DOWNBEAT),
        "median_interval_seconds": median,
        "min_interval_seconds": min(intervals) if intervals else 0.0,
        "max_interval_seconds": max(intervals) if intervals else 0.0,
    }


def _load_manifest_arrays(
    store: RhythmActivationStore, manifest: ActivationArtifactManifest
) -> tuple[np.ndarray, np.ndarray]:
    directory = store.artifact_dir(manifest.artifact_id)
    try:
        beat = np.load(directory / BEAT_FILE, allow_pickle=False)
        downbeat = np.load(directory / DOWNBEAT_FILE, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise RhythmDecodeError(f"cannot read activation artifact: {exc}") from exc
    return beat, downbeat


def decode_artifact(
    store: RhythmActivationStore,
    manifest: ActivationArtifactManifest,
    *,
    project_sample_rate: int,
    source_duration_frames: int,
    profile: BeatDecoderProfile = BEAT_THIS_DECODER_PROFILE,
) -> DecodedRhythmResult:
    """Decode one published activation artifact."""
    if not store.verify(manifest):
        raise RhythmDecodeError("activation artifact is missing or failed hash verification")
    beat, downbeat = _load_manifest_arrays(store, manifest)
    return decode_arrays(
        DecodeInput(
            artifact_id=manifest.artifact_id,
            content_hash=manifest.content_hash,
            frame_mapping=manifest.frame_mapping,
            beat=beat,
            downbeat=downbeat,
        ),
        project_sample_rate=project_sample_rate,
        source_duration_frames=source_duration_frames,
        profile=profile,
    )
