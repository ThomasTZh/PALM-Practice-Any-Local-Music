"""Device records and qualification state (M2.2, milestone2.md §4.4).

A *device record* describes one analysis device the user may select: a GPU
(discovered via the driver) or the CPU fallback. It carries the facts the
UI needs to display a device list and the qualification state that decides
whether the device may be used for separation.

Devices are marked usable only after a full model test succeeds
(spec 4.2.8); until then their ``qualification_status`` is
``untested`` or ``failed``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from basseparate.domain.common import UtcTimestamp


class DeviceKind(StrEnum):
    """Kind of analysis device."""

    GPU = "gpu"
    CPU = "cpu"


class QualificationStatus(StrEnum):
    """Qualification state of a device for the analysis runtime.

    - ``untested``: no qualification has been recorded for this device with
      the current environment fingerprint.
    - ``qualified``: tensor, convolution, FFT, and a short model run all
      passed on this device.
    - ``failed``: a qualification attempt failed; the reason is recorded in
      ``unavailability_reason``.
    """

    UNTESTED = "untested"
    QUALIFIED = "qualified"
    FAILED = "failed"


#: Maximum length of a device display name as reported by the driver.
MAX_DEVICE_NAME_LENGTH = 128

#: Maximum length of a qualification detail / unavailability reason string.
MAX_QUALIFICATION_DETAIL_LENGTH = 500


class DeviceRecord(BaseModel):
    """One selectable analysis device (GPU or CPU).

    Invariants:
    - A ``qualified`` record must carry ``last_qualified_at``.
    - A ``failed`` record must carry ``unavailability_reason``.
    - A GPU record must carry ``vram_total_mib``; ``vram_free_mib`` is the
      last measured value and may be ``None`` until refreshed.
    - A CPU record carries no VRAM facts.
    """

    model_config = ConfigDict(frozen=True)

    kind: DeviceKind
    #: Stable identifier: the driver GPU UUID, or ``"cpu"`` for the CPU.
    identifier: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=MAX_DEVICE_NAME_LENGTH)
    vram_total_mib: int | None = Field(default=None, ge=0)
    #: Last measured free VRAM; refreshed before a job starts (spec 4.4).
    vram_free_mib: int | None = Field(default=None, ge=0)
    qualification_status: QualificationStatus = QualificationStatus.UNTESTED
    last_qualified_at: UtcTimestamp | None = None
    #: What the last qualification attempt checked (engine/wheel fingerprint).
    last_qualification_detail: str | None = Field(
        default=None, max_length=MAX_QUALIFICATION_DETAIL_LENGTH
    )
    #: Why an unqualified device cannot be used (driver, VRAM, test failure).
    unavailability_reason: str | None = Field(
        default=None, max_length=MAX_QUALIFICATION_DETAIL_LENGTH
    )

    @model_validator(mode="after")
    def _check_consistency(self) -> DeviceRecord:
        if self.kind is DeviceKind.GPU:
            if self.vram_total_mib is None:
                raise ValueError("a GPU device record requires vram_total_mib")
        else:
            if self.vram_total_mib is not None or self.vram_free_mib is not None:
                raise ValueError("a CPU device record carries no VRAM facts")
            if self.identifier != "cpu":
                raise ValueError("the CPU device record uses identifier 'cpu'")
        if (
            self.qualification_status is QualificationStatus.QUALIFIED
            and self.last_qualified_at is None
        ):
            raise ValueError("a qualified record requires last_qualified_at")
        if (
            self.qualification_status is QualificationStatus.FAILED
            and self.unavailability_reason is None
        ):
            raise ValueError("a failed record requires unavailability_reason")
        return self

    @property
    def is_usable(self) -> bool:
        """Whether this device may be selected for a separation job."""
        return self.qualification_status is QualificationStatus.QUALIFIED
