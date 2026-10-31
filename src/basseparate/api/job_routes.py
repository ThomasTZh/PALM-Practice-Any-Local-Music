"""Job routes: create, inspect, cancel and stream progress as SSE."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from basseparate.api.deps import JobsDep
from basseparate.api.import_routes import validate_job_params
from basseparate.api.models import JobCreateRequest
from basseparate.events import SSE_CONTENT_TYPE, sse_headers

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
def list_jobs(jobs: JobsDep) -> dict[str, Any]:
    return {"jobs": [job.to_dict() for job in jobs.list()]}


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_job(
    body: JobCreateRequest,
    jobs: JobsDep,
) -> dict[str, Any]:
    validate_job_params(body.kind, body.params)
    try:
        job = jobs.submit(body.kind, body.params)
    except KeyError as error:
        raise HTTPException(status_code=400, detail=f"unknown job kind {body.kind!r}") from error
    return job.to_dict()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, jobs: JobsDep) -> dict[str, Any]:
    return jobs.get(job_id).to_dict()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, jobs: JobsDep) -> dict[str, Any]:
    return jobs.cancel(job_id).to_dict()


@router.get("/jobs/{job_id}/events")
def job_events(job_id: str, jobs: JobsDep) -> StreamingResponse:
    jobs.get(job_id)  # 404 before the stream starts, not inside it
    return StreamingResponse(
        jobs.stream_events(job_id),
        media_type=SSE_CONTENT_TYPE,
        headers=sse_headers(),
    )


__all__ = ["router"]
