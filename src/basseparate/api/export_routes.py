"""WAV stem export routes (M2.13, milestone2.md §15, §19.2).

Routes (all authenticated, loopback-only):

- POST /api/v1/projects/{project_id}/exports — start a WAV export job for
  the selected stems of an immutable result set. The response is the
  durable job record; long work never blocks the request (§19.2).
- GET  /api/v1/projects/{project_id}/exports — delivered export
  artifacts with their job state, so completed exports stay
  re-downloadable after a reload.
- GET  /api/v1/downloads/{artifact_id} — authenticated delivery of one
  completed artifact with ``Content-Disposition``.

Defaults follow the spec: the newest active result set, all of its
stems, 24-bit WAV at the source sample rate, normalization off
(§15.1–15.2). ``Idempotency-Key`` is honored like the other write
routes.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, cast
from urllib.parse import quote

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from basseparate.api.errors import (
    ExportArtifactNotFoundError,
    ExportSelectionError,
    IdempotencyConflictError,
    NoExportResultSetError,
    ProjectNotFoundError,
    ProjectNotReadyError,
    ResultSetNotFoundError,
)
from basseparate.api.idempotency import IdempotencyStore
from basseparate.domain.export import (
    ExportArtifact,
    ExportFormat,
    ExportNormalization,
)
from basseparate.domain.media_job import JobState, JobType, MediaJob
from basseparate.domain.project import ProjectRecord, ProjectStatus
from basseparate.domain.separation import StemRole, ValidationStatus
from basseparate.jobs import JobManager
from basseparate.storage import (
    ExportArtifactRepository,
    ProjectRepository,
    SeparationRepository,
    StoragePaths,
)

router = APIRouter(prefix="/api/v1")

#: One streamed chunk of a download response.
_CHUNK_SIZE = 1 << 20


class CreateExportRequest(BaseModel):
    """Export selection and options (spec §15.1–15.2)."""

    result_set_id: uuid.UUID | None = Field(
        default=None,
        description="Immutable result set to export; defaults to the project's "
        "active result set",
    )
    asset_ids: list[uuid.UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=16,
        description="Stem audio asset ids to export; defaults to every stem of "
        "the result set",
    )
    format: ExportFormat = Field(
        default=ExportFormat.WAV24,
        description="Output encoding (24-bit WAV by default)",
    )
    sample_rate: Literal[44100, 48000] | None = Field(
        default=None,
        description="Output sample rate; null keeps the source rate",
    )
    normalize: ExportNormalization = Field(
        default=ExportNormalization.OFF,
        description="Linked peak normalization to -1 dBFS across the selection; "
        "off by default",
    )


class ExportArtifactResponse(BaseModel):
    """One delivered export file with its job state."""

    artifact_id: uuid.UUID
    job_id: uuid.UUID
    job_state: JobState
    result_set_id: uuid.UUID
    stem_id: uuid.UUID
    asset_id: uuid.UUID
    role: StemRole
    format: ExportFormat
    sample_rate: int
    channel_count: int
    frame_count: int
    normalized: bool
    gain_db: float | None
    dither: str | None
    sha256: str
    byte_size: int
    download_filename: str
    created_at: str
    download_url: str


class ExportListingResponse(BaseModel):
    artifacts: list[ExportArtifactResponse]


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _separations(request: Request) -> SeparationRepository:
    return cast(SeparationRepository, request.app.state.separation_repository)


def _exports(request: Request) -> ExportArtifactRepository:
    return cast(ExportArtifactRepository, request.app.state.export_repository)


def _paths(request: Request) -> StoragePaths:
    return cast(StoragePaths, request.app.state.storage_paths)


def _manager(request: Request) -> JobManager:
    return cast(JobManager, request.app.state.job_manager)


def _idempotency_store(request: Request) -> IdempotencyStore:
    return cast(IdempotencyStore, request.app.state.idempotency_store)


def _require_ready_project(request: Request, project_id: uuid.UUID) -> ProjectRecord:
    project = _projects(request).get_project(project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    if project.status is not ProjectStatus.READY:
        raise ProjectNotReadyError()
    return project


def _artifact_response(artifact: ExportArtifact, job_state: JobState) -> ExportArtifactResponse:
    return ExportArtifactResponse(
        artifact_id=artifact.id,
        job_id=artifact.job_id,
        job_state=job_state,
        result_set_id=artifact.result_set_id,
        stem_id=artifact.stem_id,
        asset_id=artifact.audio_asset_id,
        role=artifact.role,
        format=artifact.format,
        sample_rate=artifact.sample_rate,
        channel_count=artifact.channel_count,
        frame_count=artifact.frame_count,
        normalized=artifact.normalized,
        gain_db=artifact.gain_db,
        dither=artifact.dither,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
        download_filename=artifact.download_filename,
        created_at=artifact.created_at.isoformat().replace("+00:00", "Z"),
        download_url=f"/api/v1/downloads/{artifact.id}",
    )


@router.post(
    "/projects/{project_id}/exports",
    response_model=MediaJob,
    status_code=status.HTTP_201_CREATED,
)
async def create_export(
    project_id: uuid.UUID, body: CreateExportRequest, request: Request
) -> MediaJob:
    """Start a WAV export job for the selected stems (spec §15.3.1–3)."""
    project = _require_ready_project(request, project_id)
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key:
        store = _idempotency_store(request)
        body_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        existing = store.get(idempotency_key)
        if existing is not None:
            if existing.body_hash != body_hash:
                raise IdempotencyConflictError()
            return cast(MediaJob, existing.payload)

    separations = _separations(request)
    if body.result_set_id is not None:
        detail = separations.get_result_set_detail(project_id, body.result_set_id)
        if detail is None:
            raise ResultSetNotFoundError(str(body.result_set_id))
    else:
        active = project.practice_state.active_result_set_id
        if active is not None:
            detail = separations.get_result_set_detail(project_id, active)
        else:
            detail = None
        if detail is None:
            raise NoExportResultSetError()
    result_set, _run, stems = detail
    if result_set.validation_status is not ValidationStatus.VALID:
        raise ExportSelectionError(
            "only a valid result set can be exported; this set is not available"
        )
    selected = list(stems)
    if body.asset_ids is not None:
        by_asset = {stem.audio_asset_id: stem for stem in stems}
        missing = [str(value) for value in body.asset_ids if value not in by_asset]
        if missing:
            raise ExportSelectionError(
                "the selection contains assets that are not stems of this "
                f"result set: {', '.join(missing)}"
            )
        wanted = set(body.asset_ids)
        selected = [stem for stem in stems if stem.audio_asset_id in wanted]
    if not selected:
        raise ExportSelectionError("the export selection contains no stems")

    job = await _manager(request).create_job(
        project_id,
        JobType.EXPORT,
        parameters={
            "result_set_id": str(result_set.id),
            "asset_ids": [str(stem.audio_asset_id) for stem in selected],
            "format": body.format.value,
            "target_sample_rate": body.sample_rate,
            "normalize": body.normalize.value,
        },
    )
    if idempotency_key:
        _idempotency_store(request).set(idempotency_key, body_hash, job)
    return job


@router.get("/projects/{project_id}/exports", response_model=ExportListingResponse)
async def list_exports(project_id: uuid.UUID, request: Request) -> ExportListingResponse:
    """Delivered export artifacts for a project, newest first."""
    _require_ready_project(request, project_id)
    entries = _exports(request).list_artifacts_with_job_state(project_id)
    return ExportListingResponse(
        artifacts=[_artifact_response(artifact, state) for artifact, state in entries]
    )


def _iter_file_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


@router.get("/downloads/{artifact_id}")
async def download_artifact(artifact_id: uuid.UUID, request: Request) -> StreamingResponse:
    """Authenticated download of one verified export (§19.2).

    The response carries ``Content-Disposition: attachment`` with the
    artifact's safe download filename, its exact byte length, and the
    content hash for verification.
    """
    artifact = _exports(request).get_artifact(artifact_id)
    if artifact is None:
        raise ExportArtifactNotFoundError(str(artifact_id))
    path = _paths(request).resolve_asset_path(artifact.relative_path)
    if not path.is_file():
        raise ExportArtifactNotFoundError(str(artifact_id), missing_file=True)
    filename = artifact.download_filename
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    headers = {
        "Content-Type": "audio/wav",
        "Content-Length": str(artifact.byte_size),
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        ),
        "X-Artifact-Id": str(artifact.id),
        "X-Content-Sha256": artifact.sha256,
    }
    return StreamingResponse(_iter_file_chunks(path), headers=headers)


__all__ = ["router", "CreateExportRequest", "ExportArtifactResponse", "ExportListingResponse"]
