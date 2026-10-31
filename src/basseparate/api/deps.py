"""Dependency helpers: the server-owned objects attached to ``app.state``."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from basseparate.config import DataPaths, Settings
from basseparate.jobs import JobManager
from basseparate.projects import ProjectStore


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_paths(request: Request) -> DataPaths:
    paths: DataPaths = request.app.state.paths
    return paths


def get_store(request: Request) -> ProjectStore:
    store: ProjectStore = request.app.state.projects
    return store


def get_jobs(request: Request) -> JobManager:
    jobs: JobManager = request.app.state.jobs
    return jobs


SettingsDep = Annotated[Settings, Depends(get_settings)]
PathsDep = Annotated[DataPaths, Depends(get_paths)]
StoreDep = Annotated[ProjectStore, Depends(get_store)]
JobsDep = Annotated[JobManager, Depends(get_jobs)]
