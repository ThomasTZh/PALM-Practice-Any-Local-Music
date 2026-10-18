"""Portable project open routes (M2.16, spec §18.1).

Open sessions carry a ``.basseparate`` archive over the same bounded,
chunked transfer protocol as media imports, but they are not tied to a
project until the import commits, so they have no database rows:

- POST /api/v1/projects/open — create a session (filename, declared
  size, open mode, optional new name). A declared size over the archive
  cap is 413 ``ARCHIVE_SIZE_LIMIT``; a failed space reservation is 507.
- PUT  /api/v1/projects/open/{id}/chunks?offset=… — the import chunk
  protocol (sequential offsets, ``X-Chunk-SHA256``, idempotent replay).
- POST /api/v1/projects/open/{id}/complete — run the §18 open pipeline
  (validation, staged extraction, untrusted DB, remap, restore, one
  transaction). The blocking work runs in the threadpool; failure keeps
  the session so the client may retry.
- GET  /api/v1/projects/open/{id} — transfer state and last error.
- POST /api/v1/projects/open/{id}/cancel — remove the session (idempotent).

Session metadata is a small JSON file beside the upload part/manifest,
so the session survives a restart exactly like a media upload session.
It is removed on success and on cancel; no archive bytes are kept after
a successful open.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from basseparate.api.errors import (
    ApiError,
    ArchiveBadFilenameError,
    ArchiveSizeLimitError,
    ChunkConflictError,
    ChunkSizeError,
    OffsetMismatchError,
    OpenIdConflictError,
    OpenNoSpaceError,
    OpenSessionIncompleteError,
    OpenSessionNotFoundError,
    OpenSessionStateError,
)
from basseparate.portable.errors import (
    PortableOpenError,
    PortableOpenIdConflict,
    PortableOpenNoSpace,
)
from basseparate.portable.open import open_portable_archive
from basseparate.storage import ProjectRepository
from basseparate.storage.paths import StoragePaths
from basseparate.uploads import (
    ChunkAck,
    ImportSessionNotFoundError,
    InsufficientSpaceError,
    UploadError,
    UploadManager,
)
from basseparate.uploads import ChunkConflictError as UploadChunkConflictError
from basseparate.uploads import ChunkSizeError as UploadChunkSizeError
from basseparate.uploads import OffsetMismatchError as UploadOffsetMismatchError

router = APIRouter(prefix="/api/v1")

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ARCHIVE_SUFFIX = ".basseparate"
_MAX_FILENAME_LENGTH = 512
_MAX_PROJECT_NAME_LENGTH = 200

OpenMode = Literal["new-copy", "as-archived"]


# ---------------------------------------------------------------------------
# Session metadata (durable, no database rows)
# ---------------------------------------------------------------------------


class OpenSessionMetadata(BaseModel):
    """One open session's client-supplied parameters and last error."""

    session_id: uuid.UUID
    filename: str
    declared_byte_count: int = Field(ge=1)
    open_mode: OpenMode = "new-copy"
    project_name: str | None = None
    last_error: str | None = None


