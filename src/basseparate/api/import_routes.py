"""Import routes: path import, multipart upload, library view and the import job."""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import ValidationError

from basseparate.api.deps import JobsDep, PathsDep, SettingsDep, StoreDep
from basseparate.api.models import (
    ImportPathRequest,
    InvalidRequest,
    parse_sample_rate_text,
    validate_sample_rate_value,
)
from basseparate.api.uploads import parse_multipart_upload
from basseparate.config import DataPaths, Settings
from basseparate.jobs import Job, JobContext, JobManager
from basseparate.media import import_media
from basseparate.projects import (
    Project,
    ProjectStore,
    build_audio_info,
    build_project,
    project_response,
)

router = APIRouter(tags=["library"])

ProgressCallback = Callable[[float, str], None]
CancelCallback = Callable[[], bool]


def library_entry(project: Project) -> dict[str, Any]:
    audio = project.audio
    return {
        "id": project.id,
        "title": project.name,
        "durationSeconds": audio.duration_seconds,
        "sampleRate": audio.sample_rate,
        "channels": audio.channels,
        "importedAt": project.created_at,
        "projectId": project.id,
    }


def import_source(
    *,
    settings: Settings,
    paths: DataPaths,
    store: ProjectStore,
    source: Path,
    name: str | None = None,
    sample_rate: int | None = None,
    progress: ProgressCallback | None = None,
    is_cancelled: CancelCallback | None = None,
) -> Project:
    """One import path shared by the synchronous route and the background job."""
    asset = import_media(
        source,
        assets_root=paths.assets,
        sample_rate=sample_rate,
        progress=progress,
        is_cancelled=is_cancelled,
    )
    audio = build_audio_info(
        asset_id=asset.asset_id,
        source_name=asset.source_name,
        source_format=asset.source_format,
        sample_rate=asset.sample_rate,
        channels=asset.channels,
        frames=asset.frames,
        content_sha256=asset.content_sha256,
        peak_counts=asset.peak_counts,
        codec=asset.codec,
    )
    project = build_project(audio, name=name or Path(asset.source_name).stem)
    return store.create(project)


def register_import_job(
    manager: JobManager,
    *,
    settings: Settings,
    paths: DataPaths,
    store: ProjectStore,
) -> None:
    def runner(context: JobContext, params: Mapping[str, Any]) -> dict[str, Any]:
        request = ImportPathRequest.model_validate(params)
        project = import_source(
            settings=settings,
            paths=paths,
            store=store,
            source=Path(request.path),
            name=request.name,
            sample_rate=request.sample_rate,
            progress=context.progress,
            is_cancelled=lambda: context.cancelled,
        )
        context.check_cancelled()
        return project_response(project)

    manager.register("import", runner)


@router.post("/imports", status_code=status.HTTP_201_CREATED)
def import_from_path(
    body: ImportPathRequest,
    settings: SettingsDep,
    paths: PathsDep,
    store: StoreDep,
) -> dict[str, Any]:
    project = import_source(
        settings=settings,
        paths=paths,
        store=store,
        source=Path(body.path),
        name=body.name,
        sample_rate=body.sample_rate,
    )
    return project_response(project)


async def _import_upload(
    request: Request,
    *,
    settings: Settings,
    paths: DataPaths,
    store: ProjectStore,
    name: str | None,
    sample_rate: int | None,
) -> dict[str, Any]:
    upload_root = paths.upload_dir(uuid.uuid4().hex)
    try:
        form = await parse_multipart_upload(
            request, target_dir=upload_root, max_bytes=settings.max_upload_bytes
        )
        if not form.files:
            raise HTTPException(
                status_code=400, detail="multipart upload must include a 'file' part"
            )
        uploaded = form.files.get("file") or next(iter(form.files.values()))
        display_name = name or form.fields.get("name") or Path(uploaded.filename).stem
        effective_rate = validate_sample_rate_value(sample_rate)
        if effective_rate is None:
            effective_rate = parse_sample_rate_text(form.fields.get("sample_rate"))
        project = import_source(
            settings=settings,
            paths=paths,
            store=store,
            source=uploaded.path,
            name=display_name,
            sample_rate=effective_rate,
        )
        return {"entry": library_entry(project), "project": project_response(project)}
    finally:
        shutil.rmtree(upload_root, ignore_errors=True)


@router.post("/library/import", status_code=status.HTTP_201_CREATED)
async def library_import(
    request: Request,
    settings: SettingsDep,
    paths: PathsDep,
    store: StoreDep,
    name: str | None = Query(default=None, max_length=200),
    sample_rate: int | None = Query(default=None),
) -> dict[str, Any]:
    return await _import_upload(
        request,
        settings=settings,
        paths=paths,
        store=store,
        name=name,
        sample_rate=sample_rate,
    )


@router.post("/imports/upload", status_code=status.HTTP_201_CREATED)
async def import_upload(
    request: Request,
    settings: SettingsDep,
    paths: PathsDep,
    store: StoreDep,
    name: str | None = Query(default=None, max_length=200),
    sample_rate: int | None = Query(default=None),
) -> dict[str, Any]:
    result = await _import_upload(
        request,
        settings=settings,
        paths=paths,
        store=store,
        name=name,
        sample_rate=sample_rate,
    )
    project: dict[str, Any] = result["project"]
    return project


@router.get("/library")
def library(store: StoreDep) -> dict[str, Any]:
    entries = [library_entry(project) for project in store.list()]
    return {"entries": entries}


@router.post("/imports/jobs", status_code=status.HTTP_202_ACCEPTED)
def import_as_job(
    body: ImportPathRequest,
    jobs: JobsDep,
) -> dict[str, Any]:
    job: Job = jobs.submit(
        "import",
        {
            "path": body.path,
            "name": body.name,
            "sample_rate": body.sample_rate,
        },
    )
    return job.to_dict()


def validate_job_params(kind: str, params: Mapping[str, Any]) -> None:
    """Route-level job parameter validation keeps failures out of the worker."""
    if kind != "import":
        return
    try:
        ImportPathRequest.model_validate(dict(params))
    except ValidationError as error:
        raise InvalidRequest(f"invalid import job parameters: {error}") from error
