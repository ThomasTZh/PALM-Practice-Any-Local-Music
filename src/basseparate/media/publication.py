"""Stem validation and publication transforms (M2.6, milestone2.md §8).

Turns staged model stems (44.1 kHz interleaved f32le) into validated
project-rate stem PCM, computes the four-stem reconstruction diagnostics,
and derives the Bass + Others residual.

Restore (spec §8.1):
- The pinned M1.7 SWR profile (``resample_playback``) resamples
  continuously back to the project rate; a byte-exact identity fast path
  applies when the project rate and channel count already match.
- Mono projects collapse the model's stereo output with the documented
  average ``(L + R) / 2`` (float64 intermediate, float32 output).
- Endpoint policy (the M2.4 convention): the resampler may round by at
  most ±2 frames, and the final output must match the project frame count
  exactly. Larger unexplained discrepancies are a failure — never a blind
  trim (§8.1.6–9).

Diagnostics (spec §8.3–8.4): ``reference_mix − Σ stems`` and
``reference_mix − bass`` are computed in bounded float64 chunks; the
residual is stored as float32 PCM and verified within float32 rounding.

All transforms are unit-gain and linear: no clipping, no normalization.
The §8.2 "no accidental clipping or normalization" property is enforced
structurally; ``max_amplitude`` is recorded as a monitoring diagnostic.
The main environment stays torch/demucs-free: numpy plus the M1.7 ffmpeg
driver only.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import shutil
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from basseparate.domain.asset import AssetRecord, AssetRole, AudioMetadata
from basseparate.domain.confidence import Confidence, ConfidenceKind
from basseparate.domain.media_job import JobState, JobType, MediaJob
from basseparate.domain.separation import (
    ReferenceMixIdentity,
    SeparationMode,
    SeparationResultSet,
    SeparationRun,
    SeparationRunStatus,
    SourceIdentity,
    StemRecord,
    StemRole,
    ValidationStatus,
)
from basseparate.media.decode import (
    DecodeFailedError,
    NonFiniteSamplesError,
    check_frame_alignment,
    validate_pcm,
)
from basseparate.media.derived import (
    DEFAULT_DERIVED_TIMEOUT_SECONDS,
    DerivedProgress,
    resample_playback,
)
from basseparate.media.preparation import ENDPOINT_TOLERANCE_FRAMES
from basseparate.storage import JobRepository, SeparationRepository

#: MIME type of raw f32le PCM assets (the M1 publisher convention).
PCM_ASSET_MEDIA_TYPE = "application/octet-stream"

#: WAVEFORM job states that suppress a duplicate queue for the same asset.
_WAVEFORM_LIVE_STATES = frozenset(
    {JobState.QUEUED, JobState.RUNNING, JobState.CANCELLING, JobState.COMPLETED}
)

#: Bounded read size for the float64 math passes.
_MATH_CHUNK_BYTES = 4 * 1024 * 1024

#: Residual verification tolerance: 4x the worst-case float32
#: quantization (0.5 ulp) of a difference bounded by the input peak
#: (spec §8.4.6).
_RESIDUAL_TOLERANCE_SCALE = 2.0**-22


class PublicationError(Exception):
    """Base error for stem publication failures."""


class RestoreFrameCountError(PublicationError):
    """The restored stem violates the documented endpoint policy."""


class StemsValidationError(PublicationError):
    """A staged stem failed the §8.2 validation checklist."""


class ResidualVerificationError(PublicationError):
    """The derived residual failed its float32 rounding verification."""


@dataclass(frozen=True)
class RestoredStemOutcome:
    """Validated output of a stem restore (the caller owns ``output_path``)."""

    output_path: Path
    content_hash: str
    frame_count: int
    channel_count: int
    max_amplitude: float
    pcm_byte_count: int
    endpoint_difference_frames: int
    #: Signed trailing-edge adjustment applied to hit the exact project
    #: frame count (the documented resampling rounding, spec §8.1.7).
    endpoint_correction_frames: int
    resampled: bool
    mono_collapsed: bool


@dataclass(frozen=True)
class StemValidation:
    """One stem's §8.2 validation facts (bytes observable in the file)."""

    role: str
    path: Path
    content_hash: str
    max_amplitude: float
    frame_count: int


