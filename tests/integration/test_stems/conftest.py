"""Session fixtures for the real Demucs stem integration tests."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from basseparate.config import DataPaths, Settings
from basseparate.media import import_media
from basseparate.projects import (
    Project,
    ProjectStore,
    build_audio_info,
    build_project,
)
from basseparate.stems import StemSet, publish_project_stems, separate_project

ROOT = Path(__file__).resolve().parents[3]
AUDIO = ROOT / "tests" / "fixtures" / "audio"
CHORDS = AUDIO / "chords_c_am_f_g.wav"


@dataclass
class StemWorkspace:
    settings: Settings
    paths: DataPaths
    store: ProjectStore
    project: Project
    stem_set: StemSet
    wall_seconds: float
    progress: list[tuple[float, str]] = field(default_factory=list)


@pytest.fixture(scope="session")
def stem_workspace(tmp_path_factory: pytest.TempPathFactory) -> StemWorkspace:
    root = tmp_path_factory.mktemp("stems")
    settings = Settings(data_dir=root / "data", web_dir=root / "webdist")
    paths = settings.data_paths.ensure()
    store = ProjectStore(paths.projects)
    asset = import_media(CHORDS, assets_root=paths.assets, sample_rate=48_000)
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
    project = store.create(build_project(audio, name="chords c am f g"))
    progress: list[tuple[float, str]] = []
    started = time.perf_counter()
    stem_set = separate_project(
        project,
        paths=paths,
        device="cpu",
        progress=lambda fraction, message: progress.append((fraction, message)),
    )
    wall_seconds = time.perf_counter() - started
    publish_project_stems(store, project.id, stem_set)
    return StemWorkspace(
        settings=settings,
        paths=paths,
        store=store,
        project=store.get(project.id),
        stem_set=stem_set,
        wall_seconds=wall_seconds,
        progress=progress,
    )
