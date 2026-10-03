"""Durable media job routes (M1.4, M1.7).

Routes (all authenticated, loopback-only):
- GET  /api/v1/jobs/{job_id} — job state, progress, result
- GET  /api/v1/projects/{project_id}/jobs — list a project's jobs
- POST /api/v1/projects/{project_id}/jobs — create a job (201)
- POST /api/v1/jobs/{job_id}/cancel — request cancellation

Every job derives from a completed import. The ``probe``,
``canonical_decode``, ``monitoring_downmix``, and ``playback_rate`` job
types are fully executable; the remaining types are durably tracked and
fail with ``JOB_TYPE_NOT_IMPLEMENTED`` until their milestones land.
Creating a ``canonical_decode`` job requires the import to have a selected
audio stream (422 ``NO_STREAM_SELECTION`` otherwise). Creating a
``playback_rate`` job requires ``target_sample_rate`` (8000-192000 Hz);
the field is rejected for every other job type.
"""

from __future__ import annotations

import uuid
from typing import cast

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from basseparate.api.errors import (
    ImportNotFoundError,
    ImportStateError,
    JobNotFoundError,
    JobRequestError,
    MissingStreamSelection,
    ProjectNotFoundError,
)
from basseparate.domain.import_record import TransferState
from basseparate.domain.media_job import JobType, MediaJob
from basseparate.jobs import JobManager
from basseparate.storage import ImportRepository, JobRepository, ProjectRepository

router = APIRouter(prefix="/api/v1")


class CreateJobRequest(BaseModel):
    job_type: JobType
    #: The job reads its source file from this import.
    import_id: uuid.UUID
    #: Target sample rate in Hz; required for ``playback_rate`` jobs only.
    target_sample_rate: int | None = Field(default=None, ge=8000, le=192000)


class JobListResponse(BaseModel):
    jobs: list[MediaJob]


def _jobs(request: Request) -> JobRepository:
    return cast(JobRepository, request.app.state.job_repository)


def _manager(request: Request) -> JobManager:
    return cast(JobManager, request.app.state.job_manager)


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _imports(request: Request) -> ImportRepository:
    return cast(ImportRepository, request.app.state.import_repository)


@router.get("/jobs/{job_id}", response_model=MediaJob)
async def get_job(job_id: uuid.UUID, request: Request) -> MediaJob:
    job = _jobs(request).get_job(job_id)
    if job is None:
        raise JobNotFoundError(str(job_id))
    return job


@router.get("/projects/{project_id}/jobs", response_model=JobListResponse)
async def list_project_jobs(project_id: uuid.UUID, request: Request) -> JobListResponse:
    project = _projects(request).get_project(project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    return JobListResponse(jobs=_jobs(request).list_jobs_for_project(project_id))


@router.post(
    "/projects/{project_id}/jobs",
    response_model=MediaJob,
    status_code=status.HTTP_201_CREATED,
)
async def create_job(project_id: uuid.UUID, body: CreateJobRequest, request: Request) -> MediaJob:
    project = _projects(request).get_project(project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))

    import_record = _imports(request).get_import(body.import_id)
    if import_record is None:
        raise ImportNotFoundError(str(body.import_id))
    if import_record.project_id != project_id:
        raise ImportStateError("the import does not belong to this project")
    if import_record.transfer_state != TransferState.COMPLETE:
        raise ImportStateError(
            f"import is {import_record.transfer_state.value}; jobs require a completed import"
        )
    if (
        body.job_type is JobType.CANONICAL_DECODE
        and import_record.selected_stream_index is None
    ):
        raise MissingStreamSelection()
    if body.job_type is JobType.PLAYBACK_RATE and body.target_sample_rate is None:
        raise JobRequestError("playback_rate jobs require target_sample_rate (8000-192000 Hz)")
    if body.job_type is not JobType.PLAYBACK_RATE and body.target_sample_rate is not None:
        raise JobRequestError("target_sample_rate is only valid for playback_rate jobs")

    parameters = (
        {"target_sample_rate": body.target_sample_rate}
        if body.target_sample_rate is not None
        else None
    )
    job = await _manager(request).create_job(
        project_id=project_id,
        job_type=body.job_type,
        import_id=body.import_id,
        parameters=parameters,
    )
    _imports(request).add_job_id(body.import_id, job.id)
    return job


@router.post("/jobs/{job_id}/cancel", response_model=MediaJob)
async def cancel_job(job_id: uuid.UUID, request: Request) -> MediaJob:
    try:
        return await _manager(request).cancel_job(job_id)
    except KeyError as exc:
        raise JobNotFoundError(str(job_id)) from exc
