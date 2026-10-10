"""Analysis device discovery, qualification state, and selection (M2.2, §4.4-4.5).

This module lives in the *application* environment and never imports PyTorch.
GPU facts come from the driver via a short ``nvidia-smi`` subprocess; the
qualification *results* (produced by the isolated analysis environment,
``analysis/qualify.py``) are persisted as a JSON store under the data
directory and merged onto the discovered devices.

Selection rules (spec 4.5):
- a previously selected device is preserved by UUID, provided it is still
  present and qualified;
- otherwise the first qualified GPU in discovery order is selected;
- otherwise no accelerator is selected and the CPU is offered *explicitly*;
- a requested GPU that is missing or unqualified is reported, never
  silently substituted by the CPU.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from basseparate.domain.device import (
    DeviceKind,
    DeviceRecord,
    QualificationStatus,
)

#: JSON document version for the qualification store.
QUALIFICATION_STORE_VERSION = 1

_NVIDIA_SMI_TIMEOUT_SECONDS = 10.0


class DeviceError(RuntimeError):
    """Raised when device discovery or the qualification store is unusable."""


class NvidiaSmiError(DeviceError):
    """Raised when ``nvidia-smi`` is unavailable or returns bad output."""


@dataclass(frozen=True, slots=True)
class DiscoveredGpu:
    """One GPU as reported by the driver (fresh VRAM included)."""

    uuid: str
    name: str
    vram_total_mib: int
    vram_free_mib: int


@dataclass(frozen=True, slots=True)
class QualificationEntry:
    """Persisted result of one qualification attempt for a device."""

    status: QualificationStatus
    qualified_at: str | None  # ISO 8601 UTC, set when status == qualified
    detail: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class DeviceSelection:
    """Outcome of device selection.

    - ``device`` is set when an accelerator (or the CPU, on explicit
      preference) was selected.
    - ``cpu_offered`` is True when no accelerator is selected and the CPU
      may be offered to the user explicitly (spec 4.3.4).
    - ``reason`` explains why a *preferred* device was not selected; it is
      None on a clean selection.
    """

    device: DeviceRecord | None = None
    cpu_offered: bool = False
    reason: str | None = None


def _parse_csv_lines(output: str, expected_fields: int) -> list[list[str]]:
    rows = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != expected_fields:
            raise NvidiaSmiError(f"unexpected nvidia-smi row: {line!r}")
        rows.append(parts)
    return rows


def _query_gpus(run: Callable[[list[str]], str]) -> list[DiscoveredGpu]:
    output = run(
        [
            "nvidia-smi",
            "--query-gpu=name,uuid,memory.total,memory.free",
            "--format=csv,noheader,nounits",
        ]
    )
    gpus = []
    for name, uuid, total, free in _parse_csv_lines(output, 4):
        try:
            gpus.append(
                DiscoveredGpu(
                    uuid=uuid,
                    name=name,
                    vram_total_mib=int(total),
                    vram_free_mib=int(free),
                )
            )
        except ValueError as exc:
            raise NvidiaSmiError(f"non-numeric VRAM value in nvidia-smi output: {exc}") from exc
    return gpus


def _run_nvidia_smi(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NvidiaSmiError(f"nvidia-smi failed to run: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise NvidiaSmiError(f"nvidia-smi exited {completed.returncode}: {detail}")
    return completed.stdout


def discover_gpus(run: Callable[[list[str]], str] = _run_nvidia_smi) -> list[DiscoveredGpu]:
    """List GPUs with fresh total/free VRAM (spec 4.4: refresh before a job).

    An empty list means no usable NVIDIA GPU is present (driver absent or
    no device); that is a normal state, not an error.
    """
    return _query_gpus(run)


def refresh_free_vram(
    gpus: list[DiscoveredGpu], run: Callable[[list[str]], str] = _run_nvidia_smi
) -> list[DiscoveredGpu]:
    """Re-query current free VRAM, preserving discovery order.

    A GPU that disappeared since discovery is dropped; a new VRAM value is
    paired with the same UUID.
    """
    fresh = {gpu.uuid: gpu for gpu in _query_gpus(run)}
    return [fresh[gpu.uuid] for gpu in gpus if gpu.uuid in fresh]


def gpu_device_record(gpu: DiscoveredGpu, entry: QualificationEntry | None) -> DeviceRecord:
    """Merge a discovered GPU with its persisted qualification entry."""
    if entry is None:
        return DeviceRecord(
            kind=DeviceKind.GPU,
            identifier=gpu.uuid,
            display_name=gpu.name,
            vram_total_mib=gpu.vram_total_mib,
            vram_free_mib=gpu.vram_free_mib,
            qualification_status=QualificationStatus.UNTESTED,
        )
    return DeviceRecord(
        kind=DeviceKind.GPU,
        identifier=gpu.uuid,
        display_name=gpu.name,
        vram_total_mib=gpu.vram_total_mib,
        vram_free_mib=gpu.vram_free_mib,
        qualification_status=entry.status,
        last_qualified_at=(
            datetime.fromisoformat(entry.qualified_at.replace("Z", "+00:00"))
            if entry.qualified_at is not None
            else None
        ),
        last_qualification_detail=entry.detail,
        unavailability_reason=entry.reason,
    )


def cpu_device_record(entry: QualificationEntry | None) -> DeviceRecord:
    """The CPU fallback device (always present, never auto-selected)."""
    if entry is None:
        return DeviceRecord(
            kind=DeviceKind.CPU,
            identifier="cpu",
            display_name="CPU",
            qualification_status=QualificationStatus.UNTESTED,
        )
    return DeviceRecord(
        kind=DeviceKind.CPU,
        identifier="cpu",
        display_name="CPU",
        qualification_status=entry.status,
        last_qualified_at=(
            datetime.fromisoformat(entry.qualified_at.replace("Z", "+00:00"))
            if entry.qualified_at is not None
            else None
        ),
        last_qualification_detail=entry.detail,
        unavailability_reason=entry.reason,
    )


def select_device(
    records: list[DeviceRecord],
    preferred_identifier: str | None = None,
) -> DeviceSelection:
    """Select an analysis device (spec 4.5).

    ``records`` must contain the discovered GPUs in discovery order and,
    last, the CPU record. The CPU is returned only on an explicit
    ``preferred_identifier == "cpu"`` preference.
    """
    by_id = {record.identifier: record for record in records}
    cpu = by_id.get("cpu")

    if preferred_identifier is not None:
        preferred = by_id.get(preferred_identifier)
        if preferred is None:
            return DeviceSelection(
                cpu_offered=cpu is not None,
                reason=f"preferred device '{preferred_identifier}' is no longer present",
            )
        if not preferred.is_usable:
            reason = preferred.unavailability_reason
            if reason is None:
                reason = f"device '{preferred_identifier}' has not been qualified"
            return DeviceSelection(cpu_offered=cpu is not None, reason=reason)
        return DeviceSelection(device=preferred)

    for record in records:
        if record.kind is DeviceKind.GPU and record.is_usable:
            return DeviceSelection(device=record)

    return DeviceSelection(cpu_offered=cpu is not None)


class QualificationStore:
    """JSON persistence of qualification results under the data directory.

    The store is keyed by device identifier (GPU UUID or ``"cpu"``). It is
    written by the qualification step (after ``analysis/qualify.py`` runs)
    and read by the application to label devices. A missing file means
    "nothing qualified yet" and is never an error.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, QualificationEntry]:
        if not self._path.exists():
            return {}
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeviceError(f"cannot read qualification store {self._path}: {exc}") from exc
        if not isinstance(document, dict) or document.get("version") != QUALIFICATION_STORE_VERSION:
            raise DeviceError(
                f"qualification store {self._path} has unsupported version "
                f"(expected {QUALIFICATION_STORE_VERSION})"
            )
        entries: dict[str, QualificationEntry] = {}
        raw_devices = document.get("devices", {})
        if not isinstance(raw_devices, dict):
            raise DeviceError(f"qualification store {self._path} is malformed")
        for identifier, raw in raw_devices.items():
            if not isinstance(raw, dict):
                raise DeviceError(f"qualification store entry {identifier!r} is malformed")
            entries[str(identifier)] = QualificationEntry(
                status=QualificationStatus(str(raw.get("status", "untested"))),
                qualified_at=raw.get("qualified_at"),
                detail=raw.get("detail"),
                reason=raw.get("reason"),
            )
        return entries

    def save(self, entries: dict[str, QualificationEntry]) -> None:
        document = {
            "version": QUALIFICATION_STORE_VERSION,
            "devices": {
                identifier: {
                    "status": entry.status.value,
                    "qualified_at": entry.qualified_at,
                    "detail": entry.detail,
                    "reason": entry.reason,
                }
                for identifier, entry in sorted(entries.items())
            },
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self._path)


def record_qualification(
    store: QualificationStore,
    identifier: str,
    passed: bool,
    detail: str,
    now: datetime | None = None,
) -> QualificationEntry:
    """Persist one qualification result and return the stored entry.

    A failure overwrites a previous qualification (the device is no longer
    usable); a success records the timestamp used by the domain invariants.
    """
    entries = store.load()
    timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")
    if passed:
        entry = QualificationEntry(
            status=QualificationStatus.QUALIFIED,
            qualified_at=timestamp,
            detail=detail,
            reason=None,
        )
    else:
        entry = QualificationEntry(
            status=QualificationStatus.FAILED,
            qualified_at=None,
            detail=detail,
            reason=detail,
        )
    entries[identifier] = entry
    store.save(entries)
    return entry


def build_device_records(
    gpus: list[DiscoveredGpu],
    entries: dict[str, QualificationEntry],
) -> list[DeviceRecord]:
    """Merge discovery with the qualification store: GPUs first, then CPU."""
    records = [gpu_device_record(gpu, entries.get(gpu.uuid)) for gpu in gpus]
    records.append(cpu_device_record(entries.get("cpu")))
    return records
