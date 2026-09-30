"""Shared primitive types for basseparate domain models.

- UUID identifiers serialized as strings.
- UTC timestamps serialized in ISO 8601 form (``Z`` suffix).
- SHA-256 hashes as lowercase hexadecimal strings.
- Nonnegative integer revisions.
- Integer sample positions bounded to JavaScript's safe-integer range.
- Half-open intervals ``[start_sample, end_sample)``.

Milliseconds are never an authoritative stored timeline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictInt,
)

JS_SAFE_INTEGER_MAX = 9_007_199_254_740_991  # 2**53 - 1


def _validate_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        return UUID(value)
    raise ValueError(f"expected UUID, got {type(value).__name__}")


def _serialize_uuid(value: UUID) -> str:
    return str(value)


Uuid = Annotated[
    UUID,
    BeforeValidator(_validate_uuid),
    PlainSerializer(_serialize_uuid, return_type=str, when_used="json"),
    Field(description="UUID identifier, serialized as a string"),
]
Revision = Annotated[StrictInt, Field(ge=0, description="Nonnegative integer revision")]


def _validate_utc(value: object) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError(f"expected datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


def _serialize_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcTimestamp = Annotated[
    datetime,
    BeforeValidator(_validate_utc),
    PlainSerializer(_serialize_utc, return_type=str, when_used="json"),
    Field(description="UTC timestamp in ISO 8601 form"),
]

Sha256Hash = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{64}$", description="SHA-256 hash, lowercase hexadecimal"),
]

SamplePosition = Annotated[
    StrictInt,
    Field(
        ge=0,
        le=JS_SAFE_INTEGER_MAX,
        description="Integer source sample position (never milliseconds)",
    ),
]

SampleRate = Annotated[StrictInt, Field(ge=1, description="Sample rate in Hz")]


class HalfOpenInterval(BaseModel):
    """Half-open interval ``[start_sample, end_sample)`` in source samples."""

    model_config = ConfigDict(frozen=True)

    start_sample: SamplePosition
    end_sample: SamplePosition

    @property
    def length_samples(self) -> int:
        return self.end_sample - self.start_sample

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        start = self.start_sample
        end = self.end_sample
        if end < start:
            raise ValueError("end_sample must be >= start_sample in a half-open interval")
