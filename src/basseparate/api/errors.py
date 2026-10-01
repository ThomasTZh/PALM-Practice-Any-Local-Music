"""Error envelope for API responses (M0.6).

Consistent error shape:
{
  "error": {
    "code": "PROJECT_NOT_FOUND",
    "message": "The requested project does not exist.",
    "request_id": "uuid",
    "details": {}
  }
}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Application-level API error with a stable error code."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class ProjectNotFoundError(ApiError):
    def __init__(self, project_id: str) -> None:
        super().__init__(
            code="PROJECT_NOT_FOUND",
            message=f"The requested project does not exist: {project_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class IdempotencyConflictError(ApiError):
    def __init__(self) -> None:
        super().__init__(
            code="IDEMPOTENCY_CONFLICT",
            message="Idempotency key was reused with a different request body",
            status_code=status.HTTP_409_CONFLICT,
        )


class StorageContentionError(ApiError):
    def __init__(self) -> None:
        super().__init__(
            code="STORAGE_CONTENTION",
            message="Temporary storage contention; please retry",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class ImportNotFoundError(ApiError):
    def __init__(self, import_id: str) -> None:
        super().__init__(
            code="IMPORT_NOT_FOUND",
            message=f"The requested import does not exist: {import_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ProjectNotEmptyError(ApiError):
    def __init__(self) -> None:
        super().__init__(
            code="PROJECT_NOT_EMPTY",
            message="The project already has a source; imports are only "
            "allowed into empty projects",
            status_code=status.HTTP_409_CONFLICT,
        )


class ImportStateError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="IMPORT_STATE",
            message=message,
            status_code=status.HTTP_409_CONFLICT,
        )


class OffsetMismatchError(ApiError):
    def __init__(self, expected: int, requested: int) -> None:
        super().__init__(
            code="OFFSET_MISMATCH",
            message=f"Expected chunk offset {expected}, got {requested}",
            status_code=status.HTTP_400_BAD_REQUEST,
            details={"expected_offset": expected, "requested_offset": requested},
        )


class ChunkConflictError(ApiError):
    def __init__(self, offset: int) -> None:
        super().__init__(
            code="CHUNK_CONFLICT",
            message=f"The chunk at offset {offset} does not match the already acknowledged bytes",
            status_code=status.HTTP_409_CONFLICT,
            details={"offset": offset},
        )


class ChunkSizeError(ApiError):
    def __init__(self, maximum: int, received: int) -> None:
        super().__init__(
            code="CHUNK_SIZE",
            message=f"A chunk of {received} bytes exceeds the {maximum} byte limit",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            details={"maximum_bytes": maximum, "received_bytes": received},
        )


class ImportSizeLimitError(ApiError):
    def __init__(self, maximum: int, declared: int) -> None:
        super().__init__(
            code="IMPORT_SIZE_LIMIT",
            message=f"The declared size of {declared} bytes exceeds the "
            f"{maximum} byte import limit",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            details={"maximum_bytes": maximum, "declared_bytes": declared},
        )


class InsufficientDiskSpaceError(ApiError):
    def __init__(self, needed: int, free: int) -> None:
        super().__init__(
            code="INSUFFICIENT_DISK_SPACE",
            message=f"The transfer needs about {needed} bytes but only {free} are free",
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            details={"needed_bytes": needed, "free_bytes": free},
        )


@dataclass(frozen=True)
class ErrorEnvelope:
    code: str
    message: str
    request_id: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": self.request_id,
                "details": self.details,
            }
        }


def create_error_response(request: Request, error: ApiError, request_id: str) -> JSONResponse:
    envelope = ErrorEnvelope(
        code=error.code,
        message=error.message,
        request_id=request_id,
        details=error.details,
    )
    return JSONResponse(
        status_code=error.status_code,
        content=envelope.to_dict(),
        headers={"X-Request-ID": request_id},
    )