class OpenSessionStore:
    """Reads and writes ``<session>.open.json`` beside the upload files."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _path(self, session_id: uuid.UUID) -> Path:
        return self._directory / f"{session_id}.open.json"

    def save(self, metadata: OpenSessionMetadata) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._path(metadata.session_id)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(metadata.model_dump_json())
        tmp.replace(path)

    def load(self, session_id: uuid.UUID) -> OpenSessionMetadata | None:
        path = self._path(session_id)
        if not path.is_file():
            return None
        try:
            return OpenSessionMetadata.model_validate_json(path.read_text())
        except ValueError:
            return None

    def record_error(self, metadata: OpenSessionMetadata, message: str) -> None:
        self.save(metadata.model_copy(update={"last_error": message}))

    def remove(self, session_id: uuid.UUID) -> None:
        path = self._path(session_id)
        for candidate in (path, path.with_name(path.name + ".tmp")):
            with contextlib.suppress(OSError):
                candidate.unlink()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateOpenSessionRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=_MAX_FILENAME_LENGTH)
    declared_byte_count: int = Field(ge=1)
    open_mode: OpenMode = "new-copy"
    project_name: str | None = Field(
        default=None, min_length=1, max_length=_MAX_PROJECT_NAME_LENGTH
    )

    @field_validator("filename")
    @classmethod
    def _check_filename(cls, value: str) -> str:
        if _CONTROL_CHAR_RE.search(value):
            raise ValueError("filename must not contain embedded control characters")
        return value

    @field_validator("project_name")
    @classmethod
    def _check_project_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        if not 1 <= len(trimmed) <= _MAX_PROJECT_NAME_LENGTH:
            raise ValueError(
                f"project name must be 1-{_MAX_PROJECT_NAME_LENGTH} characters "
                "after trimming"
            )
        if _CONTROL_CHAR_RE.search(trimmed):
            raise ValueError("project name must not contain embedded control characters")
        return trimmed


class CreateOpenSessionResponse(BaseModel):
    open_session_id: uuid.UUID
    chunk_size: int
    max_project_archive_bytes: int
    state: str


class OpenChunkAckResponse(BaseModel):
    offset: int
    chunk_bytes: int
    idempotent_replay: bool = False


class OpenSessionStateResponse(BaseModel):
    open_session_id: uuid.UUID
    filename: str
    declared_byte_count: int
    received_byte_count: int
    state: str
    open_mode: str
    last_error: str | None = None


class CompleteOpenSessionResponse(BaseModel):
    project_id: uuid.UUID
    name: str
    status: str
    revision: int


class CancelOpenSessionResponse(BaseModel):
    open_session_id: uuid.UUID
    state: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _archive_uploads(request: Request) -> UploadManager:
    return cast(UploadManager, request.app.state.archive_uploads)


def _open_sessions(request: Request) -> OpenSessionStore:
    return cast(OpenSessionStore, request.app.state.open_session_store)


def _paths(request: Request) -> StoragePaths:
    return cast(StoragePaths, request.app.state.storage_paths)


def _require_session(request: Request, session_id: uuid.UUID) -> OpenSessionMetadata:
    metadata = _open_sessions(request).load(session_id)
    if metadata is None:
        raise OpenSessionNotFoundError(str(session_id))
    return metadata


def _map_open_error(exc: PortableOpenError) -> ApiError:
    """Map the portable open error family to the API envelope."""
    if isinstance(exc, PortableOpenIdConflict):
        return OpenIdConflictError(str(exc.details.get("project_id", "")))
    if isinstance(exc, PortableOpenNoSpace):
        return OpenNoSpaceError(
            int(exc.details.get("needed_bytes", 0)),
            int(exc.details.get("free_bytes", 0)),
        )
    return ApiError(
        code=exc.code,
        message=str(exc),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        details=exc.details,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/projects/open",
    response_model=CreateOpenSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_open_session(
    body: CreateOpenSessionRequest, request: Request
) -> CreateOpenSessionResponse:
    """Create an archive transfer session (spec §18.1)."""
    if not body.filename.lower().endswith(_ARCHIVE_SUFFIX):
        raise ArchiveBadFilenameError(body.filename)
    uploads = _archive_uploads(request)
    if body.declared_byte_count > uploads.max_import_bytes:
        raise ArchiveSizeLimitError(body.declared_byte_count, uploads.max_import_bytes)

    session_id = uuid.uuid4()
    metadata = OpenSessionMetadata(
        session_id=session_id,
        filename=body.filename,
        declared_byte_count=body.declared_byte_count,
        open_mode=body.open_mode,
        project_name=body.project_name,
    )
    try:
        uploads.reserve(session_id, body.declared_byte_count)
        _open_sessions(request).save(metadata)
    except InsufficientSpaceError as exc:
        with contextlib.suppress(ImportSessionNotFoundError):
            await uploads.cancel_and_remove(session_id)
        raise OpenNoSpaceError(exc.needed, exc.free) from exc
    except UploadError as exc:
        with contextlib.suppress(ImportSessionNotFoundError):
            await uploads.cancel_and_remove(session_id)
        raise OpenSessionStateError("could not reserve temporary upload space") from exc
    except OSError as exc:
        with contextlib.suppress(ImportSessionNotFoundError):
            await uploads.cancel_and_remove(session_id)
        raise OpenSessionStateError(f"could not record the open session: {exc}") from exc

    return CreateOpenSessionResponse(
        open_session_id=session_id,
        chunk_size=uploads.chunk_size,
        max_project_archive_bytes=uploads.max_import_bytes,
        state="created",
    )


@router.put("/projects/open/{session_id}/chunks", response_model=OpenChunkAckResponse)
async def upload_open_chunk(
    session_id: uuid.UUID, request: Request, offset: int
) -> OpenChunkAckResponse:
    """Upload the next archive chunk with the import chunk protocol."""
    _require_session(request, session_id)
    if offset < 0:
        raise OffsetMismatchError(0, offset)

    chunk_sha256 = request.headers.get("X-Chunk-SHA256", "").lower()
    if len(chunk_sha256) != 64:
        raise OpenSessionStateError(
            "the X-Chunk-SHA256 header must carry the chunk hash"
        )

    uploads = _archive_uploads(request)
    try:
        ack: ChunkAck = await uploads.append_chunk(
            session_id, request.stream(), offset, chunk_sha256
        )
    except ImportSessionNotFoundError as exc:
        raise OpenSessionNotFoundError(str(session_id)) from exc
    except UploadError as exc:
        if isinstance(exc, UploadOffsetMismatchError):
            raise OffsetMismatchError(exc.expected, exc.requested) from exc
        if isinstance(exc, UploadChunkConflictError):
            raise ChunkConflictError(exc.offset) from exc
        if isinstance(exc, UploadChunkSizeError):
            raise ChunkSizeError(exc.maximum, exc.received) from exc
        raise OpenSessionStateError(f"chunk upload failed: {exc}") from exc

    return OpenChunkAckResponse(
        offset=ack.offset,
        chunk_bytes=ack.chunk_bytes,
        idempotent_replay=ack.idempotent_replay,
    )


@router.get("/projects/open/{session_id}", response_model=OpenSessionStateResponse)
def get_open_session(
    session_id: uuid.UUID, request: Request
) -> OpenSessionStateResponse:
    """The session's acknowledged bytes, state, and last error."""
    metadata = _require_session(request, session_id)
    uploads = _archive_uploads(request)
    try:
        received = uploads.acknowledged_offset(session_id)
        file_size = uploads.file_size(session_id)
    except ImportSessionNotFoundError as exc:
        raise OpenSessionNotFoundError(str(session_id)) from exc

    if received == metadata.declared_byte_count == file_size:
        state = "complete"
    elif received > 0:
        state = "uploading"
    else:
        state = "created"
    return OpenSessionStateResponse(
        open_session_id=session_id,
        filename=metadata.filename,
        declared_byte_count=metadata.declared_byte_count,
        received_byte_count=received,
        state=state,
        open_mode=metadata.open_mode,
        last_error=metadata.last_error,
    )