@dataclass(frozen=True)
class ReconstructionDiagnostics:
    """Four-stem reconstruction error: ``reference_mix − Σ stems`` (§8.3)."""

    rms: float
    max_abs: float
    sample_count: int


@dataclass(frozen=True)
class ResidualOutcome:
    """Validated Bass + Others residual (the caller owns ``output_path``)."""

    output_path: Path
    content_hash: str
    max_amplitude: float
    frame_count: int
    pcm_byte_count: int
    verification_max_abs: float


def _residual_rounding_tolerance(peak: float) -> float:
    """Worst-case float32 rounding of the residual, scaled for safety."""
    return peak * _RESIDUAL_TOLERANCE_SCALE


def _frame_chunk_bytes(channel_count: int) -> int:
    """A read size holding a whole number of frames."""
    frames = _MATH_CHUNK_BYTES // (4 * channel_count)
    return frames * 4 * channel_count


def _frame_count(path: Path, channel_count: int, what: str) -> int:
    try:
        return check_frame_alignment(path.stat().st_size, channel_count)
    except (OSError, DecodeFailedError) as exc:
        raise PublicationError(f"{what}: {exc}") from exc


def _correct_endpoint_frames(
    path: Path, channel_count: int, target_frames: int
) -> int:
    """Align a restored stem's trailing edge to the project frame count.

    The pinned resampler can finish one or two frames early or late
    (spec §8.1.7, the documented endpoint rounding). Downstream mixing
    requires exact project timing, so a discrepancy inside the documented
    tolerance is corrected at the trailing edge only: a late endpoint is
    truncated, an early one holds the final frame. Returns the signed
    number of corrected frames (positive = trimmed).
    """
    frame_bytes = channel_count * 4
    current = _frame_count(path, channel_count, f"restored stem {path.name}")
    difference = current - target_frames
    if difference == 0:
        return 0
    with path.open("r+b") as handle:
        if difference > 0:
            handle.truncate(target_frames * frame_bytes)
        else:
            handle.seek((current - 1) * frame_bytes)
            last = handle.read(frame_bytes)
            handle.seek(0, 2)
            handle.write(last * (-difference))
    return difference


def _remove(*paths: Path | None) -> None:
    for path in paths:
        if path is not None:
            with contextlib.suppress(OSError):
                path.unlink()


def _collapse_stereo_to_mono(input_path: Path, output_path: Path) -> None:
    """Collapse stereo to mono with the documented average ``(L + R) / 2``.

    Float64 intermediate, float32 output; unit gain (spec §8.1.2).
    """
    with input_path.open("rb") as src, output_path.open("wb") as dst:
        while chunk := src.read(_MATH_CHUNK_BYTES):
            if len(chunk) % 8 != 0:
                raise PublicationError(
                    f"stereo input {input_path.name} is not sample-aligned"
                )
            block = np.frombuffer(chunk, dtype="<f4").astype(np.float64).reshape(-1, 2)
            mono = ((block[:, 0] + block[:, 1]) * 0.5).astype("<f4")
            dst.write(mono.tobytes())


def _reconstruction_pass(
    reference_path: Path,
    stem_paths: Sequence[Path],
    channel_count: int,
) -> tuple[float, float, int]:
    """Bounded float64 pass: ``reference_mix − Σ stems`` → (rms, max, n)."""
    chunk = _frame_chunk_bytes(channel_count)
    n_samples = 0
    sumsq = 0.0
    max_abs = 0.0
    with contextlib.ExitStack() as stack:
        ref_handle = stack.enter_context(reference_path.open("rb"))
        stem_handles = [stack.enter_context(p.open("rb")) for p in stem_paths]
        while True:
            ref_bytes = ref_handle.read(chunk)
            if not ref_bytes:
                break
            if len(ref_bytes) % (4 * channel_count) != 0:
                raise StemsValidationError(
                    f"reference {reference_path.name} is not frame-aligned "
                    f"for {channel_count} channels"
                )
            ref = np.frombuffer(ref_bytes, dtype="<f4").astype(np.float64).reshape(
                -1, channel_count
            )
            total = np.zeros_like(ref)
            for handle, path in zip(stem_handles, stem_paths, strict=True):
                stem_bytes = handle.read(chunk)
                if len(stem_bytes) != len(ref_bytes):
                    raise StemsValidationError(
                        f"stem {path.name} has a different length than the reference"
                    )
                total += np.frombuffer(stem_bytes, dtype="<f4").astype(np.float64).reshape(
                    -1, channel_count
                )
            err = ref - total
            n_samples += err.size
            sumsq += float(np.square(err).sum())
            block_max = float(np.abs(err).max())
            if block_max > max_abs:
                max_abs = block_max
    if n_samples == 0:
        raise StemsValidationError("reconstruction inputs are empty")
    return math.sqrt(sumsq / n_samples), max_abs, n_samples


