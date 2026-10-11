"""Separation run, result set, and stem records (M2.1, milestone2.md §3.2–3.4).

A *separation run* is one execution of the Demucs baseline on a project's
reference mix. It records the full input/model/engine identity and keeps
requested parameters separate from effective parameters so that
memory-recovery retries remain auditable.

A *result set* is the immutable output of a completed run: the aligned
stems plus reconstruction metrics and validation status. A result set is
*available* only once its required audio assets pass validation
(``validation_status == "valid"``).

A *stem* is one instrument output, keyed by the model's declared source
label (never a hard-coded tensor index), with its audio asset, timing,
project alignment, and confidence.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import (
    SamplePosition,
    SampleRate,
    Sha256Hash,
    UtcTimestamp,
    Uuid,
)
from basseparate.domain.confidence import Confidence


class SeparationMode(StrEnum):
    """The two separation modes in Milestone 2 (spec §2)."""

    BASS_PAIR = "bass_pair"
    FOUR_STEMS = "four_stems"


class SeparationRunStatus(StrEnum):
    """Run lifecycle. Mirrors the durable job state set (M1.4)."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ValidationStatus(StrEnum):
    """Whether a result set's required assets passed validation (spec §8.2)."""

    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class DeviceType(StrEnum):
    """Compute device for a separation run."""

    CPU = "cpu"
    CUDA = "cuda"


class StemRole(StrEnum):
    """Stem roles (spec §3.4, §8.4).

    ``vocals``/``drums``/``bass``/``other`` mirror the model's declared
    source labels (never a hard-coded tensor index). ``others`` is a
    publication-only role for the Bass + Others residual
    (``reference_mix − bass``), kept distinct from the model's ``other``
    stem.
    """

    VOCALS = "vocals"
    DRUMS = "drums"
    BASS = "bass"
    OTHER = "other"
    OTHERS = "others"


#: Maximum magnitude of a stem's project alignment offset, in frames.
#: Normally zero; the bound guards against corrupt or misaligned data.
MAX_ALIGNMENT_OFFSET_FRAMES = 1_000_000


class SourceIdentity(BaseModel):
    """The project source a separation was computed from (spec §3.3)."""

    model_config = ConfigDict(frozen=True)

    asset_id: Uuid
    source_hash: Sha256Hash
    sample_rate: SampleRate
    duration_frames: SamplePosition


class ReferenceMixIdentity(BaseModel):
    """The prepared reference mix fed to the model (spec §3.3, §6.1)."""

    model_config = ConfigDict(frozen=True)

    asset_id: Uuid
    hash: Sha256Hash
    transformation_hash: Sha256Hash


class SeparationRun(BaseModel):
    """One execution of the Demucs baseline (spec §3.2)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    project_id: Uuid
    input_asset_id: Uuid
    input_transform_hash: Sha256Hash
    requested_mode: SeparationMode
    model_manifest_id: Uuid
    model_manifest_hash: Sha256Hash
    engine_version: str = Field(min_length=1, max_length=128)
    adapter_version: str = Field(min_length=1, max_length=128)
    requested_parameters: dict[str, Any] = Field(default_factory=dict)
    effective_parameters: dict[str, Any] | None = Field(
        default=None,
        description="Parameters actually used; differs from requested after a "
        "memory-recovery retry, so both are retained for auditability",
    )
    random_seed: int = Field(default=0)
    device_type: DeviceType
    gpu_uuid: str | None = Field(default=None, min_length=1, max_length=128)
    runtime_versions: dict[str, str] = Field(default_factory=dict)
    started_at: UtcTimestamp | None = None
    ended_at: UtcTimestamp | None = None
    status: SeparationRunStatus = SeparationRunStatus.QUEUED
    result_set_id: Uuid | None = None
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, float] | None = Field(
        default=None,
        description="Timing and peak-memory metrics (e.g. wall_seconds, peak_mb)",
    )

    @model_validator(mode="after")
    def _check_device_and_result(self) -> SeparationRun:
        if self.device_type == DeviceType.CUDA and self.gpu_uuid is None:
            raise ValueError("a cuda run must record its gpu_uuid")
        if self.device_type == DeviceType.CPU and self.gpu_uuid is not None:
            raise ValueError("a cpu run must not record a gpu_uuid")
        if self.status == SeparationRunStatus.COMPLETED and self.result_set_id is None:
            raise ValueError("a completed run must reference its result set")
        if self.status != SeparationRunStatus.COMPLETED and self.result_set_id is not None:
            raise ValueError("only a completed run may reference a result set")
        if self.ended_at is not None and self.started_at is None:
            raise ValueError("ended_at requires started_at")
        return self


class SeparationResultSet(BaseModel):
    """The immutable output of a completed separation run (spec §3.3).

    A result set is *available* only once its required audio assets pass
    validation: a ``valid`` result set must reference at least one stem and
    carry a positive frame count.
    """

    model_config = ConfigDict(frozen=True)

    id: Uuid
    run_id: Uuid
    project_id: Uuid
    source: SourceIdentity
    output_sample_rate: SampleRate
    output_channel_count: int = Field(ge=1, le=8)
    output_frame_count: SamplePosition
    available_stem_roles: list[StemRole] = Field(default_factory=list)
    stem_ids: list[Uuid] = Field(default_factory=list)
    bass_residual_asset_id: Uuid | None = None
    reference_mix: ReferenceMixIdentity
    reconstruction_metrics: dict[str, float] | None = None
    validation_status: ValidationStatus = ValidationStatus.PENDING
    created_at: UtcTimestamp

    @model_validator(mode="after")
    def _check_roles_and_availability(self) -> SeparationResultSet:
        if len(set(self.available_stem_roles)) != len(self.available_stem_roles):
            raise ValueError("available_stem_roles must not contain duplicates")
        if (StemRole.OTHERS in self.available_stem_roles) != (
            self.bass_residual_asset_id is not None
        ):
            raise ValueError(
                "the others role and bass_residual_asset_id must be present together"
            )
        if self.validation_status == ValidationStatus.VALID:
            if not self.stem_ids:
                raise ValueError("a valid result set must reference at least one stem")
            if self.output_frame_count <= 0:
                raise ValueError("a valid result set must have a positive frame count")
        return self


class StemRecord(BaseModel):
    """One instrument output of a result set (spec §3.4)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    result_set_id: Uuid
    role: StemRole
    display_name: str = Field(min_length=1, max_length=80)
    audio_asset_id: Uuid
    sample_rate: SampleRate
    channel_count: int = Field(ge=1, le=8)
    channel_layout: str | None = Field(default=None, min_length=1, max_length=64)
    frame_count: SamplePosition
    alignment_offset_frames: int = Field(
        default=0,
        ge=-MAX_ALIGNMENT_OFFSET_FRAMES,
        le=MAX_ALIGNMENT_OFFSET_FRAMES,
        description="Project alignment offset in frames (normally zero)",
    )
    waveform_cache_asset_id: Uuid | None = None
    playback_representation_ids: list[Uuid] = Field(default_factory=list)
    confidence: Confidence
    provenance: dict[str, str] | None = Field(
        default=None,
        description="Decoder/model provenance (tool, versions, seed)",
    )
