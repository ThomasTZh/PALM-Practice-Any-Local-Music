"""Device discovery, qualification store, and selection (M2.2, spec §4.4-4.5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.devices import (
    DeviceError,
    DeviceKind,
    DeviceRecord,
    DeviceSelection,
    DiscoveredGpu,
    NvidiaSmiError,
    QualificationEntry,
    QualificationStore,
    build_device_records,
    cpu_device_record,
    discover_gpus,
    gpu_device_record,
    record_qualification,
    refresh_free_vram,
    select_device,
)
from basseparate.domain import QualificationStatus

GPU_A = "GPU-aaaaaa-1111-4111-8111-aaaaaaaaaaaa"
GPU_B = "GPU-bbbbbb-2222-4222-8222-bbbbbbbbbbbb"

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _stub_nvidia_smi(rows: list[list[str]]):
    """Build a fake nvidia-smi runner returning fixed csv rows."""

    def run(args: list[str]) -> str:
        assert args[0] == "nvidia-smi"
        return "\n".join(",".join(row) for row in rows)

    return run


def _gpu_record(
    uuid: str, name: str, status: QualificationStatus = QualificationStatus.UNTESTED
) -> DeviceRecord:
    kwargs: dict[str, object] = {}
    if status is QualificationStatus.QUALIFIED:
        kwargs["last_qualified_at"] = NOW
    if status is QualificationStatus.FAILED:
        kwargs["unavailability_reason"] = "model test failed"
    return DeviceRecord(
        kind=DeviceKind.GPU,
        identifier=uuid,
        display_name=name,
        vram_total_mib=16376,
        vram_free_mib=8000,
        qualification_status=status,
        **kwargs,
    )


class TestDiscoverGpus:
    def test_parses_two_gpus_with_fresh_vram(self) -> None:
        run = _stub_nvidia_smi(
            [
                ["NVIDIA GeForce RTX 4080", GPU_A, "16376", "8123"],
                ["NVIDIA GeForce RTX 5060 Ti", GPU_B, "16311", "15000"],
            ]
        )
        gpus = discover_gpus(run)
        assert gpus == [
            DiscoveredGpu(GPU_A, "NVIDIA GeForce RTX 4080", 16376, 8123),
            DiscoveredGpu(GPU_B, "NVIDIA GeForce RTX 5060 Ti", 16311, 15000),
        ]

    def test_empty_output_means_no_gpu(self) -> None:
        assert discover_gpus(lambda args: "") == []

    def test_malformed_row_raises(self) -> None:
        with pytest.raises(NvidiaSmiError, match="unexpected nvidia-smi row"):
            discover_gpus(_stub_nvidia_smi([["only", "two"]]))

    def test_non_numeric_vram_raises(self) -> None:
        with pytest.raises(NvidiaSmiError, match="non-numeric"):
            discover_gpus(_stub_nvidia_smi([["GPU", GPU_A, "abc", "1024"]]))

    def test_runner_failure_raises(self) -> None:
        def broken(args: list[str]) -> str:
            raise NvidiaSmiError("nvidia-smi exited 9: no devices found")

        with pytest.raises(NvidiaSmiError):
            discover_gpus(broken)


class TestRefreshFreeVram:
    def test_pairs_fresh_vram_by_uuid(self) -> None:
        gpus = [
            DiscoveredGpu(GPU_A, "4080", 16376, 1000),
            DiscoveredGpu(GPU_B, "5060 Ti", 16311, 2000),
        ]
        run = _stub_nvidia_smi(
            [
                ["NVIDIA GeForce RTX 4080", GPU_A, "16376", "9000"],
                ["NVIDIA GeForce RTX 5060 Ti", GPU_B, "16311", "7000"],
            ]
        )
        refreshed = refresh_free_vram(gpus, run)
        assert [g.vram_free_mib for g in refreshed] == [9000, 7000]
        assert [g.uuid for g in refreshed] == [GPU_A, GPU_B]

    def test_drops_disappeared_gpu(self) -> None:
        gpus = [
            DiscoveredGpu(GPU_A, "4080", 16376, 1000),
            DiscoveredGpu(GPU_B, "5060 Ti", 16311, 2000),
        ]
        run = _stub_nvidia_smi([["NVIDIA GeForce RTX 4080", GPU_A, "16376", "9000"]])
        refreshed = refresh_free_vram(gpus, run)
        assert [g.uuid for g in refreshed] == [GPU_A]


class TestRecordBuilders:
    def test_gpu_without_entry_is_untested(self) -> None:
        gpu = DiscoveredGpu(GPU_A, "4080", 16376, 8123)
        record = gpu_device_record(gpu, None)
        assert record.qualification_status is QualificationStatus.UNTESTED
        assert record.is_usable is False

    def test_gpu_with_qualified_entry(self) -> None:
        gpu = DiscoveredGpu(GPU_A, "4080", 16376, 8123)
        entry = QualificationEntry(
            QualificationStatus.QUALIFIED, "2026-10-10T12:00:00Z", "torch 2.9.1+cu128", None
        )
        record = gpu_device_record(gpu, entry)
        assert record.is_usable is True
        assert record.last_qualified_at == NOW
        assert record.last_qualification_detail == "torch 2.9.1+cu128"

    def test_gpu_with_failed_entry(self) -> None:
        gpu = DiscoveredGpu(GPU_A, "4080", 16376, 8123)
        entry = QualificationEntry(
            QualificationStatus.FAILED, None, "oom", "model test failed: out of memory"
        )
        record = gpu_device_record(gpu, entry)
        assert record.is_usable is False
        assert record.unavailability_reason == "model test failed: out of memory"

    def test_build_device_records_appends_cpu_last(self) -> None:
        gpus = [DiscoveredGpu(GPU_A, "4080", 16376, 8123)]
        records = build_device_records(gpus, {})
        assert [r.kind for r in records] == [DeviceKind.GPU, DeviceKind.CPU]
        assert records[-1].identifier == "cpu"


class TestQualificationStore:
    def test_missing_file_means_no_entries(self, tmp_path: Path) -> None:
        store = QualificationStore(tmp_path / "devices.json")
        assert store.load() == {}

    def test_round_trip(self, tmp_path: Path) -> None:
        store = QualificationStore(tmp_path / "devices.json")
        entries = {
            GPU_A: QualificationEntry(
                QualificationStatus.QUALIFIED, "2026-10-10T12:00:00Z", "torch 2.9.1+cu128", None
            ),
            "cpu": QualificationEntry(
                QualificationStatus.FAILED, None, "slow", "model test failed"
            ),
        }
        store.save(entries)
        assert store.load() == entries

    def test_save_is_atomic_and_versioned(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.json"
        store = QualificationStore(path)
        store.save(
            {
                GPU_A: QualificationEntry(
                    QualificationStatus.QUALIFIED, "2026-10-10T12:00:00Z", "d", None
                )
            }
        )
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["version"] == 1
        assert set(document["devices"]) == {GPU_A}
        assert not path.with_suffix(".tmp").exists()

    def test_wrong_version_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.json"
        path.write_text(json.dumps({"version": 99, "devices": {}}), encoding="utf-8")
        with pytest.raises(DeviceError, match="unsupported version"):
            QualificationStore(path).load()

    def test_malformed_document_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "devices.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(DeviceError, match="malformed|cannot read"):
            QualificationStore(path).load()

    def test_record_qualification_success_then_failure(self, tmp_path: Path) -> None:
        store = QualificationStore(tmp_path / "devices.json")
        passed = record_qualification(store, GPU_A, True, "torch 2.9.1+cu128", now=NOW)
        assert passed.status is QualificationStatus.QUALIFIED
        assert passed.qualified_at == "2026-10-10T12:00:00Z"

        failed = record_qualification(store, GPU_A, False, "oom", now=NOW)
        assert failed.status is QualificationStatus.FAILED
        assert failed.reason == "oom"
        assert failed.qualified_at is None

        reloaded = store.load()
        assert reloaded[GPU_A].status is QualificationStatus.FAILED


class TestEnvironmentBoundary:
    def test_main_environment_is_torch_free(self) -> None:
        # Spec 4.1.2: the application environment must not require PyTorch;
        # inference runs in the isolated analysis environment only.
        with pytest.raises(ModuleNotFoundError):
            import torch  # noqa: F401

    def test_device_service_does_not_import_torch(self) -> None:
        import basseparate.devices

        source = Path(basseparate.devices.__file__).read_text(encoding="utf-8")
        assert "import torch" not in source
        assert "import demucs" not in source


class TestSelectDevice:
    def _records(self, a: QualificationStatus, b: QualificationStatus) -> list[DeviceRecord]:
        return [
            _gpu_record(GPU_A, "RTX 4080", a),
            _gpu_record(GPU_B, "RTX 5060 Ti", b),
            cpu_device_record(None),
        ]

    def test_no_preference_selects_first_qualified_gpu(self) -> None:
        records = self._records(QualificationStatus.QUALIFIED, QualificationStatus.UNTESTED)
        selection = select_device(records)
        assert selection.device is not None
        assert selection.device.identifier == GPU_A
        assert selection.reason is None
        assert selection.cpu_offered is False

    def test_skips_unqualified_gpu_in_order(self) -> None:
        records = self._records(QualificationStatus.FAILED, QualificationStatus.QUALIFIED)
        selection = select_device(records)
        assert selection.device is not None
        assert selection.device.identifier == GPU_B

    def test_no_qualified_gpu_offers_cpu_explicitly(self) -> None:
        records = self._records(QualificationStatus.UNTESTED, QualificationStatus.FAILED)
        selection = select_device(records)
        assert selection.device is None
        assert selection.cpu_offered is True
        assert selection.reason is None

    def test_no_gpus_at_all_still_offers_cpu(self) -> None:
        selection = select_device([cpu_device_record(None)])
        assert selection.device is None
        assert selection.cpu_offered is True

    def test_preferred_qualified_gpu_is_preserved(self) -> None:
        records = self._records(QualificationStatus.QUALIFIED, QualificationStatus.QUALIFIED)
        selection = select_device(records, preferred_identifier=GPU_B)
        assert selection.device is not None
        assert selection.device.identifier == GPU_B
        assert selection.reason is None

    def test_preferred_unqualified_gpu_is_not_silently_substituted(self) -> None:
        records = self._records(QualificationStatus.QUALIFIED, QualificationStatus.UNTESTED)
        selection = select_device(records, preferred_identifier=GPU_B)
        assert selection.device is None
        assert selection.cpu_offered is True
        assert (
            selection.reason
            == f"device '{GPU_B}' has not been qualified"
        )

    def test_preferred_failed_gpu_reports_stored_reason(self) -> None:
        records = self._records(QualificationStatus.QUALIFIED, QualificationStatus.FAILED)
        selection = select_device(records, preferred_identifier=GPU_B)
        assert selection.device is None
        assert selection.reason == "model test failed"

    def test_preferred_missing_gpu_is_reported(self) -> None:
        records = self._records(QualificationStatus.QUALIFIED, QualificationStatus.UNTESTED)
        selection = select_device(records, preferred_identifier="GPU-gone")
        assert selection.device is None
        assert selection.reason == "preferred device 'GPU-gone' is no longer present"

    def test_explicit_cpu_preference_selects_cpu(self) -> None:
        records = self._records(QualificationStatus.QUALIFIED, QualificationStatus.QUALIFIED)
        cpu = DeviceRecord(
            kind=DeviceKind.CPU,
            identifier="cpu",
            display_name="CPU",
            qualification_status=QualificationStatus.QUALIFIED,
            last_qualified_at=NOW,
        )
        records[-1] = cpu
        selection = select_device(records, preferred_identifier="cpu")
        assert selection.device is not None
        assert selection.device.kind is DeviceKind.CPU

    def test_explicit_cpu_preference_requires_qualified_cpu(self) -> None:
        records = self._records(QualificationStatus.FAILED, QualificationStatus.FAILED)
        selection = select_device(records, preferred_identifier="cpu")
        assert selection.device is None
        assert selection.reason is not None

    def test_selection_dataclass_defaults(self) -> None:
        selection = DeviceSelection()
        assert selection.device is None
        assert selection.cpu_offered is False
        assert selection.reason is None
