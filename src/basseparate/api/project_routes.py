"""Project, PCM and peak routes; all reads are ranged and bounded."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from basseparate.api.deps import PathsDep, StoreDep
from basseparate.api.models import ProjectUpdateRequest
from basseparate.config import DataPaths
from basseparate.media import (
    MediaError,
    RangeError,
    pcm_response_headers,
    read_pcm_slice,
    unsatisfiable_range_headers,
)
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


def range_error_response(error: RangeError, total_bytes: int) -> Response:
    return Response(
        content=json.dumps({"detail": str(error)}).encode(),
        status_code=416,
        media_type="application/json",
        headers=unsatisfiable_range_headers(total_bytes),
    )


@router.get("/projects/{project_id}/pcm")
def project_pcm(
    project_id: str,
    request: Request,
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
    total_bytes = pcm.stat().st_size
    try:
        sliced = read_pcm_slice(
            pcm,
            channels=project.audio.channels,
            total_frames=total,
            range_header=request.headers.get("range"),
            start=start,
            end=end,
        )
    except RangeError as error:
        return range_error_response(error, total_bytes)
    return Response(
        content=sliced.payload,
        status_code=sliced.status_code,
        media_type=BINARY_MEDIA_TYPE,
        headers=pcm_response_headers(
            start_frame=sliced.start_frame,
            end_frame=sliced.end_frame,
            total_frames=sliced.total_frames,
            sample_rate=project.audio.sample_rate,
            channels=project.audio.channels,
            content_range=sliced.content_range,
        ),
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
