"""Reopen, autosave, export and doctor routes for the local studio."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from basseparate.api.deps import PathsDep, SettingsDep, StoreDep
from basseparate.config import DataPaths
from basseparate.doctor import DoctorLayout, diagnose
from basseparate.export import (
    ChannelMix,
    ExportError,
    MixerSpec,
    export_mixdown,
    safe_export_component,
)
from basseparate.persist import (
    MissingAssetError,
    PersistenceError,
    PracticeState,
    ProjectPersistence,
    restore_state,
)
from basseparate.projects import ProjectStore, project_response

router = APIRouter(tags=["export"])
alias_router = APIRouter(tags=["meta"])
EXPORT_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class ChannelMixRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gain: float = Field(default=1.0, ge=0.0)
    muted: bool = False
    mute: bool | None = None
    solo: bool = False
    pan: float = Field(default=0.0, ge=-1.0, le=1.0)

    def to_domain(self) -> ChannelMix:
        return ChannelMix(
            gain=self.gain,
            muted=self.muted or bool(self.mute),
            solo=self.solo,
            pan=self.pan,
        )


class MixerRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stems: dict[str, ChannelMixRequest] = Field(default_factory=dict)
    channels: dict[str, ChannelMixRequest] = Field(default_factory=dict)
    master_gain: float = Field(default=1.0, ge=0.0)

    def to_domain(self) -> MixerSpec:
        merged = {key: value.to_domain() for key, value in self.channels.items()}
        merged.update({key: value.to_domain() for key, value in self.stems.items()})
        return MixerSpec(channels=merged, master_gain=self.master_gain)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mixer: MixerRequest | None = None
    filename: str | None = Field(default=None, max_length=120)


class StateSaveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    state: PracticeState
    revision: int | None = Field(default=None, ge=1)


def persistence_for(store: ProjectStore, paths: DataPaths) -> ProjectPersistence:
    return ProjectPersistence(store, paths.assets)


def _export_root(paths: DataPaths, project_id: str) -> Path:
    return paths.root / "exports" / project_id


def _download_url(project_id: str, export_id: str) -> str:
    return f"/api/projects/{project_id}/exports/{export_id}.wav"


def doctor_report(settings: SettingsDep) -> dict[str, Any]:
    return diagnose(DoctorLayout.default(settings.data_dir)).to_dict()


@router.get("/doctor")
def get_doctor(settings: SettingsDep) -> dict[str, Any]:
    return doctor_report(settings)


@alias_router.get("/doctor")
def get_doctor_root(settings: SettingsDep) -> dict[str, Any]:
    return doctor_report(settings)


@router.get("/projects/{project_id}/state")
def get_state(
    project_id: str,
    store: StoreDep,
    paths: PathsDep,
) -> dict[str, Any]:
    persistence = persistence_for(store, paths)
    try:
        reopened = persistence.load_state(project_id)
    except PersistenceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    missing = persistence.missing_assets(reopened.project)
    return {
        "state": reopened.state.model_dump(mode="json"),
        "assets": {"ok": not missing, "missing": missing},
    }


@router.get("/projects/{project_id}/reopen")
def reopen_project(
    project_id: str,
    store: StoreDep,
    paths: PathsDep,
) -> dict[str, Any]:
    persistence = persistence_for(store, paths)
    try:
        reopened = persistence.reopen(project_id)
    except MissingAssetError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except PersistenceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "project": project_response(reopened.project),
        "state": reopened.state.model_dump(mode="json"),
        "assets": {"ok": True, "missing": []},
    }


@router.put("/projects/{project_id}/state")
def save_state(
    project_id: str,
    body: StateSaveRequest,
    store: StoreDep,
    paths: PathsDep,
) -> dict[str, Any]:
    persistence = persistence_for(store, paths)
    try:
        project = persistence.save_state(
            project_id, body.state, expected_revision=body.revision
        )
        saved = restore_state(project.document)
    except PersistenceError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "project": project_response(project),
        "state": saved.model_dump(mode="json"),
    }


@router.post("/projects/{project_id}/exports", status_code=status.HTTP_201_CREATED)
def create_export(
    project_id: str,
    body: ExportRequest,
    store: StoreDep,
    paths: PathsDep,
) -> dict[str, Any]:
    project = store.get(project_id)
    export_id = uuid.uuid4().hex
    root = _export_root(paths, project_id)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{export_id}.wav"
    mixer = body.mixer.to_domain() if body.mixer is not None else None
    try:
        result = export_mixdown(
            project,
            assets_root=paths.assets,
            destination=destination,
            mixer=mixer,
        )
    except ExportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    display = body.filename or project.name
    return {
        "id": export_id,
        "project_id": project_id,
        "filename": destination.name,
        "display_name": f"{safe_export_component(display)}.wav",
        "download_url": _download_url(project_id, export_id),
        **result.to_dict(),
    }


@router.get("/projects/{project_id}/exports/{export_id}.wav")
def download_export(
    project_id: str,
    export_id: str,
    store: StoreDep,
    paths: PathsDep,
) -> FileResponse:
    store.get(project_id)  # 404 when the project is unknown
    if not EXPORT_ID_PATTERN.fullmatch(export_id):
        raise HTTPException(status_code=404, detail="export not found")
    path = _export_root(paths, project_id) / f"{export_id}.wav"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="export not found")
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=safe_export_component(project_id) + ".wav",
    )


__all__ = ["alias_router", "router"]
