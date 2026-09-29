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
