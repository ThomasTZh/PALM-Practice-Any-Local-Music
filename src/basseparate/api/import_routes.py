"""Import transfer routes (M1.2).

Routes (all authenticated, loopback-only):
- POST /api/v1/imports — create an upload session
- PUT  /api/v1/imports/{id}/chunks?offset=… — upload the next chunk
- GET  /api/v1/imports/{id} — transfer/probe state
- GET  /api/v1/projects/{id}/imports — list a project's imports (reload recovery)
- POST /api/v1/imports/{id}/complete — finalize transfer, hash source
- POST /api/v1/imports/{id}/cancel — cancel and remove uncommitted bytes
"""

from __future__ import annotations

import contextlib
import re
import uuid
from typing import Any, cast

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field, field_validator

from basseparate.api.errors import (
    ChunkConflictError,
    ChunkSizeError,
    ImportNotFoundError,
    ImportSizeLimitError,
    ImportStateError,
    InsufficientDiskSpaceError,
    NoAudioStreamError,
    OffsetMismatchError,
    ProbeFailedError,
    ProbeTimeoutError,
    ProjectNotEmptyError,
    ProjectNotFoundError,
    StreamSelectionError,
    UnsupportedMediaError,
)
from basseparate.domain.import_record import ImportRecord, ProbeResult, TransferState
from basseparate.media.probe import (
    NoAudioStreamError as MediaNoAudioStreamError,
)
from basseparate.media.probe import (
    ProbeFailedError as MediaProbeFailedError,
)
from basseparate.media.probe import (
    ProbeTimeoutError as MediaProbeTimeoutError,
)
from basseparate.media.probe import (
    UnsupportedMediaError as MediaUnsupportedMediaError,
)
from basseparate.media.probe import (
    probe_media,
)
from basseparate.storage import ImportRepository, ProjectRepository
from basseparate.uploads import (
    ChunkAck,
    ImportSessionNotFoundError,
    UploadError,
    UploadManager,
)
from basseparate.uploads import (
    ChunkConflictError as UploadChunkConflictError,
)
from basseparate.uploads import (
    ChunkSizeError as UploadChunkSizeError,
)
from basseparate.uploads import (
    OffsetMismatchError as UploadOffsetMismatchError,
)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

router = APIRouter(prefix="/api/v1")


class CreateImportRequest(BaseModel):
    project_id: uuid.UUID
    filename: str = Field(min_length=1, max_length=512)
    declared_byte_count: int = Field(ge=1)

    @field_validator("filename")
    @classmethod
    def _check_filename(cls, v: str) -> str:
        if _CONTROL_CHAR_RE.search(v):
            raise ValueError("filename must not contain embedded control characters")
        return v


class CreateImportResponse(BaseModel):
    import_id: uuid.UUID
    project_id: uuid.UUID
    chunk_size: int
    max_import_bytes: int
    state: str


class ChunkAckResponse(BaseModel):
    offset: int
    chunk_bytes: int
    idempotent_replay: bool = False


class ImportListResponse(BaseModel):
    imports: list[ImportRecord]


class CompleteImportResponse(BaseModel):
    import_id: uuid.UUID
    source_sha256: str
    state: str
    probe_result: ProbeResult | None = None
    selected_stream_index: int | None = None


class SelectStreamRequest(BaseModel):
    stream_index: int = Field(ge=0)


class CancelImportResponse(BaseModel):
    import_id: uuid.UUID
    state: str


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _imports(request: Request) -> ImportRepository:
    return cast(ImportRepository, request.app.state.import_repository)


def _uploads(request: Request) -> UploadManager:
    return cast(UploadManager, request.app.state.upload_manager)


def _require_import(request: Request, import_id: uuid.UUID) -> ImportRecord:
    record = _imports(request).get_import(import_id)
    if record is None:
        raise ImportNotFoundError(str(import_id))
    return record


