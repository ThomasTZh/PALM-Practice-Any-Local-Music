"""The analysis-to-server seam: an ``analysis`` job kind and its persistence.

The Piper pipeline in :mod:`basseparate.features` is complete but was only
reachable from tests and the timing script. This module registers the job the
UI starts with ``POST /api/jobs``, reads the project's already decoded PCM
(no re-decode and no sample-rate mismatch), reports stage progress, honours
job cancellation, and merges the finished grid/key/chords into the project
document through the existing atomic revisioned store.

The job result is deliberately narrow; it is the UI panel contract and nothing
else::

    {"cached", "bpb", "bpm", "key", "chords", "beats", "bars"}

``beats``/``bars`` are numbers (seconds), and chord labels stay exactly as the
plugin emitted them. The document keeps the fuller analysis reference under
``analysis`` and the bar grid under ``grid``.

``job_routes`` is owned by t3, so :func:`install` wraps its parameter validator
to turn invalid analysis parameters and unknown projects into 400/404 before a
job is queued. Valid jobs still use the same shared ``JobManager`` and SSE
routes as imports and separation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from basseparate import features
from basseparate.api import job_routes
from basseparate.api.models import InvalidRequest
from basseparate.config import DataPaths
from basseparate.jobs import JobCancelled, JobContext, JobManager
from basseparate.piper import AnalysisCancelled
from basseparate.projects import (
    Project,
    ProjectStore,
    RevisionConflict,
    utc_now,
)

ANALYSIS_SCHEMA_VERSION = 1
ANALYSIS_CACHE_DIR = "analysis"
SHORT_CLIP_SECONDS = 8.0
MIN_BPB = 2
MAX_BPB = 16


class AnalysisJobError(RuntimeError):
    """Analysis job setup or persistence failed; safe to show to the user."""


class AnalysisParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    bpb: int = Field(default=4, ge=MIN_BPB, le=MAX_BPB)


def analysis_cache_dir(paths: DataPaths) -> Path:
    return paths.root / ANALYSIS_CACHE_DIR


def read_project_signal(project: Project, paths: DataPaths) -> NDArray[np.float32]:
    """Read the decoded project PCM as mono float32 at the project rate.

    The project owns one canonical decoded stream; analysis must not decode the
    source again because a second decode can pick different frame boundaries or
    a different rate.
    """
    audio = project.audio
    pcm = paths.asset_dir(audio.asset_id) / "pcm.f32"
    if not pcm.is_file():
        raise AnalysisJobError(
            f"decoded PCM for project {project.id} is missing: {pcm}. Re-import the source."
        )
    expected_bytes = audio.frames * audio.channels * 4
    actual_bytes = pcm.stat().st_size
    if actual_bytes != expected_bytes:
        raise AnalysisJobError(
            f"decoded PCM for project {project.id} is {actual_bytes} bytes, "
            f"expected {expected_bytes} ({audio.frames} frames × {audio.channels} channels)"
        )
    data = np.memmap(pcm, dtype="<f4", mode="r")
    if data.size != audio.frames * audio.channels:
        raise AnalysisJobError(
            f"decoded PCM for project {project.id} has {data.size} samples, "
            f"expected {audio.frames * audio.channels}"
        )
    matrix = data.reshape(audio.frames, audio.channels)
    signal = matrix[:, 0] if audio.channels == 1 else matrix.mean(axis=1, dtype=np.float32)
    return np.ascontiguousarray(signal, dtype=np.float32)


def analysis_result_payload(result: features.AnalysisResult) -> dict[str, Any]:
    """Map the pipeline result to the exact UI job-result contract."""
    return {
        "cached": result.cached,
        "bpb": result.grid.bpb,
        "bpm": result.bpm,
        "key": result.key.label,
        "chords": [
            {
                "start_seconds": chord.start_seconds,
                "end_seconds": chord.end_seconds,
                "label": chord.label,
            }
            for chord in result.chords
        ],
        "beats": [beat.time_seconds for beat in result.grid.beats],
        "bars": [bar.time_seconds for bar in result.grid.bars],
    }


def analysis_document(
    document: Mapping[str, Any], result: features.AnalysisResult
) -> dict[str, Any]:
    """Merge grid/key/chords/analysis meta into a project document copy."""
    payload = analysis_result_payload(result)
    beats: list[float] = payload["beats"]
    bars: list[float] = payload["bars"]
    offset = beats[0] if beats else 0.0
    grid = {
        "bpb": result.grid.bpb,
        "beats": beats,
        "bars": bars,
        "bpm": result.bpm,
        "meter": {"numerator": result.grid.bpb, "denominator": 4},
        "offsetSeconds": offset,
    }
    analysis = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "cache_key": result.meta.cache_key,
        "source_sha256": result.meta.source_sha256,
        "source_name": result.meta.source_name,
        "sample_rate": result.meta.sample_rate,
        "duration_seconds": result.meta.duration_seconds,
        "bpb": result.grid.bpb,
        "bpm": result.bpm,
        "key": result.key.label,
        "cached": result.cached,
        "lead_in_seconds": result.meta.lead_in_seconds,
        "elapsed_seconds": result.meta.elapsed_seconds,
        "updated_at": utc_now(),
        "plugins": [
            {
                "role": plugin.role,
                "display_name": plugin.display_name,
                "key": plugin.key,
                "version": plugin.version,
                "parameters": dict(sorted(plugin.parameters.items())),
                "block_size": plugin.block_size,
                "step_size": plugin.step_size,
            }
            for plugin in result.meta.plugins
        ],
    }
    merged = dict(document)
    merged["grid"] = grid
    merged["key"] = result.key.label
    merged["chords"] = payload["chords"]
    merged["analysis"] = analysis
    return merged


def publish_analysis(
    store: ProjectStore, project_id: str, result: features.AnalysisResult
) -> Project:
    """Atomically save the analysis into the project document, retrying races."""
    for _ in range(4):
        current = store.get(project_id)
        document = analysis_document(current.document, result)
        try:
            return store.update(project_id, document=document, expected_revision=current.revision)
        except RevisionConflict:
            continue
    raise AnalysisJobError(f"could not save analysis into project {project_id}")


def _lead_in_for(project: Project) -> float | None:
    """Short clips need Piper's silent lead/tail to place a downbeat."""
    if project.audio.duration_seconds < SHORT_CLIP_SECONDS:
        return features.WARM_UP_SECONDS
    return None


