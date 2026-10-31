"""Domain exception to HTTP mapping, installed once on the application."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from basseparate.api.models import InvalidRequest
from basseparate.api.uploads import UploadError
from basseparate.jobs import JobNotFound
from basseparate.media import MediaError, RangeError
from basseparate.projects import (
    ProjectAlreadyExists,
    ProjectError,
    ProjectNotFound,
    RevisionConflict,
)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RangeError)
    async def range_error(request: Request, error: RangeError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=416)

    @app.exception_handler(MediaError)
    async def media_error(request: Request, error: MediaError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(InvalidRequest)
    async def invalid_request(request: Request, error: InvalidRequest) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(UploadError)
    async def upload_error(request: Request, error: UploadError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(ProjectNotFound)
    async def project_not_found(request: Request, error: ProjectNotFound) -> JSONResponse:
        return JSONResponse({"detail": f"project {error.project_id} not found"}, status_code=404)

    @app.exception_handler(ProjectAlreadyExists)
    async def project_exists(request: Request, error: ProjectAlreadyExists) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(RevisionConflict)
    async def revision_conflict(request: Request, error: RevisionConflict) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(ProjectError)
    async def project_error(request: Request, error: ProjectError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=400)

    @app.exception_handler(JobNotFound)
    async def job_not_found(request: Request, error: JobNotFound) -> JSONResponse:
        return JSONResponse({"detail": f"job {error.job_id} not found"}, status_code=404)
