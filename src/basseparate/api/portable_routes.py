"""Portable project save routes (M2.15, milestone2.md §17, §19.2).

Routes (all authenticated, loopback-only):

- POST /api/v1/projects/{project_id}/portable-saves — capture the
  working project at its current revision into a ``.basseparate``
  archive and publish it to managed storage. This is pure file I/O, so
  the route runs synchronously in the FastAPI threadpool: no media job,
  no worker dispatch, one 201 response (§17.1). ``Idempotency-Key`` is
  honored like the other write routes.
- GET  /api/v1/projects/{project_id}/portable-saves — the project's
  portable saves (newest first), so the saved-through revision and the
  download link survive a reload (§17.5).
- GET  /api/v1/portable-downloads/{artifact_id} — authenticated
  streaming delivery of one published archive with
  ``Content-Disposition`` and its content hash.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from urllib.parse import quote

from fastapi import APIRouter, Request, status
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from basseparate.api.errors import (
    ApiError,
    IdempotencyConflictError,
    PortableArtifactNotFoundError,
    PortableSaveConflictError,
    ProjectNotFoundError,
)
from basseparate.api.idempotency import IdempotencyStore
from basseparate.domain.portable import PortableArtifact
from basseparate.domain.project import ProjectRecord
from basseparate.portable.save import (
    PortableSaveError,
    PortableSaveMissingAsset,
    PortableSaveNoSpace,
)
from basseparate.storage import (
    PortableArtifactRepository,
    ProjectRepository,
    StoragePaths,
)

router = APIRouter(prefix="/api/v1")

#: One streamed chunk of a download response.
_CHUNK_SIZE = 1 << 20

#: The save route has no request body; its idempotency body hash is the
#: hash of the empty body.
_EMPTY_BODY_HASH = hashlib.sha256(b"").hexdigest()


class PortableSaveResponse(BaseModel):
    """One published portable save with its download endpoint."""

    artifact_id: uuid.UUID
    project_id: uuid.UUID
    saved_revision: int
    sha256: str
    byte_size: int
    download_filename: str
    created_at: str
    download_url: str


class PortableSaveListingResponse(BaseModel):
    saves: list[PortableSaveResponse]


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _portables(request: Request) -> PortableArtifactRepository:
    return cast(PortableArtifactRepository, request.app.state.portable_repository)


def _paths(request: Request) -> StoragePaths:
    return cast(StoragePaths, request.app.state.storage_paths)


def _idempotency_store(request: Request) -> IdempotencyStore:
    return cast(IdempotencyStore, request.app.state.idempotency_store)


def _require_project(request: Request, project_id: uuid.UUID) -> ProjectRecord:
    project = _projects(request).get_project(project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    return project


def _save_response(artifact: PortableArtifact) -> PortableSaveResponse:
    return PortableSaveResponse(
        artifact_id=artifact.id,
        project_id=artifact.project_id,
        saved_revision=artifact.saved_revision,
        sha256=artifact.sha256,
        byte_size=artifact.byte_size,
        download_filename=artifact.download_filename,
        created_at=artifact.created_at.isoformat().replace("+00:00", "Z"),
        download_url=f"/api/v1/portable-downloads/{artifact.id}",
    )


def _map_save_error(exc: PortableSaveError) -> ApiError:
    if isinstance(exc, PortableSaveMissingAsset):
        return PortableSaveConflictError(exc.details)
    if isinstance(exc, PortableSaveNoSpace):
        return ApiError(
            code=exc.code,
            message=str(exc),
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            details=exc.details,
        )
    return ApiError(
        code=exc.code,
        message=str(exc),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        details=exc.details,
    )


@router.post(
    "/projects/{project_id}/portable-saves",
    response_model=PortableSaveResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_portable_save(project_id: uuid.UUID, request: Request) -> PortableSaveResponse:
    """Save the working project as a portable archive (spec §17.1).

    Synchronous by design: the save is file I/O only (archive, hash,
    atomic publish) and never blocks on media work, so it runs in the
    threadpool and returns the recorded artifact in one response.
    """
    from basseparate.portable.save import perform_portable_save

    project = _require_project(request, project_id)
    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key:
        store = _idempotency_store(request)
        existing = store.get(idempotency_key)
        if existing is not None:
            if existing.body_hash != _EMPTY_BODY_HASH:
                raise IdempotencyConflictError()
            return cast(PortableSaveResponse, existing.payload)

    try:
        artifact, _manifest = perform_portable_save(
            request.app.state.storage_paths.database_path,
            _paths(request),
            project,
            _portables(request),
        )
    except PortableSaveError as exc:
        raise _map_save_error(exc) from exc

    response = _save_response(artifact)
    if idempotency_key:
        _idempotency_store(request).set(idempotency_key, _EMPTY_BODY_HASH, response)
    return response


@router.get(
    "/projects/{project_id}/portable-saves", response_model=PortableSaveListingResponse
)
async def list_portable_saves(
    project_id: uuid.UUID, request: Request
) -> PortableSaveListingResponse:
    """The project's portable saves, newest first (spec §17.5)."""
    _require_project(request, project_id)
    saves = _portables(request).list_for_project(project_id)
    return PortableSaveListingResponse(saves=[_save_response(s) for s in saves])


def _iter_file_chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_SIZE)
            if not chunk:
                break
            yield chunk


@router.get("/portable-downloads/{artifact_id}")
async def download_portable_save(
    artifact_id: uuid.UUID, request: Request
) -> StreamingResponse:
    """Authenticated download of one published portable archive (§19.2).

    The response carries ``Content-Disposition: attachment`` with the
    artifact's safe download filename, its exact byte length, and the
    content hash for verification.
    """
    artifact = _portables(request).get(artifact_id)
    if artifact is None:
        raise PortableArtifactNotFoundError(str(artifact_id))
    path = _paths(request).resolve_asset_path(artifact.relative_path)
    if not path.is_file():
        raise PortableArtifactNotFoundError(str(artifact_id), missing_file=True)
    filename = artifact.download_filename
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    headers = {
        "Content-Type": "application/zip",
        "Content-Length": str(artifact.byte_size),
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        ),
        "X-Artifact-Id": str(artifact.id),
        "X-Content-Sha256": artifact.sha256,
    }
    return StreamingResponse(_iter_file_chunks(path), headers=headers)


__all__ = [
    "router",
    "PortableSaveResponse",
    "PortableSaveListingResponse",
]
