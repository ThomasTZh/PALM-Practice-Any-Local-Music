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


class StaleRevisionError(ApiError):
    def __init__(self, current_revision: int) -> None:
        super().__init__(
            code="STALE_REVISION",
            message="The project was modified elsewhere; reload it and retry",
            status_code=status.HTTP_409_CONFLICT,
            details={"current_revision": current_revision},
        )


class NothingToUndoError(ApiError):
    def __init__(self) -> None:
        super().__init__(
            code="NOTHING_TO_UNDO",
            message="There are no edits to undo",
            status_code=status.HTTP_409_CONFLICT,
        )


class NothingToRedoError(ApiError):
    def __init__(self) -> None:
        super().__init__(
            code="NOTHING_TO_REDO",
            message="There are no edits to redo",
            status_code=status.HTTP_409_CONFLICT,
        )


class MarkerNotFoundError(ApiError):
    def __init__(self, marker_id: str) -> None:
        super().__init__(
            code="MARKER_NOT_FOUND",
            message=f"The requested marker does not exist: {marker_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class InvalidCommandError(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            code="INVALID_COMMAND",
            message=detail,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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


class NoAudioStreamError(ApiError):
    def __init__(self, detail: str = "") -> None:
        message = "The file contains no usable audio streams"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(
            code="NO_AUDIO_STREAM",
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class UnsupportedMediaError(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            code="UNSUPPORTED_MEDIA",
            message=f"Unsupported media: {detail}",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class ProbeTimeoutError(ApiError):
    def __init__(self) -> None:
        super().__init__(
            code="PROBE_TIMEOUT",
            message="Media inspection timed out; the file may be too complex or damaged",
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )


class ProbeFailedError(ApiError):
    def __init__(self, detail: str = "") -> None:
        message = "Media inspection failed"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(
            code="PROBE_FAILED",
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class JobNotFoundError(ApiError):
    def __init__(self, job_id: str) -> None:
        super().__init__(
            code="JOB_NOT_FOUND",
            message=f"The requested job does not exist: {job_id}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class InvalidJobType(ApiError):
    def __init__(self, job_type: str) -> None:
        super().__init__(
            code="INVALID_JOB_TYPE",
            message=f"Unknown or unsupported job type: {job_type}",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class JobRequestError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(
            code="JOB_REQUEST",
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class StreamSelectionError(ApiError):
    def __init__(self, requested: int, available: list[int]) -> None:
        super().__init__(
            code="INVALID_STREAM_SELECTION",
            message=f"Audio stream {requested} is not in this file",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"requested_stream": requested, "available_streams": available},
        )


class MissingStreamSelection(ApiError):
    def __init__(self) -> None:
        super().__init__(
            code="NO_STREAM_SELECTION",
            message="No audio stream is selected for this import; "
            "select a stream before decoding",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class AssetNotFoundError(ApiError):
    def __init__(self, asset_id: str, missing_file: bool = False) -> None:
        if missing_file:
            message = f"The asset's file is missing from storage: {asset_id}"
        else:
            message = f"The requested asset does not exist: {asset_id}"
        super().__init__(
            code="ASSET_NOT_FOUND",
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ProjectNotReadyError(ApiError):
    def __init__(self) -> None:
        super().__init__(
            code="PROJECT_NOT_READY",
            message="The project has no source audio yet; import and decode a file first",
            status_code=status.HTTP_409_CONFLICT,
        )


class InvalidMonitoringSelection(ApiError):
    def __init__(self, left: int, right: int, channel_count: int) -> None:
        super().__init__(
            code="INVALID_MONITORING_SELECTION",
            message=f"Monitoring channels {left}/{right} are outside the source's "
            f"{channel_count} channels",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"left": left, "right": right, "channel_count": channel_count},
        )


class NoPlaybackRepresentation(ApiError):
    def __init__(self, project_id: str, rate: int) -> None:
        super().__init__(
            code="NO_PLAYBACK_REPRESENTATION",
            message=f"No playback representation at {rate} Hz exists for this project",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"project_id": project_id, "rate": rate},
        )


class RangeNotSatisfiable(ApiError):
    def __init__(self, total: int) -> None:
        super().__init__(
            code="RANGE_NOT_SATISFIABLE",
            message="The requested byte range is not satisfiable",
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            details={"total_bytes": total},
        )


class NonPcmAssetError(ApiError):
    def __init__(self, asset_id: str) -> None:
        super().__init__(
            code="NOT_PCM_ASSET",
            message=f"The asset is not raw PCM audio: {asset_id}",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"asset_id": asset_id},
        )


class PcmRangeError(ApiError):
    def __init__(self, start_frame: int, frame_count: int) -> None:
        super().__init__(
            code="PCM_RANGE_OUT_OF_BOUNDS",
            message=f"start_frame {start_frame} is beyond the asset's {frame_count} frames",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={"start_frame": start_frame, "frame_count": frame_count},
        )


class PeakRangeError(ApiError):
    def __init__(self, level: int, tile: int, level_count: int, tile_count: int) -> None:
        super().__init__(
            code="PEAK_RANGE_OUT_OF_BOUNDS",
            message=f"level {level} tile {tile} is outside the pyramid "
            f"({level_count} levels; {tile_count} tiles at this level)",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={
                "level": level,
                "tile": tile,
                "level_count": level_count,
                "tile_count": tile_count,
            },
        )


class NoWaveformCacheError(ApiError):
    def __init__(self, asset_id: str) -> None:
        super().__init__(
            code="NO_WAVEFORM_CACHE",
            message=f"No waveform cache exists for this asset: {asset_id}",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"asset_id": asset_id},
        )


class TileNotReadyError(ApiError):
    def __init__(self, level: int, tile: int) -> None:
        super().__init__(
            code="TILE_NOT_READY",
            message=f"Peak tile {tile} at level {level} is not available yet",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"level": level, "tile": tile},
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
