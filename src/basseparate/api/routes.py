"""API route handlers for Milestone 0 (M0.6).

Routes:
- GET /api/v1/health — unauthenticated liveness/readiness
- GET /api/v1/system — authenticated version and runtime status
- GET /api/v1/projects — list working projects
- POST /api/v1/projects — create an empty working project
- GET /api/v1/projects/{id} — retrieve project
- GET /api/v1/modules — empty installed-module list
- GET /api/v1/models — empty installed-model list
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, cast

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from basseparate import API_VERSION, APP_VERSION
from basseparate.api.errors import (
    IdempotencyConflictError,
    ProjectNotFoundError,
)
from basseparate.api.idempotency import IdempotencyStore
from basseparate.domain.project import ProjectRecord
from basseparate.storage import ProjectRepository

router = APIRouter(prefix="/api/v1")


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @property
    def trimmed_name(self) -> str:
        return self.name.strip()


class HealthResponse(BaseModel):
    status: str
    api_version: int


class SystemResponse(BaseModel):
    app_version: str
    api_version: int
    ready: bool


class ProjectListResponse(BaseModel):
    projects: list[ProjectRecord]


class ModuleListResponse(BaseModel):
    modules: list[dict[str, Any]] = Field(default_factory=list)


class ModelListResponse(BaseModel):
    models: list[dict[str, Any]] = Field(default_factory=list)


def _is_ready(request: Request) -> bool:
    return bool(getattr(request.app.state, "ready", False))


def _repo(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _idempotency_store(request: Request) -> IdempotencyStore:
    return cast(IdempotencyStore, request.app.state.idempotency_store)


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    if not _is_ready(request):
        return HealthResponse(status="starting", api_version=API_VERSION)
    return HealthResponse(status="ready", api_version=API_VERSION)


@router.get("/system", response_model=SystemResponse)
async def system(request: Request) -> SystemResponse:
    return SystemResponse(
        app_version=APP_VERSION,
        api_version=API_VERSION,
        ready=_is_ready(request),
    )


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(request: Request) -> ProjectListResponse:
    repo = _repo(request)
    projects = repo.list_projects()
    return ProjectListResponse(projects=projects)


@router.post(
    "/projects",
    response_model=ProjectRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(request: Request, body: CreateProjectRequest) -> ProjectRecord:
    repo = _repo(request)
    idempotency_key = request.headers.get("Idempotency-Key")

    if idempotency_key:
        store = _idempotency_store(request)
        body_hash = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        existing = store.get(idempotency_key)
        if existing is not None:
            if existing.body_hash != body_hash:
                raise IdempotencyConflictError()
            return cast(ProjectRecord, existing.payload)

    trimmed = body.name.strip()
    if not trimmed:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="Project name must not be blank")
    project = repo.create_project(trimmed)

    if idempotency_key:
        store = _idempotency_store(request)
        store.set(idempotency_key, body_hash, project)

    return project


@router.get("/projects/{project_id}", response_model=ProjectRecord)
async def get_project(project_id: uuid.UUID, request: Request) -> ProjectRecord:
    repo = _repo(request)
    project = repo.get_project(project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    return project


@router.get("/modules", response_model=ModuleListResponse)
async def list_modules() -> ModuleListResponse:
    return ModuleListResponse(modules=[])


@router.get("/models", response_model=ModelListResponse)
async def list_models() -> ModelListResponse:
    return ModelListResponse(models=[])
