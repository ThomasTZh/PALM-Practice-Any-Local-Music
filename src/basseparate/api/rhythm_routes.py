"""Read-only rhythm grid API for the editor lanes (M3.11/M3.17).

GET /api/v1/projects/{id}/rhythm-grid returns the active branch's tempo
anchors, meter regions, bar origin, pulses, and derived visible grid for
a source-frame range and detail level. It never mutates project state.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from basseparate.api.errors import ApiError, ProjectNotFoundError
from basseparate.domain.grid import GridDetail, GridResult
from basseparate.domain.rhythm import (
    BarOriginState,
    GridValidity,
    MeterRegion,
    RhythmBranchRecord,
    RhythmPulse,
    TempoAnchor,
)
from basseparate.rhythm.commands import meter_map_for_branch, tempo_map_for_branch
from basseparate.rhythm.grid import GridError, derive_grid
from basseparate.storage import ProjectRepository, RhythmRepository

router = APIRouter(prefix="/api/v1")


class RhythmGridResponse(BaseModel):
    project_id: uuid.UUID
    revision: int
    branch_id: uuid.UUID
    branch_revision: int
    branch_validity: GridValidity
    source_sample_rate: int
    source_duration_frames: int
    tempo_anchors: list[TempoAnchor]
    meter_regions: list[MeterRegion]
    bar_origin: BarOriginState
    pulses: list[RhythmPulse]
    grid: GridResult


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _rhythm(request: Request) -> RhythmRepository:
    return cast(RhythmRepository, request.app.state.rhythm_repository)


class RhythmGridUnavailableError(ApiError):
    def __init__(self, project_id: uuid.UUID) -> None:
        super().__init__(
            code="RHYTHM_GRID_UNAVAILABLE",
            message="The project has no complete editable rhythm grid",
            status_code=404,
            details={"project_id": str(project_id)},
        )


@router.get(
    "/projects/{project_id}/rhythm-grid",
    response_model=RhythmGridResponse,
)
async def get_rhythm_grid(
    project_id: uuid.UUID,
    request: Request,
    start_frame: int | None = Query(default=None, ge=0),
    end_frame: int | None = Query(default=None, ge=0),
    detail: Annotated[GridDetail, Query()] = GridDetail.PRIMARY,
) -> RhythmGridResponse:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    if project.sample_rate is None:
        raise RhythmGridUnavailableError(project_id)
    branch_id = project.rhythm_state.active_branch_id
    if branch_id is None:
        raise RhythmGridUnavailableError(project_id)
    branch: RhythmBranchRecord | None = await asyncio.to_thread(
        _rhythm(request).get_branch, branch_id
    )
    if branch is None or branch.project_id != project_id:
        raise RhythmGridUnavailableError(project_id)
    try:
        tempo_map = tempo_map_for_branch(branch, project.sample_rate)
        meter_map = meter_map_for_branch(branch)
    except Exception as exc:  # noqa: BLE001 - incomplete branch is a 404 condition
        raise RhythmGridUnavailableError(project_id) from exc
    start = None
    end = None
    try:
        if start_frame is not None:
            start = tempo_map.map_source_to_musical(start_frame)
        if end_frame is not None:
            end = tempo_map.map_source_to_musical(end_frame)
    except ValueError as exc:
        raise ApiError(
            code="RHYTHM_GRID_RANGE_INVALID",
            message=str(exc),
            status_code=422,
        ) from exc
    try:
        grid = derive_grid(
            tempo_map,
            meter_map,
            branch.bar_origin,
            start=start,
            end=end,
            detail=detail,
        )
    except GridError as exc:
        raise ApiError(
            code="RHYTHM_GRID_RANGE_INVALID",
            message=str(exc),
            status_code=422,
        ) from exc
    low = start_frame if start_frame is not None else 0
    high = end_frame if end_frame is not None else branch.source_duration_frames
    pulses = [pulse for pulse in branch.pulses if low <= pulse.source_frame <= high]
    return RhythmGridResponse(
        project_id=project_id,
        revision=project.revision,
        branch_id=branch.id,
        branch_revision=branch.revision,
        branch_validity=branch.grid_validity,
        source_sample_rate=project.sample_rate,
        source_duration_frames=branch.source_duration_frames,
        tempo_anchors=branch.tempo_anchors,
        meter_regions=branch.meter_regions,
        bar_origin=branch.bar_origin,
        pulses=pulses,
        grid=grid,
    )
