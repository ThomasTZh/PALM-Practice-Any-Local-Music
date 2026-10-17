"""WAV stem export domain models and helpers (M2.13, milestone2.md §15).

An *export* turns the published stems of one immutable separation result
set into WAV files the user downloads. The job carries the selection and
options; the worker measures the sources, applies the linked
normalization gain and dither policy, encodes with FFmpeg, verifies the
result, and reports one :class:`ExportStemResult` per stem. The publisher
moves the verified files into managed export storage and records one
:class:`ExportArtifact` row per delivered file (§15.5).

Design rules encoded here:

- Formats: 16-bit, 24-bit (default), float32 (spec §15.2).
- Integer outputs get triangular dither when the float signal is
  reduced to integer PCM (spec §15.3.11); float32 output never dithers.
- Integer outputs refuse to clip: the integer full-scale bound is the
  largest magnitude exactly representable without clipping (spec
  §15.3.9–10).
- Download filenames are safe, deterministic, and unique per result set
  (spec §15.3.6); sanitizing a label never changes the source track.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from math import log10
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from basseparate.domain.common import (
    SamplePosition,
    SampleRate,
    Sha256Hash,
    UtcTimestamp,
    Uuid,
)
from basseparate.domain.separation import StemRole


class ExportFormat(StrEnum):
    """Output encodings (spec §15.2). ``wav24`` is the default."""

    WAV16 = "wav16"
    WAV24 = "wav24"
    WAV32F = "wav32f"


class ExportNormalization(StrEnum):
    """Normalization policy (spec §15.2). ``off`` is the default."""

    OFF = "off"
    LINKED_PEAK = "linked_peak"


#: The alternate output rates the API accepts (spec §15.2); the source
#: rate (``None``) is always the default.
ALTERNATE_EXPORT_SAMPLE_RATES = (44100, 48000)


@dataclass(frozen=True)
class ExportFormatSpec:
    """Encoding facts for one output format."""

    bytes_per_sample: int
    encoder: str
    depth_label: str
    #: Largest magnitude without clipping in the integer format; ``None``
    #: for float output, which cannot clip.
    integer_full_scale: float | None


_EXPORT_FORMAT_SPECS: dict[ExportFormat, ExportFormatSpec] = {
    ExportFormat.WAV16: ExportFormatSpec(
        bytes_per_sample=2,
        encoder="pcm_s16le",
        depth_label="16bit",
        integer_full_scale=32767 / 32768,
    ),
    ExportFormat.WAV24: ExportFormatSpec(
        bytes_per_sample=3,
        encoder="pcm_s24le",
        depth_label="24bit",
        integer_full_scale=8388607 / 8388608,
    ),
    ExportFormat.WAV32F: ExportFormatSpec(
        bytes_per_sample=4,
        encoder="pcm_f32le",
        depth_label="float32",
        integer_full_scale=None,
    ),
}


def export_format_spec(format: ExportFormat) -> ExportFormatSpec:
    """The encoding facts for ``format``."""
    return _EXPORT_FORMAT_SPECS[format]


def export_dither_for(format: ExportFormat) -> Literal["triangular"] | None:
    """The dither to apply when reducing to ``format`` (spec §15.3.11).

    Integer formats dither with the triangular method; float32 output
    keeps the samples as computed.
    """
    return None if format is ExportFormat.WAV32F else "triangular"


def normalize_gain_db(joint_peak: float) -> float | None:
    """The linked peak-normalization gain in dB (spec §15.2, §15.3.8).

    The selected stems share one gain that puts their joint peak at
    −1 dBFS. Silence maps to ``None`` (no gain is defined, and applying
    one would not change the samples).
    """
    if joint_peak <= 0.0:
        return None
    target = 10 ** (-1 / 20)  # −1 dBFS
    return 20.0 * log10(target / joint_peak)


_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_PART = 48


def sanitize_filename_part(value: str, *, fallback: str) -> str:
    """Reduce ``value`` to a safe filename part (spec §15.3.6).

    Only ``[A-Za-z0-9._-]`` survive; runs of anything else collapse to a
    single ``-``. An empty or fully-unsafe value becomes ``fallback``.
    """
    cleaned = _UNSAFE_FILENAME.sub("-", value.strip()).strip(".-_")
    return cleaned[:_MAX_FILENAME_PART] or fallback


def export_download_filename(
    *,
    label: str,
    role: StemRole,
    result_set_id: uuid.UUID,
    sample_rate: int,
    format: ExportFormat,
    collision_index: int = 0,
) -> str:
    """One deterministic download filename (spec §15.3.6, §15.3.15)."""
    stem = sanitize_filename_part(label, fallback=role.value)
    rate = f"{sample_rate / 1000:g}k"
    depth = export_format_spec(format).depth_label
    suffix = f"-{collision_index + 1}" if collision_index else ""
    return f"{stem}-{result_set_id.hex[:6]}-{rate}-{depth}{suffix}.wav"


def export_download_filenames(
    stems: list[tuple[uuid.UUID, str, StemRole]],
    *,
    result_set_id: uuid.UUID,
    sample_rate: int,
    format: ExportFormat,
) -> dict[uuid.UUID, str]:
    """Download filenames for a whole selection, unique within the set.

    ``stems`` is ``(stem_id, label, role)`` in selection order. The first
    use of a name is unsuffixed; collisions append ``-2``, ``-3``, …
    """
    names: dict[uuid.UUID, str] = {}
    used: set[str] = set()
    for stem_id, label, role in stems:
        collision = 0
        while True:
            candidate = export_download_filename(
                label=label,
                role=role,
                result_set_id=result_set_id,
                sample_rate=sample_rate,
                format=format,
                collision_index=collision,
            )
            if candidate not in used:
                break
            collision += 1
        used.add(candidate)
        names[stem_id] = candidate
    return names


class ExportStemResult(BaseModel):
    """Worker-reported outcome for one exported stem (M2.13 §15.3.14)."""

    model_config = ConfigDict(frozen=True)

    stem_id: Uuid
    audio_asset_id: Uuid
    role: StemRole
    format: ExportFormat
    sample_rate: SampleRate = Field(description="Output sample rate in Hz")
    channel_count: int = Field(ge=1, le=8)
    frame_count: SamplePosition = Field(description="Output frames (decoded)")
    source_frame_count: SamplePosition = Field(description="Frames read from the stem asset")
    normalized: bool
    gain_db: float | None = Field(
        default=None, description="Applied linked normalization gain, if any"
    )
    dither: Literal["triangular"] | None = None
    sha256: Sha256Hash
    byte_size: int = Field(ge=44)
    download_filename: str = Field(min_length=1, max_length=200)
    staging_path: str = Field(
        min_length=1,
        description="Absolute path of the staged WAV before publication",
    )


class ExportResult(BaseModel):
    """The completed export job's result payload (M2.13 §15.5)."""

    model_config = ConfigDict(frozen=True)

    result_set_id: Uuid
    artifacts: list[ExportStemResult] = Field(min_length=1)
    joint_peak: float = Field(ge=0.0, description="Joint peak of the selected stems")


class ExportArtifact(BaseModel):
    """A delivered export file (M2.13 §15.5), one row per stem."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    job_id: Uuid
    project_id: Uuid
    result_set_id: Uuid
    stem_id: Uuid
    audio_asset_id: Uuid
    role: StemRole
    format: ExportFormat
    sample_rate: SampleRate
    channel_count: int = Field(ge=1, le=8)
    frame_count: SamplePosition
    normalized: bool
    gain_db: float | None = None
    dither: Literal["triangular"] | None = None
    sha256: Sha256Hash
    byte_size: int = Field(ge=44)
    relative_path: Annotated[
        str, Field(pattern=r"^data/exports/[0-9a-f]{64}\.wav$")
    ] = Field(description="Workspace-relative managed storage path")
    download_filename: str = Field(min_length=1, max_length=200)
    created_at: UtcTimestamp