def analyze_project(
    project: Project,
    *,
    paths: DataPaths,
    bpb: int,
    progress: Callable[[float, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> features.AnalysisResult:
    """Run the existing feature pipeline on the project's decoded PCM."""
    if not MIN_BPB <= bpb <= MAX_BPB:
        raise AnalysisJobError(f"bpb must be between {MIN_BPB} and {MAX_BPB}, got {bpb}")

    def report(fraction: float, message: str) -> None:
        if progress is not None:
            progress(0.1 + 0.8 * max(0.0, min(1.0, fraction)), message)

    if progress is not None:
        progress(0.02, "reading project")
    signal = read_project_signal(project, paths)
    if progress is not None:
        progress(0.08, "analysing")
    try:
        return features.analyze_signal(
            signal,
            sample_rate=project.audio.sample_rate,
            source_sha256=project.audio.content_sha256,
            cache_dir=analysis_cache_dir(paths),
            bpb=bpb,
            lead_in_seconds=_lead_in_for(project),
            is_cancelled=is_cancelled,
            on_progress=report,
            source_name=project.audio.source_name,
        )
    except AnalysisCancelled as error:
        raise JobCancelled(str(error)) from error


def register_analysis_job(manager: JobManager, *, paths: DataPaths, store: ProjectStore) -> None:
    def run(context: JobContext, params: Mapping[str, Any]) -> object:
        request = AnalysisParams.model_validate(dict(params))
        project = store.get(request.project_id)
        result = analyze_project(
            project,
            paths=paths,
            bpb=request.bpb,
            progress=context.progress,
            is_cancelled=lambda: context.cancelled,
        )
        context.check_cancelled()
        if context.progress_value < 0.99:
            context.progress(0.97, "saving analysis")
        publish_analysis(store, request.project_id, result)
        return analysis_result_payload(result)

    manager.register("analysis", run)


def validate_analysis_params(kind: str, params: Mapping[str, Any], store: ProjectStore) -> None:
    """Validate analysis params before the generic job route queues a job."""
    if kind != "analysis":
        return
    try:
        request = AnalysisParams.model_validate(dict(params))
    except ValidationError as error:
        raise InvalidRequest(f"invalid analysis job parameters: {error}") from error
    store.get(request.project_id)  # ProjectNotFound maps to 404


def install(app: FastAPI) -> None:
    """Register the analysis job and its pre-queue validation once per app."""
    if getattr(app.state, "analysis_jobs_installed", False):
        return
    paths: DataPaths = app.state.paths
    store: ProjectStore = app.state.projects
    jobs: JobManager = app.state.jobs
    register_analysis_job(jobs, paths=paths, store=store)
    setattr(job_routes, "_analysis_store", store)  # noqa: B010 - dynamic seam
    if not getattr(job_routes, "_analysis_validator_installed", False):
        original = getattr(job_routes, "validate_job_params")  # noqa: B009

        def validate(kind: str, params: Mapping[str, Any]) -> None:
            if kind == "analysis":
                active = getattr(job_routes, "_analysis_store", store)
                validate_analysis_params(kind, params, active)
            original(kind, params)

        setattr(job_routes, "validate_job_params", validate)  # noqa: B010
        setattr(job_routes, "_analysis_validator_installed", True)  # noqa: B010
    app.state.analysis_jobs_installed = True


__all__ = [
    "ANALYSIS_SCHEMA_VERSION",
    "AnalysisJobError",
    "AnalysisParams",
    "analysis_cache_dir",
    "analysis_document",
    "analysis_result_payload",
    "analyze_project",
    "install",
    "publish_analysis",
    "read_project_signal",
    "register_analysis_job",
    "validate_analysis_params",
]
