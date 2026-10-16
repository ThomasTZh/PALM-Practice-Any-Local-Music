"""Separation result-set routes (M2.8, milestone2.md §10.1.6, §10.4.5–6).

Routes (authenticated, loopback-only):
- GET /api/v1/projects/{project_id}/result-sets — the project's result
  sets (id, created_at, validation status, available stem roles),
  oldest first. Feeds the playback-mode selector's set choice.
- GET /api/v1/projects/{project_id}/result-sets/{result_set_id} — the
  detail the track stack needs: the result set, its stems, and the
  completing run's provenance (model manifest + engine/adapter
  versions). 404 when the project is missing or the set is missing or
  belongs to another project.

The routes are read-only: they never mutate records or assets.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import cast

from fastapi import APIRouter, Request
from pydantic import BaseModel

from basseparate.api.errors import ProjectNotFoundError, ResultSetNotFoundError
from basseparate.storage import ProjectRepository, SeparationRepository

router = APIRouter(prefix="/api/v1")


class ResultSetStemDetail(BaseModel):
    """One published stem of a result set (spec §10.1.6)."""

    id: uuid.UUID
    role: str
    display_name: str
    audio_asset_id: uuid.UUID
    sample_rate: int
    channel_count: int
    frame_count: int


class ResultSetDetail(BaseModel):
    """A result set with its stems and run provenance (spec §10.1.6)."""

    id: uuid.UUID
    created_at: str
    validation_status: str
    cache_key: str | None
    stems: list[ResultSetStemDetail]
    engine_version: str
    adapter_version: str
    model_manifest_id: uuid.UUID
    model_manifest_hash: str


class ResultSetSummary(BaseModel):
    """One result set in the project's list (spec §10.4.5–6 selector)."""

    id: uuid.UUID
    created_at: str
    validation_status: str
    available_stem_roles: list[str]


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _separation(request: Request) -> SeparationRepository:
    return cast(SeparationRepository, request.app.state.separation_repository)


@router.get(
    "/projects/{project_id}/result-sets",
    response_model=list[ResultSetSummary],
)
async def list_result_sets(project_id: uuid.UUID, request: Request) -> list[ResultSetSummary]:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    sets = await asyncio.to_thread(
        _separation(request).list_result_sets_for_project, project_id
    )
    return [
        ResultSetSummary(
            id=s.id,
            created_at=s.created_at.isoformat().replace("+00:00", "Z"),
            validation_status=s.validation_status.value,
            available_stem_roles=[role.value for role in s.available_stem_roles],
        )
        for s in sets
    ]


@router.get(
    "/projects/{project_id}/result-sets/{result_set_id}",
    response_model=ResultSetDetail,
)
async def get_result_set_detail(
    project_id: uuid.UUID, result_set_id: uuid.UUID, request: Request
) -> ResultSetDetail:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    detail = await asyncio.to_thread(
        _separation(request).get_result_set_detail, project_id, result_set_id
    )
    if detail is None:
        raise ResultSetNotFoundError(str(result_set_id))
    result_set, run, stems = detail
    return ResultSetDetail(
        id=result_set.id,
        created_at=result_set.created_at.isoformat().replace("+00:00", "Z"),
        validation_status=result_set.validation_status.value,
        cache_key=result_set.cache_key,
        stems=[
            ResultSetStemDetail(
                id=stem.id,
                role=stem.role.value,
                display_name=stem.display_name,
                audio_asset_id=stem.audio_asset_id,
                sample_rate=stem.sample_rate,
                channel_count=stem.channel_count,
                frame_count=stem.frame_count,
            )
            for stem in stems
        ],
        engine_version=run.engine_version,
        adapter_version=run.adapter_version,
        model_manifest_id=run.model_manifest_id,
        model_manifest_hash=run.model_manifest_hash,
    )