def _write_residual(
    reference_path: Path,
    bass_path: Path,
    output_path: Path,
    channel_count: int,
) -> tuple[int, float]:
    """Write ``others = reference_mix − bass`` (float64 → float32, §8.4).

    Returns ``(frame_count, input_peak)`` where the peak bounds the
    difference magnitude.
    """
    chunk = _frame_chunk_bytes(channel_count)
    n_frames = 0
    peak = 0.0
    with contextlib.ExitStack() as stack:
        ref_handle = stack.enter_context(reference_path.open("rb"))
        bass_handle = stack.enter_context(bass_path.open("rb"))
        out = stack.enter_context(output_path.open("wb"))
        while True:
            ref_bytes = ref_handle.read(chunk)
            if not ref_bytes:
                break
            if len(ref_bytes) % (4 * channel_count) != 0:
                raise PublicationError(
                    f"reference {reference_path.name} is not frame-aligned "
                    f"for {channel_count} channels"
                )
            bass_bytes = bass_handle.read(chunk)
            if len(bass_bytes) != len(ref_bytes):
                raise PublicationError(
                    f"bass {bass_path.name} has a different length than the reference"
                )
            ref = np.frombuffer(ref_bytes, dtype="<f4").astype(np.float64)
            bass = np.frombuffer(bass_bytes, dtype="<f4").astype(np.float64)
            block_peak = max(float(np.abs(ref).max()), float(np.abs(bass).max()))
            if block_peak > peak:
                peak = block_peak
            out.write((ref - bass).astype("<f4").tobytes())
            n_frames += len(ref_bytes) // (4 * channel_count)
    if n_frames == 0:
        raise PublicationError("residual inputs are empty")
    return n_frames, peak


def _verify_residual(
    reference_path: Path,
    bass_path: Path,
    residual_path: Path,
    channel_count: int,
) -> float:
    """Max of ``reference_mix − (bass + residual)`` in float64 (§8.4.6)."""
    chunk = _frame_chunk_bytes(channel_count)
    max_abs = 0.0
    with contextlib.ExitStack() as stack:
        handles = [
            stack.enter_context(p.open("rb"))
            for p in (reference_path, bass_path, residual_path)
        ]
        while True:
            ref_bytes = handles[0].read(chunk)
            if not ref_bytes:
                break
            parts = []
            for handle in handles:
                part = handle.read(chunk) if handle is not handles[0] else ref_bytes
                if len(part) != len(ref_bytes):
                    raise PublicationError("residual verification inputs differ in length")
                parts.append(np.frombuffer(part, dtype="<f4").astype(np.float64))
            ref, bass, residual = parts
            err = ref - (bass + residual)
            block_max = float(np.abs(err).max())
            if block_max > max_abs:
                max_abs = block_max
    return max_abs


