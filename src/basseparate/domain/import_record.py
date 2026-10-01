"""Import records and probe results (M1.1).

An import tracks one local media file being transferred into a project:
upload session, chunked transfer state, ffprobe result, selected audio
stream, and the processing jobs spawned from it.

The original filename is opaque user-visible metadata. It is never
interpreted as a server path.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from basseparate.domain.common import Sha256Hash, UtcTimestamp, Uuid

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_FILENAME_LENGTH = 512
MAX_ERROR_LENGTH = 2000
MAX_STREAMS_PROBED = 64


class TransferState(StrEnum):
    CREATED = "created"
    UPLOADING = "uploading"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    FAILED = "failed"


def _validate_filename(value: str) -> str:
    if not 1 <= len(value) <= MAX_FILENAME_LENGTH:
        raise ValueError(f"filename must be 1-{MAX_FILENAME_LENGTH} characters, got {len(value)}")
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError("filename must not contain embedded control characters")
    return value


class AudioStreamInfo(BaseModel):
    """One audio stream reported by ffprobe (global stream index)."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0, description="Global stream index in the container")
    codec: str = Field(min_length=1, max_length=64)
    sample_rate: int = Field(ge=1)
    channel_count: int = Field(ge=1)
    channel_layout: str | None = Field(default=None, min_length=1, max_length=64)
    language: str | None = Field(default=None, min_length=2, max_length=8)
    title: str | None = Field(default=None, max_length=200)
    is_default: bool = False
    estimated_duration_seconds: float | None = Field(default=None, ge=0)
    start_timestamp_seconds: float | None = Field(default=None, ge=0)


class ProbeResult(BaseModel):
    """Validated ffprobe output, reduced to the metadata we retain."""

    model_config = ConfigDict(frozen=True)

    format_name: str = Field(min_length=1, max_length=128)
    estimated_duration_seconds: float | None = Field(default=None, ge=0)
    byte_count: int = Field(ge=0)
    title: str | None = Field(default=None, max_length=200)
    artist: str | None = Field(default=None, max_length=200)
    ffmpeg_version: str = Field(min_length=1, max_length=128)
    ffprobe_version: str = Field(min_length=1, max_length=128)
    audio_streams: tuple[AudioStreamInfo, ...] = Field(default=(), max_length=MAX_STREAMS_PROBED)


class ImportRecord(BaseModel):
    """One import session targeting a single project."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    project_id: Uuid
    filename: str = Field(min_length=1, max_length=MAX_FILENAME_LENGTH)
    declared_byte_count: int = Field(ge=0)
    received_byte_count: int = Field(default=0, ge=0)
    source_sha256: Sha256Hash | None = None
    transfer_state: TransferState = TransferState.CREATED
    probe_result: ProbeResult | None = None
    selected_stream_index: int | None = Field(default=None, ge=0)
    job_ids: tuple[Uuid, ...] = Field(default=())
    error: str | None = Field(default=None, max_length=MAX_ERROR_LENGTH)
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    @field_validator("filename", mode="before")
    @classmethod
    def _validate_filename(cls, v: str) -> str:
        return _validate_filename(v)

    def model_post_init(self, __context: object) -> None:
        if self.received_byte_count > self.declared_byte_count:
            raise ValueError("received_byte_count must not exceed declared_byte_count")
        if self.transfer_state == TransferState.COMPLETE and self.source_sha256 is None:
            raise ValueError("a complete import must have a source_sha256")
        if (
            self.transfer_state == TransferState.COMPLETE
            and self.received_byte_count != self.declared_byte_count
        ):
            raise ValueError("a complete import must have received all declared bytes")
        if self.transfer_state in (TransferState.CANCELLED, TransferState.FAILED) and (
            self.error is None
        ):
            raise ValueError("cancelled/failed imports must record an error")
