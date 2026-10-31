"""Project, PCM and peak routes; all reads are ranged and bounded."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from basseparate.api.deps import PathsDep, StoreDep
from basseparate.api.models import ProjectUpdateRequest
from basseparate.config import DataPaths
from basseparate.media import MediaError, read_pcm_range
from basseparate.peaks import PEAK_BUCKET_SIZES
from basseparate.projects import project_response

router = APIRouter(tags=["projects"])

BINARY_MEDIA_TYPE = "application/octet-stream"
ASSET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def validate_bucket_size(bucket_size: int) -> int:
    if bucket_size not in PEAK_BUCKET_SIZES:
        choices = ", ".join(str(size) for size in PEAK_BUCKET_SIZES)
        raise HTTPException(
            status_code=400,
            detail=f"unsupported bucket size {bucket_size}; choose one of {choices}",
        )
    return bucket_size


def validate_asset_id(asset_id: str) -> str:
    if not ASSET_ID_PATTERN.fullmatch(asset_id):
        raise HTTPException(status_code=404, detail=f"asset {asset_id!r} not found")
    return asset_id


def peaks_path(paths: DataPaths, asset_id: str, bucket_size: int) -> Path:
    return paths.asset_dir(validate_asset_id(asset_id)) / f"peaks-{bucket_size}.bin"


@router.get("/projects")
def list_projects(store: StoreDep) -> dict[str, Any]:
    return {"projects": [project_response(project) for project in store.list()]}


@router.get("/projects/{project_id}")
def get_project(project_id: str, store: StoreDep) -> dict[str, Any]:
    return project_response(store.get(project_id))


@router.put("/projects/{project_id}")
def save_project(
    project_id: str,
    body: ProjectUpdateRequest,
    store: StoreDep,
) -> dict[str, Any]:
    project = store.update(
        project_id,
        name=body.name,
        document=body.document,
        expected_revision=body.revision,
    )
    return project_response(project)


@router.get("/projects/{project_id}/media")
def project_media(project_id: str, store: StoreDep) -> dict[str, Any]:
    project = store.get(project_id)
    return project.audio.model_dump(mode="json")


@router.get("/projects/{project_id}/pcm")
def project_pcm(
    project_id: str,
    paths: PathsDep,
    store: StoreDep,
    start: int = Query(default=0),
    end: int | None = Query(default=None),
) -> Response:
    project = store.get(project_id)
    total = project.audio.frames
    pcm = paths.asset_dir(project.audio.asset_id) / "pcm.f32"
    if not pcm.is_file():
        raise HTTPException(
            status_code=404, detail=f"decoded PCM for project {project_id} is missing"
        )
    payload = read_pcm_range(
        pcm,
        channels=project.audio.channels,
        start=start,
        end=total if end is None else end,
        total_frames=total,
    )
    resolved_end = total if end is None else end
    return Response(
        content=payload,
        media_type=BINARY_MEDIA_TYPE,
        headers={
            "x-frame-start": str(start),
            "x-frame-end": str(resolved_end),
            "x-frame-count": str(resolved_end - start),
            "x-sample-rate": str(project.audio.sample_rate),
            "x-channels": str(project.audio.channels),
            "x-total-frames": str(total),
            "cache-control": "private, max-age=3600",
        },
    )


@router.get("/projects/{project_id}/peaks/{bucket_size}")
def project_peaks(
    project_id: str,
    bucket_size: int,
    paths: PathsDep,
    store: StoreDep,
) -> Response:
    validate_bucket_size(bucket_size)
    project = store.get(project_id)
    path = peaks_path(paths, project.audio.asset_id, bucket_size)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"peaks {bucket_size} for project {project_id} are missing",
        )
    return Response(
        content=path.read_bytes(),
        media_type=BINARY_MEDIA_TYPE,
        headers={
            "x-bucket-size": str(bucket_size),
            "x-channels": str(project.audio.channels),
            "x-sample-rate": str(project.audio.sample_rate),
            "cache-control": "private, max-age=3600",
        },
    )


@router.get("/assets/{asset_id}/peaks")
def asset_peaks(
    asset_id: str,
    paths: PathsDep,
    buckets: int = Query(default=1024),
) -> Response:
    validate_bucket_size(buckets)
    path = peaks_path(paths, asset_id, buckets)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"asset {asset_id} has no peaks")
    return Response(
        content=path.read_bytes(),
        media_type=BINARY_MEDIA_TYPE,
        headers={
            "x-bucket-size": str(buckets),
            "cache-control": "private, max-age=3600",
        },
    )


@router.get("/assets/{asset_id}")
def asset_metadata(asset_id: str, paths: PathsDep) -> dict[str, Any]:
    path = paths.asset_dir(validate_asset_id(asset_id)) / "asset.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"asset {asset_id} not found")
    try:
        payload: dict[str, Any] = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MediaError(f"asset {asset_id} manifest is unreadable: {error}") from error
    return payload


__all__ = ["project_pcm", "project_peaks", "router", "validate_bucket_size"]
