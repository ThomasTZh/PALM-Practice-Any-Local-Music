"""Typed request boundaries and the pure validators behind them.

FastAPI's generated 422 responses cover shape errors; these validators add the
domain rules (absolute existing source path, bounded sample rate, job params)
so the route handlers only deal with valid input.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 384_000


class InvalidRequest(ValueError):
    """A request value is syntactically valid but not usable."""


def parse_source_path(raw: str) -> str:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"source path must be absolute, got {raw!r}")
    if not path.is_file():
        raise ValueError(f"source file does not exist: {path}")
    return str(path)


def validate_sample_rate_value(value: int | None) -> int | None:
    if value is None:
        return None
    if not MIN_SAMPLE_RATE <= value <= MAX_SAMPLE_RATE:
        raise InvalidRequest(
            f"sample rate must be between {MIN_SAMPLE_RATE} and {MAX_SAMPLE_RATE}, got {value}"
        )
    return value


def parse_sample_rate_text(raw: str | None) -> int | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw.strip(), 10)
    except ValueError as error:
        raise InvalidRequest(f"sample rate must be an integer, got {raw!r}") from error
    return validate_sample_rate_value(value)


class ImportPathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    name: str | None = Field(default=None, max_length=200)
    sample_rate: int | None = Field(default=None, ge=MIN_SAMPLE_RATE, le=MAX_SAMPLE_RATE)

    @field_validator("path")
    @classmethod
    def _absolute_existing_file(cls, value: str) -> str:
        return parse_source_path(value)


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: dict[str, Any] | None = None
    name: str | None = Field(default=None, max_length=200)
    revision: int | None = Field(default=None, ge=1)


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