async def restore_stem_project_representation(
    *,
    source_path: Path,
    source_rate: int,
    source_channels: int,
    output_path: Path,
    target_rate: int,
    target_channels: int,
    target_frame_count: int,
    max_threads: int = 4,
    estimated_duration_seconds: float | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[DerivedProgress], None] | None = None,
    timeout_seconds: float = DEFAULT_DERIVED_TIMEOUT_SECONDS,
) -> RestoredStemOutcome:
    """Restore one staged stem to the project rate and channel count.

    The source is a staged model stem (interleaved f32le). On success
    ``output_path`` holds the validated project-rate PCM; on failure no
    staging file is left behind. The source file is never modified.

    A trailing frame-count difference inside the documented resampling
    endpoint rounding is corrected to the exact project count; larger
    discrepancies fail (spec §8.1.6-8).
    """
    if source_rate <= 0 or target_rate <= 0:
        raise PublicationError(
            f"sample rates must be positive, got source={source_rate} "
            f"target={target_rate}"
        )
    if not 1 <= target_channels <= 8:
        raise PublicationError(f"target channel count out of range: {target_channels}")
    if target_frame_count <= 0:
        raise PublicationError(f"target frame count must be positive, got {target_frame_count}")
    identity = source_rate == target_rate and source_channels == target_channels
    if source_channels != target_channels and not (
        source_channels == 2 and target_channels == 1
    ):
        raise PublicationError(
            f"unsupported channel conversion: {source_channels} -> {target_channels}"
        )

    # Pre-check the staged file (missing / misaligned fails fast).
    _frame_count(source_path, source_channels, f"staged stem {source_path.name}")

    intermediate: Path | None = None
    resampled = False
    endpoint_difference = 0
    try:
        if identity:
            # Byte-exact fast path: the model output is already the
            # project representation (unit gain, no resampling).
            shutil.copyfile(source_path, output_path)
        else:
            if target_channels == source_channels:
                outcome = await resample_playback(
                    source_path=source_path,
                    output_path=output_path,
                    source_rate=source_rate,
                    target_rate=target_rate,
                    channel_count=source_channels,
                    max_threads=max_threads,
                    estimated_duration_seconds=estimated_duration_seconds,
                    cancel_event=cancel_event,
                    on_progress=on_progress,
                    timeout_seconds=timeout_seconds,
                )
            else:
                # Mono project: resample the stereo stem, then collapse.
                intermediate = output_path.with_name(output_path.name + ".stereo.tmp")
                outcome = await resample_playback(
                    source_path=source_path,
                    output_path=intermediate,
                    source_rate=source_rate,
                    target_rate=target_rate,
                    channel_count=source_channels,
                    max_threads=max_threads,
                    estimated_duration_seconds=estimated_duration_seconds,
                    cancel_event=cancel_event,
                    on_progress=on_progress,
                    timeout_seconds=timeout_seconds,
                )
                await asyncio.to_thread(_collapse_stereo_to_mono, intermediate, output_path)
                intermediate.unlink()
                intermediate = None
            resampled = True
            endpoint_difference = outcome.endpoint_difference_frames
            if abs(endpoint_difference) > ENDPOINT_TOLERANCE_FRAMES:
                raise RestoreFrameCountError(
                    f"resampler endpoint difference {endpoint_difference} frames "
                    f"exceeds the documented ±{ENDPOINT_TOLERANCE_FRAMES}"
                )

        final_frames = _frame_count(
            output_path, target_channels, f"restored stem {output_path.name}"
        )
        endpoint_correction = 0
        if final_frames != target_frame_count:
            difference = final_frames - target_frame_count
            # Two resampling stages precede the restore (preparation and
            # restoration), each documented as +/- ENDPOINT_TOLERANCE_FRAMES.
            # Anything beyond that combined bound is an unexplained length
            # discrepancy, not rounding; never trim it blindly.
            if not resampled or abs(difference) > 2 * ENDPOINT_TOLERANCE_FRAMES:
                raise RestoreFrameCountError(
                    f"restored stem has {final_frames} frames; the project requires "
                    f"exactly {target_frame_count} (difference {difference}; documented "
                    f"endpoint rounding is +/-{ENDPOINT_TOLERANCE_FRAMES} per resample)"
                )
            endpoint_correction = _correct_endpoint_frames(
                output_path, target_channels, target_frame_count
            )
            final_frames = target_frame_count
        content_hash, max_amplitude = await asyncio.to_thread(
            validate_pcm, output_path, target_channels
        )
    except Exception:
        _remove(output_path, intermediate)
        raise

    return RestoredStemOutcome(
        output_path=output_path,
        content_hash=content_hash,
        frame_count=final_frames,
        channel_count=target_channels,
        max_amplitude=max_amplitude,
        pcm_byte_count=output_path.stat().st_size,
        endpoint_difference_frames=endpoint_difference,
        endpoint_correction_frames=endpoint_correction,
        resampled=resampled,
        mono_collapsed=source_channels == 2 and target_channels == 1,
    )


