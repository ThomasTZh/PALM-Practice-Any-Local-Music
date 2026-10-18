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

import asyncio
import contextlib
import logging
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request
from starlette.staticfiles import StaticFiles

from basseparate import API_VERSION
from basseparate.api.asset_routes import router as asset_router
from basseparate.api.command_routes import router as command_router
from basseparate.api.errors import ApiError, create_error_response
from basseparate.api.export_routes import router as export_router
from basseparate.api.idempotency import IdempotencyStore
from basseparate.api.import_routes import router as import_router
from basseparate.api.job_routes import router as job_router
from basseparate.api.middleware import RequestTracingMiddleware
from basseparate.api.open_routes import OpenSessionStore
from basseparate.api.open_routes import router as open_router
from basseparate.api.playback_routes import router as playback_router
from basseparate.api.portable_routes import router as portable_router
from basseparate.api.result_set_routes import router as result_set_router
from basseparate.api.routes import router
from basseparate.api.security import SecurityMiddleware
from basseparate.config import AppConfig
from basseparate.domain.asset import AssetRecord
from basseparate.domain.export import (
    ALTERNATE_EXPORT_SAMPLE_RATES,
    ExportFormat,
    ExportNormalization,
    export_download_filenames,
)
from basseparate.domain.import_record import TransferState
from basseparate.domain.media_job import JobType, MediaJob
from basseparate.domain.project import (
    MAX_SAMPLE_RATE,
    MIN_SAMPLE_RATE,
    ProjectRecord,
)
from basseparate.domain.separation import StemRecord, ValidationStatus
from basseparate.jobs import JobManager, ParameterResolutionError, build_publishers
from basseparate.media.downmix import MonitorSelectionError, pan_expression, resolve_downmix
from basseparate.runtime_diagnostics import GpuPeakTracker, RuntimeDiagnostics
from basseparate.storage import (
    ExportArtifactRepository,
    ImportRepository,
    JobRepository,
    PortableArtifactRepository,
    ProjectRepository,
    RepresentationRepository,
    SeparationRepository,
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
    """Worker parameters for a waveform pyramid build (M1.8, M2.6 stems).

    The source is the asset named by the job's ``asset_id`` parameter
    (a published stem, M2.6); jobs without the parameter fall back to the
    project's canonical PCM asset. The cache is keyed by the asset's
    content hash under the storage cache category.
    """
    if job.job_type is not JobType.WAVEFORM:
        return {}
    asset_id = job.parameters.get("asset_id")
    if asset_id is not None:
        project = projects.get_project(job.project_id)
        if project is None:
            raise ParameterResolutionError(
                "NO_WAVEFORM_ASSET", f"project {job.project_id} no longer exists"
            )
        asset = projects.get_asset(uuid.UUID(str(asset_id)))
        if asset is None or asset.audio is None:
            raise ParameterResolutionError(
                "NO_WAVEFORM_ASSET", f"the waveform source asset is unavailable: {asset_id}"
            )
    else:
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
    separations: SeparationRepository,
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
    if job.job_type is JobType.EXPORT:
        return _export_parameters_for(job, projects, separations, paths)
    return {}


def _export_parameters_for(
    job: MediaJob,
    projects: ProjectRepository,
    separations: SeparationRepository,
    paths: StoragePaths,
) -> dict[str, Any]:
    """Worker parameters for a WAV stem export (M2.13 §15.1–15.3).

    The machine-readable selection is the job's stored parameters
    (``result_set_id``, optional ``asset_ids``, ``format``,
    ``target_sample_rate``, ``normalize``). Resolution verifies that the
    set belongs to the project, that the selected stems are part of it,
    that their sample rates and frame counts agree (§15.4 common origin),
    and that every source PCM file is present before the worker is
    involved.
    """
    if job.job_type is not JobType.EXPORT:
        return {}
    raw_set_id = job.parameters.get("result_set_id")
    try:
        result_set_id = uuid.UUID(str(raw_set_id))
    except (TypeError, ValueError) as exc:
        raise ParameterResolutionError(
            "EXPORT_RESULT_SET", "the export job has no valid result_set_id"
        ) from exc
    detail = separations.get_result_set_detail(job.project_id, result_set_id)
    if detail is None:
        raise ParameterResolutionError(
            "EXPORT_RESULT_SET",
            f"result set {result_set_id} does not belong to this project",
        )
    result_set, _run, stems = detail
    if result_set.validation_status is not ValidationStatus.VALID:
        raise ParameterResolutionError(
            "EXPORT_RESULT_SET", "only a valid result set can be exported"
        )
    requested = job.parameters.get("asset_ids")
    if isinstance(requested, list) and requested:
        by_asset = {str(stem.audio_asset_id): stem for stem in stems}
        selected: list[StemRecord] = []
        for value in requested:
            stem = by_asset.get(str(value))
            if stem is None:
                raise ParameterResolutionError(
                    "EXPORT_SELECTION",
                    f"asset {value} is not a stem of result set {result_set_id}",
                )
            selected.append(stem)
    else:
        selected = list(stems)
    if not selected:
        raise ParameterResolutionError("NO_STEMS", "the export selection is empty")
    sample_rates = {stem.sample_rate for stem in selected}
    frame_counts = {stem.frame_count for stem in selected}
    if len(sample_rates) != 1 or len(frame_counts) != 1:
        raise ParameterResolutionError(
            "EXPORT_ALIGNMENT",
            "the selected stems do not share one sample rate and frame count; "
            "refusing to export misaligned audio",
        )
    format_raw = job.parameters.get("format", ExportFormat.WAV24.value)
    try:
        export_format = ExportFormat(str(format_raw))
    except ValueError as exc:
        raise ParameterResolutionError(
            "EXPORT_OPTIONS", f"unsupported export format: {format_raw}"
        ) from exc
    target = job.parameters.get("target_sample_rate")
    if target is not None and target not in ALTERNATE_EXPORT_SAMPLE_RATES:
        raise ParameterResolutionError(
            "EXPORT_OPTIONS",
            f"unsupported export sample rate: {target} Hz",
        )
    normalize_raw = job.parameters.get("normalize", ExportNormalization.OFF.value)
    try:
        normalize = ExportNormalization(str(normalize_raw))
    except ValueError as exc:
        raise ParameterResolutionError(
            "EXPORT_OPTIONS", f"unsupported normalization: {normalize_raw}"
        ) from exc
    source_rate = selected[0].sample_rate
    output_rate = target if target is not None else source_rate
    names = export_download_filenames(
        [(stem.id, stem.display_name, stem.role) for stem in selected],
        result_set_id=result_set.id,
        sample_rate=output_rate,
        format=export_format,
    )
    stem_payloads: list[dict[str, Any]] = []
    for stem in selected:
        asset = projects.get_asset(stem.audio_asset_id)
        if asset is None or asset.audio is None:
            raise ParameterResolutionError(
                "EXPORT_STEM_MISSING",
                f"the stem asset for role {stem.role.value} is unavailable",
            )
        audio = asset.audio
        if audio.sample_format != "f32le" or audio.channel_count != stem.channel_count:
            raise ParameterResolutionError(
                "EXPORT_STEM_MISSING",
                f"the stem asset for role {stem.role.value} is not canonical PCM",
            )
        source_path = paths.resolve_asset_path(asset.relative_path)
        if not source_path.is_file():
            raise ParameterResolutionError(
                "EXPORT_STEM_MISSING",
                f"the stem file for role {stem.role.value} is missing from storage",
            )
        stem_payloads.append(
            {
                "stem_id": str(stem.id),
                "asset_id": str(asset.id),
                "role": stem.role.value,
                "display_name": stem.display_name,
                "source_path": str(source_path),
                "source_hash": asset.content_hash,
                "sample_rate": audio.sample_rate,
                "channel_count": audio.channel_count,
                "frame_count": audio.frame_count,
                "download_filename": names[stem.id],
            }
        )
    return {
        "result_set_id": str(result_set.id),
        "format": export_format.value,
        "target_sample_rate": target,
        "normalize": normalize.value,
        "source_sample_rate": source_rate,
        "stems": stem_payloads,
    }


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
        # Portable archives use a second bounded transfer manager with
        # their own, deliberately larger cap (spec §18.1); session
        # metadata lives beside the upload files (no DB rows).
        archive_uploads_dir = paths.runtime / "archive-uploads"
        app.state.archive_uploads = UploadManager(
            uploads_dir=archive_uploads_dir,
            chunk_size=config.import_chunk_bytes,
            max_import_bytes=config.max_project_archive_bytes,
        )
        app.state.open_session_store = OpenSessionStore(archive_uploads_dir)
        app.state.idempotency_store = IdempotencyStore()
        app.state.session_token = session_token
        app.state.job_repository = JobRepository(paths.database_path)
        app.state.separation_repository = SeparationRepository(paths.database_path)
        representation_repository = RepresentationRepository(paths.database_path)
        app.state.representation_repository = representation_repository
        cache_repository = WaveformCacheRepository(paths.database_path, paths.cache)
        app.state.waveform_cache_repository = cache_repository
        export_repository = ExportArtifactRepository(paths.database_path)
        app.state.export_repository = export_repository
        app.state.portable_repository = PortableArtifactRepository(paths.database_path)
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
                export_repository,
            ),
            parameters_for=lambda job: _job_parameters_for(
                job,
                import_repository,
                cast(ProjectRepository, app.state.repository),
                cast(SeparationRepository, app.state.separation_repository),
                paths,
            ),
            worker_memory_limit_mb=config.media_worker_memory_limit_mb,
        )
        gpu_tracker = GpuPeakTracker(
            should_sample=lambda: app.state.job_manager.active_job_id is not None
        )
        app.state.gpu_peak_tracker = gpu_tracker
        app.state.runtime_diagnostics = RuntimeDiagnostics(
            job_manager=app.state.job_manager,
            separation_repository=cast(SeparationRepository, app.state.separation_repository),
            gpu_tracker=gpu_tracker,
        )
        app.state.ready = True
        log.info("basseparate service ready (api v%d)", API_VERSION)

        await app.state.job_manager.start()
        gpu_task = asyncio.create_task(gpu_tracker.run(), name="gpu-peak-sampler")

        yield

        # --- Shutdown ---
        app.state.ready = False
        gpu_tracker.stop()
        gpu_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await gpu_task
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
    app.include_router(asset_router)
    app.include_router(command_router)
    app.include_router(result_set_router)
    app.include_router(export_router)
    app.include_router(portable_router)
    app.include_router(open_router)

    # Static frontend shell, served from the backend origin (M0.8).
    # Mounted after the API router so /api/* routes take precedence.
    static_dir = _static_dir()
    if static_dir is not None:
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
