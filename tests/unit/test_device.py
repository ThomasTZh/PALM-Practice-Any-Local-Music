"""Domain invariants for device records (M2.2, spec §4.4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from basseparate.domain import DeviceKind, DeviceRecord, QualificationStatus

QUALIFIED_AT = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _gpu(**overrides: object) -> DeviceRecord:
    base: dict[str, object] = {
        "kind": DeviceKind.GPU,
        "identifier": "GPU-abc",
        "display_name": "NVIDIA GeForce RTX 4080",
        "vram_total_mib": 16376,
        "vram_free_mib": 8000,
        "qualification_status": QualificationStatus.UNTESTED,
    }
    base.update(overrides)
    return DeviceRecord(**base)


def _cpu(**overrides: object) -> DeviceRecord:
    base: dict[str, object] = {
        "kind": DeviceKind.CPU,
        "identifier": "cpu",
        "display_name": "CPU",
        "qualification_status": QualificationStatus.UNTESTED,
    }
    base.update(overrides)
    return DeviceRecord(**base)


class TestDeviceRecordInvariants:
    def test_gpu_requires_total_vram(self) -> None:
        with pytest.raises(ValidationError, match="vram_total_mib"):
            _gpu(vram_total_mib=None)

    def test_cpu_carries_no_vram_facts(self) -> None:
        with pytest.raises(ValidationError, match="no VRAM"):
            _cpu(vram_total_mib=4096)
        with pytest.raises(ValidationError, match="no VRAM"):
            _cpu(vram_free_mib=1024)

    def test_cpu_identifier_is_fixed(self) -> None:
        with pytest.raises(ValidationError, match="'cpu'"):
            _cpu(identifier="processor")

    def test_qualified_requires_timestamp(self) -> None:
        with pytest.raises(ValidationError, match="last_qualified_at"):
            _gpu(qualification_status=QualificationStatus.QUALIFIED)

    def test_failed_requires_reason(self) -> None:
        with pytest.raises(ValidationError, match="unavailability_reason"):
            _gpu(qualification_status=QualificationStatus.FAILED)

    def test_untested_needs_no_extras(self) -> None:
        record = _gpu()
        assert record.qualification_status is QualificationStatus.UNTESTED
        assert record.last_qualified_at is None
        assert record.unavailability_reason is None
        assert record.is_usable is False

    def test_qualified_is_usable(self) -> None:
        record = _gpu(
            qualification_status=QualificationStatus.QUALIFIED,
            last_qualified_at=QUALIFIED_AT,
            last_qualification_detail="torch 2.9.1+cu128",
        )
        assert record.is_usable is True

    def test_failed_is_not_usable(self) -> None:
        record = _gpu(
            qualification_status=QualificationStatus.FAILED,
            unavailability_reason="model test failed: out of memory",
        )
        assert record.is_usable is False

    def test_vram_values_must_be_nonnegative(self) -> None:
        with pytest.raises(ValidationError):
            _gpu(vram_free_mib=-1)

    def test_display_name_bounds(self) -> None:
        with pytest.raises(ValidationError):
            _gpu(display_name="")
        with pytest.raises(ValidationError):
            _gpu(display_name="x" * 129)

    def test_record_is_frozen(self) -> None:
        record = _gpu()
        with pytest.raises(ValidationError, match="frozen"):
            record.display_name = "Renamed"  # type: ignore[misc]

    def test_json_round_trip(self) -> None:
        record = _gpu(
            qualification_status=QualificationStatus.QUALIFIED,
            last_qualified_at=QUALIFIED_AT,
            last_qualification_detail="torch 2.9.1+cu128 / demucs 4.1.0",
        )
        payload = record.model_dump_json()
        restored = DeviceRecord.model_validate_json(payload)
        assert restored == record
        assert restored.last_qualified_at == QUALIFIED_AT