async def validate_stems(
    *,
    stems: Sequence[tuple[str, Path]],
    expected_roles: Sequence[str],
    frame_count: int,
    channel_count: int,
    sample_rate: int,
) -> tuple[StemValidation, ...]:
    """The §8.2 checklist over validated project-rate stem PCM files.

    Checks roles (complete, unique), frame count, channel alignment,
    finite samples, and records the content hash and ``max_amplitude``.
    The sample rate has no in-file representation in raw PCM: the caller
    records ``sample_rate`` (the project rate) on the published asset —
    it is the restore service's output attribute. Clipping /
    normalization cannot occur: every restore transform is unit-gain and
    linear, and ``max_amplitude`` monitors the property.
    """
    if sample_rate <= 0:
        raise PublicationError(f"sample rate must be positive, got {sample_rate}")
    if frame_count <= 0:
        raise PublicationError(f"frame count must be positive, got {frame_count}")
    roles = [role for role, _ in stems]
    expected = list(expected_roles)
    if sorted(roles) != sorted(expected):
        missing = sorted(set(expected) - set(roles))
        extra = sorted(set(roles) - set(expected))
        raise StemsValidationError(
            f"stem roles do not match: missing={missing} extra={extra} "
            f"(expected {sorted(expected)})"
        )

    results: list[StemValidation] = []
    for role, path in stems:
        try:
            frames = _frame_count(path, channel_count, f"stem {role}")
        except PublicationError as exc:
            raise StemsValidationError(str(exc)) from exc
        if frames != frame_count:
            raise StemsValidationError(
                f"stem {role}: {frames} frames, expected exactly {frame_count}"
            )
        try:
            content_hash, max_amplitude = await asyncio.to_thread(
                validate_pcm, path, channel_count
            )
        except (NonFiniteSamplesError, DecodeFailedError) as exc:
            raise StemsValidationError(f"stem {role}: {exc}") from exc
        results.append(
            StemValidation(
                role=role,
                path=path,
                content_hash=content_hash,
                max_amplitude=max_amplitude,
                frame_count=frames,
            )
        )
    return tuple(results)


async def compute_reconstruction_error(
    *,
    reference_path: Path,
    stem_paths: Sequence[Path],
    channel_count: int,
    expected_frame_count: int,
) -> ReconstructionDiagnostics:
    """Four-stem reconstruction error ``reference_mix − Σ stems`` (§8.3).

    Bounded float64 chunks; returns RMS and max over all samples. The raw
    four-stem output is not claimed exact — the diagnostics are recorded,
    not gated.
    """
    if not stem_paths:
        raise PublicationError("at least one stem is required")
    for path in (reference_path, *stem_paths):
        frames = _frame_count(path, channel_count, f"reconstruction input {path.name}")
        if frames != expected_frame_count:
            raise StemsValidationError(
                f"reconstruction input {path.name}: {frames} frames, "
                f"expected exactly {expected_frame_count}"
            )
    rms, max_abs, n_samples = await asyncio.to_thread(
        _reconstruction_pass, reference_path, tuple(stem_paths), channel_count
    )
    return ReconstructionDiagnostics(rms=rms, max_abs=max_abs, sample_count=n_samples)


async def derive_bass_residual(
    *,
    reference_path: Path,
    bass_path: Path,
    output_path: Path,
    channel_count: int,
    expected_frame_count: int,
) -> ResidualOutcome:
    """Derive the Bass + Others residual ``reference_mix − bass`` (§8.4).

    Bounded float64 chunks, stored as float32 PCM, then verified:
    ``reference_mix − (bass + residual)`` must stay within float32
    rounding of the input peak. On failure no staging file is left
    behind.
    """
    for path in (reference_path, bass_path):
        frames = _frame_count(path, channel_count, f"residual input {path.name}")
        if frames != expected_frame_count:
            raise PublicationError(
                f"residual input {path.name}: {frames} frames, "
                f"expected exactly {expected_frame_count}"
            )
    try:
        frame_count, peak = await asyncio.to_thread(
            _write_residual, reference_path, bass_path, output_path, channel_count
        )
        verification = await asyncio.to_thread(
            _verify_residual, reference_path, bass_path, output_path, channel_count
        )
        tolerance = _residual_rounding_tolerance(peak)
        if verification > tolerance:
            raise ResidualVerificationError(
                f"residual verification max {verification:.3e} exceeds the float32 "
                f"rounding tolerance {tolerance:.3e}"
            )
        content_hash, max_amplitude = await asyncio.to_thread(
            validate_pcm, output_path, channel_count
        )
    except Exception:
        _remove(output_path)
        raise

    return ResidualOutcome(
        output_path=output_path,
        content_hash=content_hash,
        max_amplitude=max_amplitude,
        frame_count=frame_count,
        pcm_byte_count=output_path.stat().st_size,
        verification_max_abs=verification,
    )


