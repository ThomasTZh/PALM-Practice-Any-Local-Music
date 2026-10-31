"""Project documents and the atomic JSON store.

A project is a small JSON document: media facts plus the practice state that the
UI autosaves. Saves are atomic (write a temporary file in the same directory,
fsync, then ``os.replace``) and serialised per project with an advisory file
lock. A crash therefore leaves either the previous document or the new one,
never a half-written file; concurrent saves are ordered and revision-checked.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
import uuid
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from basseparate.peaks import PEAK_HEADER_SIZE

PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ProjectError(Exception):
    """Base class for project store failures that map to HTTP errors."""


class ProjectNotFound(ProjectError, KeyError):
    """No project with that id exists."""

    def __init__(self, project_id: str) -> None:
        super().__init__(project_id)
        self.project_id = project_id


class ProjectAlreadyExists(ProjectError):
    pass


class RevisionConflict(ProjectError):
    def __init__(self, project_id: str, expected: int, actual: int) -> None:
        super().__init__(
            f"project {project_id} changed: expected revision {expected}, current revision {actual}"
        )
        self.project_id = project_id
        self.expected = expected
        self.actual = actual


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_project_id(project_id: str) -> str:
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ValueError(f"project id {project_id!r} is not a safe slug")
    return project_id


class PeakInfo(BaseModel):
    bucket_size: int
    count: int
    channels: int
    frames: int
    byte_size: int


class AudioInfo(BaseModel):
    asset_id: str
    sample_rate: int
    channels: int
    frames: int
    duration_seconds: float
    content_sha256: str
    source_name: str
    source_format: str
    codec: str = "unknown"
    peaks: dict[str, PeakInfo] = Field(default_factory=dict)


class Project(BaseModel):
    """Canonical project document; unknown keys are preserved for later tasks."""

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    id: str
    name: str
    created_at: str
    updated_at: str
    revision: int = 1
    audio: AudioInfo
    document: dict[str, Any] = Field(default_factory=dict)


def build_audio_info(
    *,
    asset_id: str,
    source_name: str,
    source_format: str,
    sample_rate: int,
    channels: int,
    frames: int,
    content_sha256: str,
    peak_counts: Mapping[int, int],
    codec: str = "unknown",
) -> AudioInfo:
    if sample_rate <= 0:
        raise ValueError("sample rate must be positive")
    if frames < 0:
        raise ValueError("frame count must not be negative")
    peaks = {
        str(bucket): PeakInfo(
            bucket_size=bucket,
            count=count,
            channels=channels,
            frames=frames,
            byte_size=PEAK_HEADER_SIZE + count * channels * 4,
        )
        for bucket, count in sorted(peak_counts.items())
    }
    return AudioInfo(
        asset_id=asset_id,
        sample_rate=sample_rate,
        channels=channels,
        frames=frames,
        duration_seconds=frames / sample_rate,
        content_sha256=content_sha256,
        source_name=source_name,
        source_format=source_format,
        codec=codec,
        peaks=peaks,
    )


def build_project(
    audio: AudioInfo,
    *,
    name: str,
    project_id: str | None = None,
    now: str | None = None,
) -> Project:
    identifier = project_id if project_id is not None else uuid.uuid4().hex
    validate_project_id(identifier)
    timestamp = now if now is not None else utc_now()
    clean_name = name.strip() or "Untitled"
    return Project(
        id=identifier,
        name=clean_name,
        created_at=timestamp,
        updated_at=timestamp,
        revision=1,
        audio=audio,
        document={},
    )


def project_response(project: Project) -> dict[str, Any]:
    """JSON payload for the API: canonical fields plus the UI's camelCase aliases."""
    audio = project.audio
    payload = project.model_dump(mode="json")
    peaks = {
        bucket: {
            "bucketSize": info.bucket_size,
            "bucket_size": info.bucket_size,
            "count": info.count,
            "channels": info.channels,
            "frames": info.frames,
            "byteSize": info.byte_size,
        }
        for bucket, info in audio.peaks.items()
    }
    payload.update(
        {
            "title": project.name,
            "duration_seconds": audio.duration_seconds,
            "durationSeconds": audio.duration_seconds,
            "asset": {
                "id": audio.asset_id,
                "title": project.name,
                "durationSeconds": audio.duration_seconds,
                "duration_seconds": audio.duration_seconds,
                "sampleRate": audio.sample_rate,
                "sample_rate": audio.sample_rate,
                "channels": audio.channels,
                "frames": audio.frames,
                "peaks": peaks,
            },
            "grid": project.document.get("grid"),
            "key": project.document.get("key"),
            "stems": project.document.get("stems", []),
        }
    )
    return payload


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    data = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class ProjectStore:
    """Atomic, revisioned JSON documents in one directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._locks = self.directory / ".locks"
        self._locks.mkdir(exist_ok=True)

    def _path(self, project_id: str) -> Path:
        return self.directory / f"{validate_project_id(project_id)}.json"

    @contextlib.contextmanager
    def _lock(self, project_id: str) -> Iterator[None]:
        validate_project_id(project_id)
        descriptor = os.open(self._locks / f"{project_id}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def create(self, project: Project) -> Project:
        path = self._path(project.id)
        with self._lock(project.id):
            if path.exists():
                raise ProjectAlreadyExists(f"project {project.id} already exists")
            _write_json_atomic(path, project.model_dump(mode="json"))
        return project

    def get(self, project_id: str) -> Project:
        path = self._path(project_id)
        try:
            payload = json.loads(path.read_text("utf-8"))
        except FileNotFoundError as error:
            raise ProjectNotFound(project_id) from error
        except (OSError, json.JSONDecodeError) as error:
            raise ProjectError(f"cannot read project {project_id}: {error}") from error
        try:
            return Project.model_validate(payload)
        except ValueError as error:
            raise ProjectError(f"project {project_id} is invalid: {error}") from error

    def list(self) -> list[Project]:
        projects: list[Project] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                projects.append(self.get(path.stem))
            except ProjectError:
                continue
        return projects

    def save(self, project: Project, *, expected_revision: int | None = None) -> Project:
        """Write ``project``, bumping its revision under the per-project lock."""
        path = self._path(project.id)
        with self._lock(project.id):
            current: Project | None = None
            if path.exists():
                try:
                    current = Project.model_validate(json.loads(path.read_text("utf-8")))
                except (OSError, ValueError) as error:
                    raise ProjectError(f"cannot read project {project.id}: {error}") from error
            actual = current.revision if current is not None else 0
            if expected_revision is not None and expected_revision != actual:
                raise RevisionConflict(project.id, expected_revision, actual)
            updated = project.model_copy(update={"revision": actual + 1, "updated_at": utc_now()})
            _write_json_atomic(path, updated.model_dump(mode="json"))
            return updated

    def update(
        self,
        project_id: str,
        *,
        name: str | None = None,
        document: Mapping[str, Any] | None = None,
        expected_revision: int | None = None,
    ) -> Project:
        project = self.get(project_id)
        if name is not None:
            clean = name.strip()
            if not clean:
                raise ProjectError("project name must not be empty")
            project = project.model_copy(update={"name": clean})
        if document is not None:
            project = project.model_copy(update={"document": dict(document)})
        return self.save(project, expected_revision=expected_revision)

    def delete(self, project_id: str) -> None:
        path = self._path(project_id)
        with self._lock(project_id):
            try:
                path.unlink()
            except FileNotFoundError as error:
                raise ProjectNotFound(project_id) from error