@router.post(
    "/imports",
    response_model=CreateImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_import(request: Request, body: CreateImportRequest) -> CreateImportResponse:
    projects = _projects(request)
    uploads = _uploads(request)

    project = projects.get_project(body.project_id)
    if project is None:
        raise ProjectNotFoundError(str(body.project_id))
    if project.status.value != "empty":
        raise ProjectNotEmptyError()

    if body.declared_byte_count > uploads.max_import_bytes:
        raise ImportSizeLimitError(uploads.max_import_bytes, body.declared_byte_count)

    record = _imports(request).create_import(
        project_id=body.project_id,
        filename=body.filename,
        declared_byte_count=body.declared_byte_count,
    )

    try:
        uploads.reserve(record.id, body.declared_byte_count)
    except UploadError as exc:
        message = str(exc)
        if message.startswith("insufficient disk space"):
            needed, free = message.split(" bytes, ", 1)
            raise InsufficientDiskSpaceError(int(needed), int(free.split(" free")[0])) from exc
        # Reservation failed for another reason; do not leave a dangling
        # import record.
        _imports(request).update_transfer_state(
            record.id, TransferState.FAILED, error="upload reservation failed"
        )
        raise ImportStateError("could not reserve temporary upload space") from exc

    return CreateImportResponse(
        import_id=record.id,
        project_id=record.project_id,
        chunk_size=uploads.chunk_size,
        max_import_bytes=uploads.max_import_bytes,
        state=record.transfer_state.value,
    )


@router.put("/imports/{import_id}/chunks", response_model=ChunkAckResponse)
async def upload_chunk(
    import_id: uuid.UUID,
    request: Request,
    offset: int,
) -> ChunkAckResponse:
    record = _require_import(request, import_id)
    if record.transfer_state not in (TransferState.CREATED, TransferState.UPLOADING):
        raise ImportStateError(
            f"import is {record.transfer_state.value}; uploads are no longer accepted"
        )
    if offset < 0:
        raise OffsetMismatchError(0, offset)

    chunk_sha256 = request.headers.get("X-Chunk-SHA256", "").lower()
    if len(chunk_sha256) != 64:
        raise ImportStateError("the X-Chunk-SHA256 header must carry the chunk hash")

    uploads = _uploads(request)
    try:
        ack: ChunkAck = await uploads.append_chunk(
            import_id, request.stream(), offset, chunk_sha256
        )
    except ImportSessionNotFoundError as exc:
        raise ImportNotFoundError(str(import_id)) from exc
    except UploadError as exc:
        if isinstance(exc, UploadOffsetMismatchError):
            raise OffsetMismatchError(exc.expected, exc.requested) from exc
        if isinstance(exc, UploadChunkConflictError):
            raise ChunkConflictError(exc.offset) from exc
        if isinstance(exc, UploadChunkSizeError):
            raise ChunkSizeError(exc.maximum, exc.received) from exc
        raise ImportStateError(f"chunk upload failed: {exc}") from exc

    _imports(request).update_transfer_state(
        import_id,
        TransferState.UPLOADING,
        received_byte_count=ack.offset,
    )
    return ChunkAckResponse(
        offset=ack.offset,
        chunk_bytes=ack.chunk_bytes,
        idempotent_replay=ack.idempotent_replay,
    )


@router.get("/imports/{import_id}", response_model=ImportRecord)
async def get_import(import_id: uuid.UUID, request: Request) -> ImportRecord:
    return _require_import(request, import_id)


@router.get("/projects/{project_id}/imports", response_model=ImportListResponse)
async def list_project_imports(project_id: uuid.UUID, request: Request) -> ImportListResponse:
    project = _projects(request).get_project(project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    return ImportListResponse(imports=_imports(request).list_imports_for_project(project_id))


@router.post("/imports/{import_id}/complete", response_model=CompleteImportResponse)
async def complete_import(import_id: uuid.UUID, request: Request) -> CompleteImportResponse:
    record = _require_import(request, import_id)
    if record.transfer_state not in (TransferState.CREATED, TransferState.UPLOADING):
        raise ImportStateError(f"import is {record.transfer_state.value}; it cannot be completed")
    uploads = _uploads(request)
    try:
        file_size = uploads.file_size(import_id)
        acknowledged = uploads.acknowledged_offset(import_id)
    except ImportSessionNotFoundError as exc:
        raise ImportNotFoundError(str(import_id)) from exc

    if acknowledged != record.declared_byte_count or file_size != record.declared_byte_count:
        raise ImportStateError(
            f"the transfer is incomplete: {acknowledged} of {record.declared_byte_count} "
            "bytes acknowledged"
        )

    source_sha256 = await uploads.hash_completed_file(import_id)

    try:
        probe = await probe_media(uploads.part_path_for(import_id))
    except MediaNoAudioStreamError as exc:
        _imports(request).update_transfer_state(import_id, TransferState.FAILED, error=str(exc))
        raise NoAudioStreamError(str(exc)) from exc
    except MediaProbeTimeoutError as exc:
        _imports(request).update_transfer_state(import_id, TransferState.FAILED, error=str(exc))
        raise ProbeTimeoutError() from exc
    except MediaProbeFailedError as exc:
        _imports(request).update_transfer_state(import_id, TransferState.FAILED, error=str(exc))
        raise ProbeFailedError(str(exc)) from exc
    except MediaUnsupportedMediaError as exc:
        _imports(request).update_transfer_state(import_id, TransferState.FAILED, error=str(exc))
        raise UnsupportedMediaError(str(exc)) from exc

    updated = _imports(request).update_transfer_state(
        import_id,
        TransferState.COMPLETE,
        received_byte_count=record.declared_byte_count,
        source_sha256=source_sha256,
    )
    updated = _imports(request).set_probe_result(import_id, probe)
    if len(probe.audio_streams) == 1:
        updated = _imports(request).set_selected_stream(import_id, probe.audio_streams[0].index)
    return CompleteImportResponse(
        import_id=import_id,
        source_sha256=source_sha256,
        state=updated.transfer_state.value,
        probe_result=updated.probe_result,
        selected_stream_index=updated.selected_stream_index,
    )


@router.post("/imports/{import_id}/select-stream", response_model=ImportRecord)
async def select_stream(
    import_id: uuid.UUID, body: SelectStreamRequest, request: Request
) -> ImportRecord:
    record = _require_import(request, import_id)
    if record.transfer_state != TransferState.COMPLETE:
        raise ImportStateError(
            f"import is {record.transfer_state.value}; a stream can only be selected "
            "after the transfer is complete"
        )
    if record.probe_result is None:
        raise ImportStateError("the import has no probe result")
    available = sorted(s.index for s in record.probe_result.audio_streams)
    if body.stream_index not in available:
        raise StreamSelectionError(body.stream_index, available)
    return _imports(request).set_selected_stream(import_id, body.stream_index)


@router.post("/imports/{import_id}/cancel", response_model=CancelImportResponse)
async def cancel_import(import_id: uuid.UUID, request: Request) -> CancelImportResponse:
    record = _require_import(request, import_id)
    if record.transfer_state in (TransferState.COMPLETE,):
        raise ImportStateError("a completed import cannot be cancelled")
    if record.transfer_state == TransferState.CANCELLED:
        return CancelImportResponse(import_id=import_id, state="cancelled")

    updated = _imports(request).update_transfer_state(
        import_id, TransferState.CANCELLED, error="cancelled by user"
    )
    uploads = _uploads(request)
    with contextlib.suppress(ImportSessionNotFoundError):
        await uploads.cancel_and_remove(import_id)
    return CancelImportResponse(import_id=import_id, state=updated.transfer_state.value)


def import_state_summary(record: ImportRecord) -> dict[str, Any]:
    """Convenience summary used by tests and future polling endpoints."""
    return {
        "id": str(record.id),
        "state": record.transfer_state.value,
        "received_byte_count": record.received_byte_count,
        "declared_byte_count": record.declared_byte_count,
    }