@dataclass(frozen=True)
class PublishedSeparationResult:
    """Everything committed by ``publish_separation_result`` (spec §8.7)."""

    run: SeparationRun
    result_set: SeparationResultSet
    stems: tuple[StemRecord, ...]
    assets: tuple[AssetRecord, ...]
    reconstruction: ReconstructionDiagnostics
    residual: ResidualOutcome | None
    waveform_jobs: tuple[MediaJob, ...]


def queue_stem_waveforms(
    job_repository: JobRepository,
    project_id: uuid.UUID,
    assets: Sequence[AssetRecord],
) -> list[MediaJob]:
    """Queue one WAVEFORM job per published stem asset (spec §8.7.5).

    The per-asset variant of the canonical auto-queue: a job is skipped
    while a live (queued/running/cancelling/completed) WAVEFORM job targets
    the same asset; a previously failed or cancelled build is retried.
    Returns the jobs that were queued.
    """
    queued: list[MediaJob] = []
    existing = job_repository.list_jobs_for_project(project_id)
    for asset in assets:
        target = str(asset.id)
        if any(
            job.job_type is JobType.WAVEFORM
            and job.state in _WAVEFORM_LIVE_STATES
            and job.parameters.get("asset_id") == target
            for job in existing
        ):
            continue
        job = job_repository.create_job(
            project_id=project_id,
            job_type=JobType.WAVEFORM,
            parameters={"asset_id": target},
        )
        existing = [*existing, job]  # a repeated asset id is queued once
        queued.append(job)
    return queued


def _stem_provenance(run: SeparationRun) -> dict[str, str]:
    return {
        "kind": "demucs",
        "engine_version": run.engine_version,
        "adapter_version": run.adapter_version,
        "model_manifest_hash": run.model_manifest_hash,
        "random_seed": str(run.random_seed),
        "device": run.device_type.value,
    }


def _move_to_asset_store(restored: Path, content_hash: str, asset_dir: Path) -> None:
    """Move a validated stem into ``<asset_dir>/<hash>.pcm`` (dedup by hash).

    Identical bytes imply an identical asset, so an existing file is kept
    and the staging copy dropped (the M1 publisher policy).
    """
    destination = asset_dir / f"{content_hash}.pcm"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(restored), str(destination))
    else:
        with contextlib.suppress(OSError):
            restored.unlink()


