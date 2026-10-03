"""Monitoring and playback routes (M1.7, milestone1.md §9).

Routes (all authenticated, loopback-only):
- PUT  /api/v1/projects/{project_id}/monitoring-channels — store the user's
  left/right source-channel selection (unknown layouts only)
- GET  /api/v1/projects/{project_id}/source-info — source rate, duration,
  channel labels, monitoring state, and the playback rates on hand
- GET  /api/v1/projects/{project_id}/playback?rate=N — resolve the asset to
  play at a rate (404 ``NO_PLAYBACK_REPRESENTATION`` when none exists)
- GET  /api/v1/assets/{asset_id}/bytes — raw asset bytes with HTTP Range
  support (200 full, 206 partial, 416 unsatisfiable)

Playback resolution (spec §9.5): the source is the monitoring asset when
present, else the canonical asset. A request at the source's own rate
resolves to that asset; other rates resolve to a published playback-rate
representation.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from typing import Annotated, cast

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from basseparate.api.errors import (
    AssetNotFoundError,
    InvalidMonitoringSelection,
    NoPlaybackRepresentation,
    ProjectNotFoundError,
    ProjectNotReadyError,
    RangeNotSatisfiable,
)
from basseparate.domain.project import ProjectRecord, ProjectStatus
from basseparate.domain.representation import RepresentationRole
from basseparate.media.downmix import STANDARD_51_LAYOUTS, channel_labels
from basseparate.storage import ProjectRepository, RepresentationRepository, StoragePaths

router = APIRouter(prefix="/api/v1")

#: One streamed chunk of an asset byte response.
_CHUNK_SIZE = 1 << 20

#: Single-range ``bytes=start-end`` (either bound may be empty; a leading
#: suffix ``bytes=-N`` means the last N bytes).
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


class MonitoringChannelsRequest(BaseModel):
    #: Source channel index for the monitoring left output (0-based).
    left: int = Field(ge=0, le=7)
    #: Source channel index for the monitoring right output (0-based).
    right: int = Field(ge=0, le=7)


class MonitoringInfo(BaseModel):
    mode: str
    asset_id: uuid.UUID
    left_channel: int
    right_channel: int


class SourceInfoResponse(BaseModel):
    sample_rate: int
    duration_frames: int
    duration_seconds: float
    channel_count: int
    channel_layout: str | None
    channel_labels: list[str]
    monitoring: MonitoringInfo | None
    playback_rates: list[int]


class PlaybackResponse(BaseModel):
    asset_id: uuid.UUID
    role: str
    sample_rate: int
    channel_count: int
    frame_count: int
    byte_count: int
    duration_seconds: float


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _representations(request: Request) -> RepresentationRepository:
    return cast(RepresentationRepository, request.app.state.representation_repository)


def _paths(request: Request) -> StoragePaths:
    return cast(StoragePaths, request.app.state.storage_paths)


def _require_ready_project(request: Request, project_id: uuid.UUID) -> ProjectRecord:
    project = _projects(request).get_project(project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    if project.status is not ProjectStatus.READY:
        raise ProjectNotReadyError()
    return project


@router.put("/projects/{project_id}/monitoring-channels", response_model=ProjectRecord)
async def set_monitoring_channels(
    project_id: uuid.UUID, body: MonitoringChannelsRequest, request: Request
) -> ProjectRecord:
    project = _require_ready_project(request, project_id)
    count = project.source_channel_count
    assert count is not None  # a ready project always has a channel count
    if not 0 <= body.left < count or not 0 <= body.right < count:
        raise InvalidMonitoringSelection(body.left, body.right, count)
    return _projects(request).set_monitoring_channels(project_id, body.left, body.right)


@router.get("/projects/{project_id}/source-info", response_model=SourceInfoResponse)
async def get_source_info(project_id: uuid.UUID, request: Request) -> SourceInfoResponse:
    project = _require_ready_project(request, project_id)
    sample_rate = project.sample_rate
    duration_frames = project.duration_frames
    channel_count = project.source_channel_count
    assert (
        sample_rate is not None and duration_frames is not None and channel_count is not None
    )
    layout = project.source_channel_layout

    monitoring: MonitoringInfo | None = None
    if project.monitoring_asset_id is not None:
        if channel_count == 6 and layout in STANDARD_51_LAYOUTS:
            monitoring = MonitoringInfo(
                mode="standard_5_1",
                asset_id=project.monitoring_asset_id,
                left_channel=0,
                right_channel=1,
            )
        elif project.monitoring_left_channel is not None:
            assert project.monitoring_right_channel is not None
            monitoring = MonitoringInfo(
                mode="manual",
                asset_id=project.monitoring_asset_id,
                left_channel=project.monitoring_left_channel,
                right_channel=project.monitoring_right_channel,
            )

    rates: set[int] = set()
    parent_id = project.monitoring_asset_id or project.canonical_asset_id
    if parent_id is not None:
        for rep in _representations(request).list_representations_for_asset(parent_id):
            if rep.role is RepresentationRole.PLAYBACK_RATE:
                rates.add(rep.sample_rate)

    return SourceInfoResponse(
        sample_rate=sample_rate,
        duration_frames=duration_frames,
        duration_seconds=duration_frames / sample_rate,
        channel_count=channel_count,
        channel_layout=layout,
        channel_labels=channel_labels(channel_count, layout),
        monitoring=monitoring,
        playback_rates=sorted(rates),
    )


@router.get("/projects/{project_id}/playback", response_model=PlaybackResponse)
async def resolve_playback(
    project_id: uuid.UUID,
    rate: Annotated[int, Query(ge=8000, le=192000)],
    request: Request,
) -> PlaybackResponse:
    projects = _projects(request)
    project = _require_ready_project(request, project_id)
    source_id = project.monitoring_asset_id or project.canonical_asset_id
    asset = projects.get_asset(source_id) if source_id is not None else None
    if asset is None or asset.audio is None:
        raise ProjectNotReadyError()
    audio = asset.audio
    if audio.sample_rate == rate:
        role = "monitoring_downmix" if project.monitoring_asset_id is not None else "canonical"
        return PlaybackResponse(
            asset_id=asset.id,
            role=role,
            sample_rate=rate,
            channel_count=audio.channel_count,
            frame_count=audio.frame_count,
            byte_count=asset.byte_count,
            duration_seconds=audio.frame_count / rate,
        )
    rep = _representations(request).find_playback(asset.id, rate)
    if rep is None:
        raise NoPlaybackRepresentation(str(project_id), rate)
    rep_asset = projects.get_asset(rep.asset_id)
    if rep_asset is None:
        raise AssetNotFoundError(str(rep.asset_id))
    return PlaybackResponse(
        asset_id=rep.asset_id,
        role="playback_rate",
        sample_rate=rate,
        channel_count=rep.channel_count,
        frame_count=rep.frame_count,
        byte_count=rep_asset.byte_count,
        duration_seconds=rep.frame_count / rate,
    )


def _parse_range(header: str, total: int) -> tuple[int, int]:
    """Parse a single ``bytes=`` range against ``total`` bytes.

    Returns an inclusive ``(start, end)`` pair. Raises
    ``RangeNotSatisfiable`` for malformed or out-of-bounds ranges.
    """
    match = _RANGE_RE.fullmatch(header.strip())
    if match is None:
        raise RangeNotSatisfiable(total)
    start_text, end_text = match.groups()
    if start_text == "" and end_text == "":
        raise RangeNotSatisfiable(total)
    if start_text == "":
        suffix = int(end_text)
        if suffix == 0:
            raise RangeNotSatisfiable(total)
        return max(0, total - suffix), total - 1
    start = int(start_text)
    if start >= total:
        raise RangeNotSatisfiable(total)
    end = int(end_text) if end_text else total - 1
    return start, min(end, total - 1)


@router.get("/assets/{asset_id}/bytes")
async def get_asset_bytes(asset_id: uuid.UUID, request: Request) -> StreamingResponse:
    projects = _projects(request)
    asset = projects.get_asset(asset_id)
    if asset is None:
        raise AssetNotFoundError(str(asset_id))
    path = _paths(request).resolve_asset_path(asset.relative_path)
    if not path.is_file():
        raise AssetNotFoundError(str(asset_id), missing_file=True)
    total = path.stat().st_size
    range_header = request.headers.get("range", "")
    partial = bool(range_header)
    if partial:
        start, end = _parse_range(range_header, total)
    else:
        start, end = 0, max(0, total - 1)
    length = end - start + 1

    def iter_chunks() -> Iterator[bytes]:
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(_CHUNK_SIZE, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(length),
        "Content-Type": "application/octet-stream",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return StreamingResponse(
        iter_chunks(),
        status_code=status.HTTP_206_PARTIAL_CONTENT if partial else status.HTTP_200_OK,
        headers=headers,
    )
