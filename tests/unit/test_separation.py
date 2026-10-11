"""Unit tests for the separation run/result-set/stem records (M2.1, spec §3.2–3.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from basseparate.domain import (
    MAX_ALIGNMENT_OFFSET_FRAMES,
    Confidence,
    ConfidenceKind,
    DeviceType,
    SeparationMode,
    SeparationResultSet,
    SeparationRun,
    SeparationRunStatus,
    SourceIdentity,
    StemRecord,
    StemRole,
    ValidationStatus,
)
from basseparate.domain.separation import ReferenceMixIdentity

NOW = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64


def _run(**overrides: object) -> SeparationRun:
    base: dict[str, object] = {
        "id": uuid4(),
        "project_id": uuid4(),
        "input_asset_id": uuid4(),
        "input_transform_hash": HASH,
        "requested_mode": SeparationMode.FOUR_STEMS,
        "model_manifest_id": uuid4(),
        "model_manifest_hash": HASH,
        "engine_version": "demucs-4.1.0",
        "adapter_version": "adapter-1",
        "device_type": DeviceType.CPU,
    }
    base.update(overrides)
    return SeparationRun(**base)


def _result_set(**overrides: object) -> SeparationResultSet:
    base: dict[str, object] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "project_id": uuid4(),
        "source": SourceIdentity(
            asset_id=uuid4(), source_hash=HASH, sample_rate=48_000, duration_frames=100_000
        ),
        "output_sample_rate": 48_000,
        "output_channel_count": 2,
        "output_frame_count": 100_000,
        "reference_mix": ReferenceMixIdentity(
            asset_id=uuid4(), hash=HASH, transformation_hash=HASH
        ),
        "created_at": NOW,
    }
    base.update(overrides)
    return SeparationResultSet(**base)


def _stem(**overrides: object) -> StemRecord:
    base: dict[str, object] = {
        "id": uuid4(),
        "result_set_id": uuid4(),
        "role": StemRole.BASS,
        "display_name": "Bass",
        "audio_asset_id": uuid4(),
        "sample_rate": 48_000,
        "channel_count": 2,
        "frame_count": 100_000,
        "confidence": Confidence(kind=ConfidenceKind.UNAVAILABLE),
    }
    base.update(overrides)
    return StemRecord(**base)


class TestEnums:
    def test_mode_values(self) -> None:
        assert {m.value for m in SeparationMode} == {"bass_pair", "four_stems"}

    def test_stem_role_values(self) -> None:
        assert {r.value for r in StemRole} == {"vocals", "drums", "bass", "other", "others"}

    def test_run_status_values(self) -> None:
        assert {s.value for s in SeparationRunStatus} == {
            "queued",
            "running",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
        }

    def test_validation_status_values(self) -> None:
        assert {s.value for s in ValidationStatus} == {"pending", "valid", "invalid"}


class TestSeparationRun:
    def test_defaults(self) -> None:
        run = _run()
        assert run.status == SeparationRunStatus.QUEUED
        assert run.requested_parameters == {}
        assert run.effective_parameters is None
        assert run.result_set_id is None
        assert run.gpu_uuid is None
        assert run.warnings == []
        assert run.metrics is None
        assert run.random_seed == 0

    def test_requested_and_effective_parameters_are_separate(self) -> None:
        run = _run(
            requested_parameters={"split": 8, "overlap": 0.25},
            effective_parameters={"split": 4, "overlap": 0.25},
        )
        assert run.requested_parameters["split"] == 8
        assert run.effective_parameters is not None
        assert run.effective_parameters["split"] == 4

    def test_cuda_requires_gpu_uuid(self) -> None:
        with pytest.raises(ValidationError, match="gpu_uuid"):
            _run(device_type=DeviceType.CUDA)

    def test_cuda_with_gpu_uuid_ok(self) -> None:
        run = _run(device_type=DeviceType.CUDA, gpu_uuid="GPU-1234")
        assert run.gpu_uuid == "GPU-1234"

    def test_cpu_forbids_gpu_uuid(self) -> None:
        with pytest.raises(ValidationError, match="cpu"):
            _run(device_type=DeviceType.CPU, gpu_uuid="GPU-1234")

    def test_completed_requires_result_set(self) -> None:
        with pytest.raises(ValidationError, match="result set"):
            _run(status=SeparationRunStatus.COMPLETED)

    def test_completed_with_result_set_ok(self) -> None:
        run = _run(status=SeparationRunStatus.COMPLETED, result_set_id=uuid4())
        assert run.result_set_id is not None

    def test_non_completed_forbids_result_set(self) -> None:
        with pytest.raises(ValidationError, match="completed"):
            _run(status=SeparationRunStatus.RUNNING, result_set_id=uuid4())

    def test_ended_at_requires_started_at(self) -> None:
        with pytest.raises(ValidationError, match="started_at"):
            _run(ended_at=NOW)

    def test_timestamps_ok(self) -> None:
        run = _run(started_at=NOW, ended_at=NOW)
        assert run.started_at == NOW
        assert run.ended_at == NOW


class TestSeparationResultSet:
    def test_defaults_pending(self) -> None:
        rs = _result_set()
        assert rs.validation_status == ValidationStatus.PENDING
        assert rs.stem_ids == []
        assert rs.bass_residual_asset_id is None
        assert rs.reconstruction_metrics is None

    def test_duplicate_roles_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            _result_set(available_stem_roles=[StemRole.BASS, StemRole.BASS])

    def test_others_role_requires_residual_asset(self) -> None:
        with pytest.raises(ValidationError, match="bass_residual_asset_id"):
            _result_set(available_stem_roles=[StemRole.BASS, StemRole.OTHERS])

    def test_residual_asset_requires_others_role(self) -> None:
        with pytest.raises(ValidationError, match="bass_residual_asset_id"):
            _result_set(bass_residual_asset_id=uuid4())

    def test_others_with_residual_asset_ok(self) -> None:
        residual_id = uuid4()
        rs = _result_set(
            available_stem_roles=[StemRole.BASS, StemRole.OTHERS],
            bass_residual_asset_id=residual_id,
        )
        assert StemRole.OTHERS in rs.available_stem_roles
        assert rs.bass_residual_asset_id == residual_id

    def test_valid_requires_stems(self) -> None:
        with pytest.raises(ValidationError, match="stem"):
            _result_set(validation_status=ValidationStatus.VALID)

    def test_valid_requires_positive_frame_count(self) -> None:
        with pytest.raises(ValidationError, match="frame count"):
            _result_set(
                validation_status=ValidationStatus.VALID,
                stem_ids=[uuid4()],
                output_frame_count=0,
            )

    def test_valid_with_stems_ok(self) -> None:
        rs = _result_set(validation_status=ValidationStatus.VALID, stem_ids=[uuid4()])
        assert rs.validation_status == ValidationStatus.VALID

    def test_pending_allows_no_stems(self) -> None:
        rs = _result_set(validation_status=ValidationStatus.PENDING)
        assert rs.stem_ids == []


class TestStemRecord:
    def test_defaults(self) -> None:
        stem = _stem()
        assert stem.alignment_offset_frames == 0
        assert stem.channel_layout is None
        assert stem.waveform_cache_asset_id is None
        assert stem.playback_representation_ids == []
        assert stem.provenance is None

    def test_alignment_offset_within_bounds_ok(self) -> None:
        stem = _stem(alignment_offset_frames=128)
        assert stem.alignment_offset_frames == 128

    def test_alignment_offset_too_large_rejected(self) -> None:
        with pytest.raises(ValidationError, match="alignment"):
            _stem(alignment_offset_frames=MAX_ALIGNMENT_OFFSET_FRAMES + 1)

    def test_alignment_offset_too_negative_rejected(self) -> None:
        with pytest.raises(ValidationError, match="alignment"):
            _stem(alignment_offset_frames=-(MAX_ALIGNMENT_OFFSET_FRAMES + 1))

    def test_channel_layout_present(self) -> None:
        stem = _stem(channel_layout="stereo")
        assert stem.channel_layout == "stereo"
