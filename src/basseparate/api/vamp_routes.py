"""Local Vamp analysis routes (personal build)."""

from __future__ import annotations

import asyncio
import uuid
from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from basseparate.api.errors import (
    ProjectNotFoundError,
    ProjectNotReadyError,
    VampAnalysisFailedError,
    VampUnavailableError,
)
from basseparate.storage import ProjectRepository
from basseparate.vamp.service import (
    VampAnalysisError,
    VampAnalysisService,
    VampUnavailable,
)

router = APIRouter(prefix="/api/v1", tags=["vamp"])


class VampAnalysisRequest(BaseModel):
    bpb: int = Field(default=4, ge=2, le=16)


class VampAnalysisResponse(BaseModel):
    branch_id: uuid.UUID
    beats: int
    bars: int
    cached: bool
    plugin_key: str
    plugin_version: str
    bpb: int


def _vamp_service(request: Request) -> VampAnalysisService:
    return cast(VampAnalysisService, request.app.state.vamp_service)


@router.post("/projects/{project_id}/vamp-analysis", response_model=VampAnalysisResponse)
async def analyze_project(
    project_id: uuid.UUID, body: VampAnalysisRequest, request: Request
) -> VampAnalysisResponse:
    repository = cast(ProjectRepository, request.app.state.repository)
    project = repository.get_project(project_id)
    if project is None:
        raise ProjectNotFoundError("unknown project")
    if project.status.value != "ready" or project.canonical_asset_id is None:
        raise ProjectNotReadyError()
    try:
        result = await asyncio.to_thread(_vamp_service(request).analyze, project_id, body.bpb)
    except VampUnavailable as exc:
        raise VampUnavailableError(str(exc)) from exc
    except VampAnalysisError as exc:
        raise VampAnalysisFailedError(str(exc)) from exc
    return VampAnalysisResponse(
        branch_id=result.branch.id,
        beats=result.beats,
        bars=result.bars,
        cached=result.cached,
        plugin_key=result.plugin_key,
        plugin_version=result.plugin_version,
        bpb=result.bpb,
    )
