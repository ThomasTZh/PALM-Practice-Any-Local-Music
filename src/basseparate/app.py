"""Application factory and lifecycle (M0.6).

``create_app(config)`` builds a FastAPI instance with:
- Lifespan-managed startup/shutdown.
- Storage initialization.
- Database initialization and migration.
- Session token creation.
- Request tracing middleware.
- API routes.

No filesystem mutations, background workers, browser opens, or network
requests occur at module import time.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request
from starlette.staticfiles import StaticFiles

from basseparate import API_VERSION
from basseparate.api.errors import ApiError, create_error_response
from basseparate.api.idempotency import IdempotencyStore
from basseparate.api.import_routes import router as import_router
from basseparate.api.job_routes import router as job_router
from basseparate.api.middleware import RequestTracingMiddleware
from basseparate.api.playback_routes import router as playback_router
from basseparate.api.routes import router
from basseparate.api.security import SecurityMiddleware
from basseparate.config import AppConfig
from basseparate.domain.asset import AssetRecord
from basseparate.domain.import_record import TransferState
from basseparate.domain.media_job import JobType, MediaJob
from basseparate.domain.project import (
    MAX_SAMPLE_RATE,
    MIN_SAMPLE_RATE,
    ProjectRecord,
)
from basseparate.jobs import JobManager, ParameterResolutionError, build_publishers
from basseparate.media.downmix import MonitorSelectionError, pan_expression, resolve_downmix
from basseparate.storage import (
    ImportRepository,
    JobRepository,
    ProjectRepository,
    RepresentationRepository,
    StoragePaths,
    WaveformCacheRepository,
    initialize_database,
    initialize_storage_paths,
    resolve_storage_paths,
)
from basseparate.uploads import UploadManager

log = logging.getLogger(__name__)


def _decode_parameters_for(job: MediaJob, imports: ImportRepository) -> dict[str, Any]:
    """Worker parameters for a canonical decode, from the import's probe.

    Returns an empty dict when no valid stream selection exists; the
    JobManager turns that into a ``NO_STREAM_SELECTION`` failure before the
    worker is involved.
    """
    if job.job_type is not JobType.CANONICAL_DECODE or job.import_id is None:
        return {}
    import_record = imports.get_import(job.import_id)
    if import_record is None:
        return {}
    if import_record.transfer_state is not TransferState.COMPLETE:
        return {}
    probe = import_record.probe_result
    if probe is None or import_record.selected_stream_index is None:
        return {}
    stream = next(
        (s for s in probe.audio_streams if s.index == import_record.selected_stream_index),
        None,
    )
    if stream is None:
        return {}
    parameters: dict[str, Any] = {
        "stream_index": stream.index,
        "sample_rate": stream.sample_rate,
        "channel_count": stream.channel_count,
    }
    if stream.channel_layout is not None:
        parameters["channel_layout"] = stream.channel_layout
    if probe.estimated_duration_seconds is not None:
        parameters["estimated_duration_seconds"] = probe.estimated_duration_seconds
    if stream.start_timestamp_seconds is not None:
        parameters["start_timestamp_seconds"] = stream.start_timestamp_seconds
    return parameters


def _canonical_pcm_asset(
    job: MediaJob, projects: ProjectRepository
) -> tuple[ProjectRecord, AssetRecord]:
    """The project and its canonical PCM asset (or raise NO_CANONICAL)."""
    project = projects.get_project(job.project_id)
    if project is None:
        raise ParameterResolutionError(
            "NO_CANONICAL", f"project {job.project_id} no longer exists"
        )
    if project.canonical_asset_id is None:
        raise ParameterResolutionError(
            "NO_CANONICAL", "the project has no canonical audio"
        )
    asset = projects.get_asset(project.canonical_asset_id)
    if asset is None or asset.audio is None:
        raise ParameterResolutionError(
            "NO_CANONICAL", "the project's canonical audio asset is unavailable"
        )
    return project, asset


def _downmix_parameters_for(
    job: MediaJob, projects: ProjectRepository, paths: StoragePaths
) -> dict[str, Any]:
    """Worker parameters for a monitoring downmix, from the project (M1.7).

    The matrix is resolved per spec §9.3: the standard 5.1 rows for a
    6-channel "5.1" source, the user's stored L/R selection for any other
    multichannel layout. Mono/stereo sources need no downmix at all.
    """
    if job.job_type is not JobType.MONITORING_DOWNMIX:
        return {}
    project, asset = _canonical_pcm_asset(job, projects)
    audio = asset.audio
    assert audio is not None
    try:
        resolved = resolve_downmix(
            audio.channel_count,
            project.source_channel_layout,
            project.monitoring_left_channel,
            project.monitoring_right_channel,
        )
    except MonitorSelectionError as exc:
        raise ParameterResolutionError("MISSING_MONITORING_SELECTION", str(exc)) from exc
    if resolved is None:
        raise ParameterResolutionError(
            "NO_DOWNMIX_NEEDED",
            "the source is mono or stereo; the canonical audio is already the "
            "monitoring representation",
        )
    mode, left_row, right_row = resolved
    if mode == "manual":
        # resolve_downmix raised when either selection is missing.
        left_channel = cast(int, project.monitoring_left_channel)
        right_channel = cast(int, project.monitoring_right_channel)
    else:  # standard_5_1: the effective sources are FL/FR
        left_channel, right_channel = 0, 1
    return {
        "source_pcm_path": str(paths.resolve_asset_path(asset.relative_path)),
        "sample_rate": audio.sample_rate,
        "channel_count": audio.channel_count,
        "pan_spec": pan_expression(left_row, right_row),
        "downmix_mode": mode,
        "left_channel": left_channel,
        "right_channel": right_channel,
        "estimated_duration_seconds": audio.frame_count / audio.sample_rate,
    }


def _playback_parameters_for(
    job: MediaJob, projects: ProjectRepository, paths: StoragePaths
) -> dict[str, Any]:
    """Worker parameters for a playback-rate conversion (M1.7).

    The source is the monitoring asset when present (playback listens to
    what the user monitors), else the canonical asset.
    """
    if job.job_type is not JobType.PLAYBACK_RATE:
        return {}
    target = job.parameters.get("target_sample_rate")
    if isinstance(target, bool) or not isinstance(target, int):
        raise ParameterResolutionError(
            "INVALID_TARGET_RATE",
            "playback_rate jobs require an integer target_sample_rate "
            "(8000-192000 Hz)",
        )
    if not MIN_SAMPLE_RATE <= target <= MAX_SAMPLE_RATE:
        raise ParameterResolutionError(
            "INVALID_TARGET_RATE",
            f"target_sample_rate {target} Hz is outside the supported range "
            f"{MIN_SAMPLE_RATE}-{MAX_SAMPLE_RATE} Hz",
        )
    project, _canonical = _canonical_pcm_asset(job, projects)
    source_id = project.monitoring_asset_id or project.canonical_asset_id
    asset = projects.get_asset(source_id) if source_id is not None else None
    if asset is None or asset.audio is None:
        raise ParameterResolutionError(
            "NO_CANONICAL", "the project's source audio asset is unavailable"
        )
    audio = asset.audio
    return {
        "source_pcm_path": str(paths.resolve_asset_path(asset.relative_path)),
        "sample_rate": audio.sample_rate,
        "channel_count": audio.channel_count,
        "target_sample_rate": target,
        "estimated_duration_seconds": audio.frame_count / audio.sample_rate,
    }


def _waveform_parameters_for(
    job: MediaJob, projects: ProjectRepository, paths: StoragePaths
) -> dict[str, Any]:
    """Worker parameters for a waveform pyramid build (M1.8).

    The source is the canonical PCM asset; the cache is keyed by its
    content hash under the storage cache category.
    """
    if job.job_type is not JobType.WAVEFORM:
        return {}
    _project, asset = _canonical_pcm_asset(job, projects)
    audio = asset.audio
    assert audio is not None
    return {
        "source_path": str(paths.resolve_asset_path(asset.relative_path)),
        "source_hash": asset.content_hash,
        "sample_rate": audio.sample_rate,
        "frame_count": audio.frame_count,
        "channel_count": audio.channel_count,
        "cache_dir": str(paths.cache / "waveforms" / asset.content_hash),
    }


def _job_parameters_for(
    job: MediaJob,
    imports: ImportRepository,
    projects: ProjectRepository,
    paths: StoragePaths,
) -> dict[str, Any]:
    """Worker parameters for any job type (M1.4 decode, M1.7/M1.8 derived)."""
    if job.job_type is JobType.CANONICAL_DECODE:
        return _decode_parameters_for(job, imports)
    if job.job_type is JobType.MONITORING_DOWNMIX:
        return _downmix_parameters_for(job, projects, paths)
    if job.job_type is JobType.PLAYBACK_RATE:
        return _playback_parameters_for(job, projects, paths)
    if job.job_type is JobType.WAVEFORM:
        return _waveform_parameters_for(job, projects, paths)
    return {}


def _static_dir() -> Path | None:
    """Locate the built frontend assets.

    Prefers package data (wheel install layout ``basseparate/web/static``)
    and falls back to the source tree ``frontend/dist`` for development.
    """
    package_static = Path(__file__).resolve().parent / "web" / "static"
    if (package_static / "index.html").is_file():
        return package_static
    source_static = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if (source_static / "index.html").is_file():
        return source_static
    return None


def create_app(config: AppConfig) -> FastAPI:
    """Build a FastAPI application from an explicit configuration.

    Safe to call multiple times for isolated test instances.
    """

    # Generate session token at creation time so middleware can use it.
    session_token = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # --- Startup ---
        paths = resolve_storage_paths(config.storage_root)
        initialize_storage_paths(paths)
        initialize_database(paths.database_path)

        app.state.config = config
        app.state.storage_paths = paths
        app.state.repository = ProjectRepository(paths.database_path)
        app.state.import_repository = ImportRepository(paths.database_path)
        app.state.upload_manager = UploadManager(
            uploads_dir=paths.runtime / "uploads",
            chunk_size=config.import_chunk_bytes,
            max_import_bytes=config.max_import_bytes,
        )
        app.state.idempotency_store = IdempotencyStore()
        app.state.session_token = session_token
        app.state.job_repository = JobRepository(paths.database_path)
        representation_repository = RepresentationRepository(paths.database_path)
        app.state.representation_repository = representation_repository
        cache_repository = WaveformCacheRepository(paths.database_path, paths.cache)
        app.state.waveform_cache_repository = cache_repository
        import_repository = cast(ImportRepository, app.state.import_repository)
        app.state.job_manager = JobManager(
            repository=cast(JobRepository, app.state.job_repository),
            staging_root=paths.runtime / "jobs",
            source_path_for=app.state.upload_manager.part_path_for,
            publisher=build_publishers(
                import_repository,
                cast(ProjectRepository, app.state.repository),
                representation_repository,
                paths,
                cast(JobRepository, app.state.job_repository),
                cache_repository,
            ),
            parameters_for=lambda job: _job_parameters_for(
                job,
                import_repository,
                cast(ProjectRepository, app.state.repository),
                paths,
            ),
        )
        app.state.ready = True
        log.info("basseparate service ready (api v%d)", API_VERSION)

        await app.state.job_manager.start()

        yield

        # --- Shutdown ---
        app.state.ready = False
        await app.state.job_manager.stop()
        app.state.idempotency_store.clear()
        log.info("basseparate service stopped")

    app = FastAPI(
        title="basseparate",
        version=str(API_VERSION),
        lifespan=lifespan,
    )
    app.state.session_token = session_token

    # Request tracing (outermost middleware).
    app.add_middleware(RequestTracingMiddleware)

    # Security: bearer auth, Host/Origin validation, rate limiting.
    app.add_middleware(SecurityMiddleware, session_token=session_token)

    # API error handler.
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> object:
        request_id = getattr(request.state, "request_id", "unknown")
        return create_error_response(request, exc, request_id)

    # Routes.
    app.include_router(router)
    app.include_router(import_router)
    app.include_router(job_router)
    app.include_router(playback_router)

    # Static frontend shell, served from the backend origin (M0.8).
    # Mounted after the API router so /api/* routes take precedence.
    static_dir = _static_dir()
    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