@router.post(
    "/projects/open/{session_id}/complete",
    response_model=CompleteOpenSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def complete_open_session(
    session_id: uuid.UUID, request: Request
) -> CompleteOpenSessionResponse:
    """Run the §18 open pipeline for a fully acknowledged transfer.

    The blocking work (archive validation, extraction, database read,
    remap, asset restoration, one transaction) runs in the threadpool —
    no media job is dispatched. A failure keeps the session files so the
    client can retry; success removes them.
    """
    metadata = _require_session(request, session_id)
    uploads = _archive_uploads(request)
    try:
        received = uploads.acknowledged_offset(session_id)
        file_size = uploads.file_size(session_id)
    except ImportSessionNotFoundError as exc:
        raise OpenSessionNotFoundError(str(session_id)) from exc
    if received != metadata.declared_byte_count or file_size != metadata.declared_byte_count:
        raise OpenSessionIncompleteError(received, metadata.declared_byte_count)

    config = request.app.state.config
    try:
        project = await run_in_threadpool(
            open_portable_archive,
            uploads.part_path_for(session_id),
            paths=_paths(request),
            repository=_projects(request),
            max_uncompressed_bytes=config.max_archive_uncompressed_bytes,
            max_member_count=config.max_archive_member_count,
            open_mode=metadata.open_mode,
            project_name=metadata.project_name,
            source_filename=metadata.filename,
        )
    except PortableOpenError as exc:
        _open_sessions(request).record_error(metadata, str(exc))
        raise _map_open_error(exc) from exc

    with contextlib.suppress(ImportSessionNotFoundError):
        await uploads.cancel_and_remove(session_id)
    _open_sessions(request).remove(session_id)
    return CompleteOpenSessionResponse(
        project_id=project.id,
        name=project.name,
        status=project.status.value,
        revision=project.revision,
    )


@router.post(
    "/projects/open/{session_id}/cancel", response_model=CancelOpenSessionResponse
)
async def cancel_open_session(
    session_id: uuid.UUID, request: Request
) -> CancelOpenSessionResponse:
    """Remove the session's upload files and metadata (idempotent)."""
    _open_sessions(request).remove(session_id)
    with contextlib.suppress(ImportSessionNotFoundError):
        await _archive_uploads(request).cancel_and_remove(session_id)
    return CancelOpenSessionResponse(open_session_id=session_id, state="cancelled")