async def publish_separation_result(
    *,
    run: SeparationRun,
    staging_dir: Path,
    attempt_dir: Path,
    stem_labels: Sequence[str],
    reference_path: Path,
    source: SourceIdentity,
    sample_rate: int,
    duration_frames: int,
    channel_count: int,
    asset_dir: Path,
    separation_repository: SeparationRepository,
    #: Content-hash lookup so identical audio already in the store is
    #: reused (its asset id), not re-inserted under a fresh id.
    find_asset_by_hash: Callable[[str], AssetRecord | None] | None = None,
    cache_key: str | None = None,
    model_rate: int = 44_100,
    job_repository: JobRepository | None = None,
    max_threads: int = 4,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[DerivedProgress], None] | None = None,
    remove_staging: bool = True,
) -> PublishedSeparationResult:
    """Publish a completed separation run (spec §8.1–8.7).

    Orchestrates: restore every staged model stem to the project
    representation (``attempt_dir/<label>.pcm``, 44.1 kHz), the §8.2
    validation, the four-stem reconstruction diagnostics, the Bass +
    Others residual when ``requested_mode`` is ``bass_pair`` (the four
    model stems are always published; §8.5), moving the assets into the
    content-addressed store, the transactional repository publish, and
    the per-stem waveform queueing (§8.7.5–6: audio is available while
    the optional waveform preparation continues).

    ``cache_key`` (M2.7, §9.1) is the deterministic key of the
    separation request, computed by the caller via
    ``separation_cache.compute_cache_key``; it is stamped on both the
    completed run and the published result set so identical requests
    can be cached and coalesced.

    On success the staging is removed (``remove_staging``); on failure
    the staged stems are kept for diagnostics and no partial records are
    committed. The four model stems' labels are the model's declared
    source labels (never a hard-coded tensor index).
    """
    if run.status not in (SeparationRunStatus.QUEUED, SeparationRunStatus.RUNNING):
        raise PublicationError(f"run {run.id} is {run.status.value}, not in flight")
    if sample_rate <= 0 or duration_frames <= 0 or not 1 <= channel_count <= 8:
        raise PublicationError(
            f"invalid project geometry: rate={sample_rate} "
            f"frames={duration_frames} channels={channel_count}"
        )
    labels = list(stem_labels)
    if len(set(labels)) != len(labels) or not labels:
        raise PublicationError(f"stem labels must be non-empty and unique: {labels}")
    if run.requested_mode is SeparationMode.BASS_PAIR and StemRole.BASS.value not in labels:
        raise PublicationError("bass_pair mode requires the bass stem label")
    if not reference_path.is_file():
        raise PublicationError(f"reference mix PCM not found: {reference_path}")
    staged_paths = {label: attempt_dir / f"{label}.pcm" for label in labels}
    for path in staged_paths.values():
        if not path.is_file():
            raise PublicationError(f"staged stem is missing: {path}")

    restored_dir = staging_dir / "restored"
    restored_dir.mkdir(parents=True, exist_ok=True)
    restored: dict[str, RestoredStemOutcome] = {}
    try:
        # 1. Restore every model stem to the project representation.
        for label, path in staged_paths.items():
            restored[label] = await restore_stem_project_representation(
                source_path=path,
                source_rate=model_rate,
                source_channels=2,
                output_path=restored_dir / f"{label}.pcm",
                target_rate=sample_rate,
                target_channels=channel_count,
                target_frame_count=duration_frames,
                max_threads=max_threads,
                cancel_event=cancel_event,
                on_progress=on_progress,
            )

        # 2. The Bass + Others residual (§8.4), when requested.
        residual: ResidualOutcome | None = None
        if run.requested_mode is SeparationMode.BASS_PAIR:
            residual = await derive_bass_residual(
                reference_path=reference_path,
                bass_path=restored["bass"].output_path,
                output_path=restored_dir / "others.pcm",
                channel_count=channel_count,
                expected_frame_count=duration_frames,
            )

        # 3. The §8.2 validation checklist over all published stems.
        all_labels = [*labels, *(["others"] if residual is not None else [])]
        _validations = await validate_stems(
            stems=[(label, restored_dir / f"{label}.pcm") for label in all_labels],
            expected_roles=all_labels,
            frame_count=duration_frames,
            channel_count=channel_count,
            sample_rate=sample_rate,
        )

        # 4. Four-stem reconstruction diagnostics (§8.3).
        diagnostics = await compute_reconstruction_error(
            reference_path=reference_path,
            stem_paths=[restored_dir / f"{label}.pcm" for label in labels],
            channel_count=channel_count,
            expected_frame_count=duration_frames,
        )

        # 5. Move the validated PCM into the content-addressed store.
        now = datetime.now(UTC)
        assets: list[AssetRecord] = []
        assets_by_label: dict[str, AssetRecord] = {}
        for label in all_labels:
            stem_path = restored_dir / f"{label}.pcm"
            if label in restored:
                outcome = restored[label]
                _move_to_asset_store(stem_path, outcome.content_hash, asset_dir)
                content_hash, byte_count = outcome.content_hash, outcome.pcm_byte_count
            else:
                assert residual is not None
                _move_to_asset_store(stem_path, residual.content_hash, asset_dir)
                content_hash, byte_count = residual.content_hash, residual.pcm_byte_count
            existing = (
                find_asset_by_hash(content_hash)
                if find_asset_by_hash is not None
                else None
            )
            if existing is not None:
                # The content-addressed store already holds these bytes
                # (for example, the same recording separated in another
                # project). Reuse the existing row and id so the new
                # project links to it; a fresh id would collide on the
                # unique content hash and break the transactional publish.
                audio = existing.audio
                if (
                    existing.role is not AssetRole.STEM
                    or audio is None
                    or audio.sample_rate != sample_rate
                    or audio.channel_count != channel_count
                    or audio.frame_count != duration_frames
                ):
                    raise PublicationError(
                        f"existing asset {existing.id} for hash {content_hash} "
                        "does not match the project representation"
                    )
                asset = existing
            else:
                asset = AssetRecord(
                    id=uuid.uuid4(),
                    content_hash=content_hash,
                    role=AssetRole.STEM,
                    relative_path=f"data/assets/{content_hash}.pcm",
                    media_type=PCM_ASSET_MEDIA_TYPE,
                    byte_count=byte_count,
                    created_at=now,
                    audio=AudioMetadata(
                        sample_rate=sample_rate,
                        channel_count=channel_count,
                        frame_count=duration_frames,
                        sample_format="f32le",
                    ),
                )
            # Reused assets stay in the list: the repository ignores the
            # duplicate asset row and still links it to this project.
            assets.append(asset)
            assets_by_label[label] = asset

        # 6. The domain records.
        result_set_id = uuid.uuid4()
        stems: list[StemRecord] = []
        for label in all_labels:
            provenance = (
                {"kind": "bass_residual", "formula": "reference_mix - bass"}
                if label == "others"
                else _stem_provenance(run)
            )
            stems.append(
                StemRecord(
                    id=uuid.uuid4(),
                    result_set_id=result_set_id,
                    role=StemRole(label),
                    display_name=label.title(),
                    audio_asset_id=assets_by_label[label].id,
                    sample_rate=sample_rate,
                    channel_count=channel_count,
                    frame_count=duration_frames,
                    confidence=Confidence(kind=ConfidenceKind.UNAVAILABLE),
                    provenance=provenance,
                )
            )
        metrics: dict[str, float] = {
            "reconstruction_rms": diagnostics.rms,
            "reconstruction_max": diagnostics.max_abs,
        }
        if residual is not None:
            metrics["residual_reconstruction_max"] = residual.verification_max_abs
        result_set = SeparationResultSet(
            id=result_set_id,
            run_id=run.id,
            project_id=run.project_id,
            source=source,
            output_sample_rate=sample_rate,
            output_channel_count=channel_count,
            output_frame_count=duration_frames,
            available_stem_roles=[StemRole(label) for label in all_labels],
            stem_ids=[stem.id for stem in stems],
            bass_residual_asset_id=(
                assets_by_label["others"].id if residual is not None else None
            ),
            reference_mix=ReferenceMixIdentity(
                asset_id=source.asset_id,
                hash=source.source_hash,
                transformation_hash=run.input_transform_hash,
            ),
            reconstruction_metrics=metrics,
            validation_status=ValidationStatus.VALID,
            created_at=now,
            cache_key=cache_key,
        )
        # ``model_copy`` skips validation: a queued run never set
        # ``started_at``, so backfill it — a completed run must have both
        # timestamps (the domain validator would reject the record on
        # read-back otherwise).
        update: dict[str, object] = {
            "status": SeparationRunStatus.COMPLETED,
            "result_set_id": result_set_id,
            "ended_at": now,
        }
        if run.started_at is None:
            update["started_at"] = now
        if cache_key is not None:
            update["cache_key"] = cache_key
        completed_run = run.model_copy(update=update)

        # 7. The transactional publish (spec §8.7.1–4).
        separation_repository.publish_result_set(completed_run, result_set, stems, assets)

        # 8. Waveform queueing after the atomic publish (§8.7.5–6).
        waveform_jobs: list[MediaJob] = []
        if job_repository is not None:
            waveform_jobs = queue_stem_waveforms(job_repository, run.project_id, assets)
    except Exception:
        shutil.rmtree(restored_dir, ignore_errors=True)
        raise

    # 9. Staging cleanup on success only.
    if remove_staging:
        shutil.rmtree(staging_dir, ignore_errors=True)

    return PublishedSeparationResult(
        run=completed_run,
        result_set=result_set,
        stems=tuple(stems),
        assets=tuple(assets),
        reconstruction=diagnostics,
        residual=residual,
        waveform_jobs=tuple(waveform_jobs),
    )
