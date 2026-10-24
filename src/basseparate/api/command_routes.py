"""Project command routes (M1.15, milestone1.md §17.3/§17.4).

Routes:
- POST /api/v1/projects/{id}/commands — apply one project command with
  base-revision validation (409 STALE_REVISION on mismatch) and an
  idempotency key; returns the resulting state.
- POST /api/v1/projects/{id}/undo — undo the newest history entry.
- POST /api/v1/projects/{id}/redo — redo the newest undone entry.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import NoReturn, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, ValidationError

from basseparate.api.errors import (
    IdempotencyConflictError,
    InvalidCommandError,
    LoopAlignmentConfirmationRequiredError,
    LoopGridUnavailableError,
    LoopNotFoundError,
    LoopRangeInvalidError,
    LoopTooShortError,
    MarkerNotFoundError,
    NoActiveLoopError,
    NothingToRedoError,
    NothingToUndoError,
    PlaybackModeRequiresResultSetError,
    ProjectNotFoundError,
    ProjectNotReadyError,
    ResultSetNotFoundError,
    StaleRevisionError,
)
from basseparate.api.idempotency import IdempotencyStore
from basseparate.domain.commands import CommandRequest, CommandResult
from basseparate.storage import ProjectRepository
from basseparate.storage.repository import (
    LoopAlignmentConfirmationRequiredError as RepoLoopAlignmentConfirmationRequiredError,
)
from basseparate.storage.repository import (
    LoopGridUnavailableError as RepoLoopGridUnavailableError,
)
from basseparate.storage.repository import (
    LoopNotFoundError as RepoLoopNotFoundError,
)
from basseparate.storage.repository import (
    LoopRangeInvalidError as RepoLoopRangeInvalidError,
)
from basseparate.storage.repository import (
    LoopTooShortError as RepoLoopTooShortError,
)
from basseparate.storage.repository import (
    MarkerNotFoundError as RepoMarkerNotFoundError,
)
from basseparate.storage.repository import (
    NoActiveLoopError as RepoNoActiveLoopError,
)
from basseparate.storage.repository import (
    NothingToRedoError as RepoNothingToRedoError,
)
from basseparate.storage.repository import (
    NothingToUndoError as RepoNothingToUndoError,
)
from basseparate.storage.repository import (
    PlaybackModeRequiresResultSetError as RepoPlaybackModeRequiresResultSetError,
)
from basseparate.storage.repository import (
    ProjectMissingError,
    ProjectNotReady,
)
from basseparate.storage.repository import (
    ResultSetNotFoundError as RepoResultSetNotFoundError,
)
from basseparate.storage.repository import (
    StaleRevisionError as RepoStaleRevisionError,
)

router = APIRouter(prefix="/api/v1")


class HistoryRequest(BaseModel):
    base_revision: int = Field(ge=0)


def _repo(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _idempotency_store(request: Request) -> IdempotencyStore:
    return cast(IdempotencyStore, request.app.state.idempotency_store)


def _raise_mapped(exc: Exception) -> NoReturn:
    """Map repository-level exceptions to API errors and raise."""
    if isinstance(exc, ProjectMissingError):
        raise ProjectNotFoundError("unknown project") from exc
    if isinstance(exc, RepoStaleRevisionError):
        raise StaleRevisionError(exc.current_revision) from exc
    if isinstance(exc, RepoNothingToUndoError):
        raise NothingToUndoError() from exc
    if isinstance(exc, RepoNothingToRedoError):
        raise NothingToRedoError() from exc
    if isinstance(exc, RepoMarkerNotFoundError):
        raise MarkerNotFoundError(str(exc.marker_id)) from exc
    if isinstance(exc, RepoResultSetNotFoundError):
        raise ResultSetNotFoundError(str(exc.result_set_id)) from exc
    if isinstance(exc, RepoPlaybackModeRequiresResultSetError):
        raise PlaybackModeRequiresResultSetError() from exc
    if isinstance(exc, RepoLoopNotFoundError):
        raise LoopNotFoundError(str(exc.loop_id)) from exc
    if isinstance(exc, RepoLoopRangeInvalidError):
        raise LoopRangeInvalidError(exc.start, exc.end, exc.duration) from exc
    if isinstance(exc, RepoLoopGridUnavailableError):
        raise LoopGridUnavailableError(str(exc)) from exc
    if isinstance(exc, RepoLoopAlignmentConfirmationRequiredError):
        raise LoopAlignmentConfirmationRequiredError(exc.warnings) from exc
    if isinstance(exc, RepoNoActiveLoopError):
        raise NoActiveLoopError() from exc
    if isinstance(exc, RepoLoopTooShortError):
        raise LoopTooShortError(exc.frames, exc.sample_rate) from exc
    if isinstance(exc, ProjectNotReady):
        raise ProjectNotReadyError() from exc
    if isinstance(exc, ValidationError):
        raise InvalidCommandError(str(exc)) from exc
    raise exc


@router.post("/projects/{project_id}/commands", response_model=CommandResult)
async def apply_command(
    project_id: uuid.UUID, body: CommandRequest, request: Request
) -> CommandResult:
    store = _idempotency_store(request)
    body_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    existing = store.get(body.idempotency_key)
    if existing is not None:
        if existing.body_hash != body_hash:
            raise IdempotencyConflictError()
        return cast(CommandResult, existing.payload)

    try:
        result = await asyncio.to_thread(
            _repo(request).apply_command, project_id, body.op, body.base_revision
        )
    except Exception as exc:
        _raise_mapped(exc)
    store.set(body.idempotency_key, body_hash, result)
    return result


@router.post("/projects/{project_id}/undo", response_model=CommandResult)
async def undo(project_id: uuid.UUID, body: HistoryRequest, request: Request) -> CommandResult:
    try:
        return await asyncio.to_thread(_repo(request).undo, project_id, body.base_revision)
    except Exception as exc:
        _raise_mapped(exc)


@router.post("/projects/{project_id}/redo", response_model=CommandResult)
async def redo(project_id: uuid.UUID, body: HistoryRequest, request: Request) -> CommandResult:
    try:
        return await asyncio.to_thread(_repo(request).redo, project_id, body.base_revision)
    except Exception as exc:
        _raise_mapped(exc)
