"""Read-only rhythm grid API for the editor lanes (M3.11/M3.17).

GET /api/v1/projects/{id}/rhythm-grid returns the active branch's tempo
anchors, meter regions, bar origin, pulses, and derived visible grid for
a source-frame range and detail level. It never mutates project state.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, NoReturn, cast

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from basseparate.api.errors import ApiError, ProjectNotFoundError
from basseparate.domain.count_in import CountInPlan
from basseparate.domain.grid import GridDetail, GridResult
from basseparate.domain.metronome import MetronomeSchedule
from basseparate.domain.rhythm import (
    BarOriginState,
    GridValidity,
    MeterRegion,
    RhythmAnalysisRun,
    RhythmBranchRecord,
    RhythmPulse,
    TempoAnchor,
)
from basseparate.domain.rhythm_commands import RhythmCommandRequest, RhythmCommandResult
from basseparate.domain.rhythm_pipeline import RhythmPipelineStage, module_catalog
from basseparate.domain.snapping import SNAP_RADIUS_CSS_PX, SnapMode, SnapResult
from basseparate.models.rhythm_registry import BEAT_THIS_FINAL0_ID
from basseparate.rhythm.commands import (
    RhythmCommandConflict,
    RhythmCommandError,
    RhythmCommandService,
    meter_map_for_branch,
    tempo_map_for_branch,
)
from basseparate.rhythm.count_in import CountInError, build_count_in_plan
from basseparate.rhythm.grid import GridError, derive_grid
from basseparate.rhythm.metronome import MetronomeError, build_metronome_schedule
from basseparate.rhythm.pipeline import (
    RhythmPipelineError,
    RhythmPipelineService,
    RhythmRunRequest,
)
from basseparate.rhythm.snapping import SnapError, snap_to_grid
from basseparate.storage import ProjectRepository, RhythmRepository
from basseparate.storage.repository import StaleRevisionError

router = APIRouter(prefix="/api/v1")


class RhythmGridResponse(BaseModel):
    project_id: uuid.UUID
    revision: int
    branch_id: uuid.UUID
    branch_revision: int
    branch_validity: GridValidity
    source_sample_rate: int
    source_duration_frames: int
    tempo_anchors: list[TempoAnchor]
    meter_regions: list[MeterRegion]
    bar_origin: BarOriginState
    pulses: list[RhythmPulse]
    grid: GridResult


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _rhythm(request: Request) -> RhythmRepository:
    return cast(RhythmRepository, request.app.state.rhythm_repository)


class HistoryRequest(BaseModel):
    base_revision: int


class RhythmResultSummary(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    activation_artifact_id: uuid.UUID
    stage: str
    status: str
    decoder_profile_id: str
    accepted_count: int
    candidate_count: int
    created_at: str


class RhythmBranchSummary(BaseModel):
    id: uuid.UUID
    revision: int
    parent_automatic_result_id: uuid.UUID | None
    grid_validity: str
    pulse_count: int
    tempo_anchor_count: int
    meter_region_count: int
    updated_at: str


class CountInPlanRequest(BaseModel):
    start_frame: int
    playback_rate: float = 1.0


class MetronomeScheduleRequest(BaseModel):
    start_frame: int | None = None
    end_frame: int | None = None


class SnapEventCandidate(BaseModel):
    frame: int
    label: str


class SnapRequest(BaseModel):
    position_frames: int
    mode: SnapMode
    frames_per_pixel: float
    radius_css_px: float = SNAP_RADIUS_CSS_PX
    event_candidates: list[SnapEventCandidate] = []


class RhythmGridUnavailableError(ApiError):
    def __init__(self, project_id: uuid.UUID) -> None:
        super().__init__(
            code="RHYTHM_GRID_UNAVAILABLE",
            message="The project has no complete editable rhythm grid",
            status_code=404,
            details={"project_id": str(project_id)},
        )


@router.get(
    "/projects/{project_id}/rhythm-grid",
    response_model=RhythmGridResponse,
)
async def get_rhythm_grid(
    project_id: uuid.UUID,
    request: Request,
    start_frame: int | None = Query(default=None, ge=0),
    end_frame: int | None = Query(default=None, ge=0),
    detail: Annotated[GridDetail, Query()] = GridDetail.PRIMARY,
) -> RhythmGridResponse:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    if project.sample_rate is None:
        raise RhythmGridUnavailableError(project_id)
    branch_id = project.rhythm_state.active_branch_id
    if branch_id is None:
        raise RhythmGridUnavailableError(project_id)
    branch: RhythmBranchRecord | None = await asyncio.to_thread(
        _rhythm(request).get_branch, branch_id
    )
    if branch is None or branch.project_id != project_id:
        raise RhythmGridUnavailableError(project_id)
    try:
        tempo_map = tempo_map_for_branch(branch, project.sample_rate)
        meter_map = meter_map_for_branch(branch)
    except Exception as exc:  # noqa: BLE001 - incomplete branch is a 404 condition
        raise RhythmGridUnavailableError(project_id) from exc
    start = None
    end = None
    try:
        # The request range is the viewport, not the mapped interval: a
        # real track often starts before the first accepted pulse. Clamp
        # to the map edges instead of failing the whole grid request; the
        # mixer/ruler reports unmapped time separately.
        first_source = tempo_map.anchors[0].source_frame
        last_source = tempo_map.anchors[-1].source_frame
        if start_frame is not None:
            start = (
                tempo_map.musical_start
                if start_frame < first_source
                else tempo_map.musical_end
                if start_frame > last_source
                else tempo_map.map_source_to_musical(start_frame)
            )
        if end_frame is not None:
            end = (
                tempo_map.musical_start
                if end_frame < first_source
                else tempo_map.musical_end
                if end_frame > last_source
                else tempo_map.map_source_to_musical(end_frame)
            )
    except ValueError as exc:
        raise ApiError(
            code="RHYTHM_GRID_RANGE_INVALID",
            message=str(exc),
            status_code=422,
        ) from exc
    try:
        grid = derive_grid(
            tempo_map,
            meter_map,
            branch.bar_origin,
            start=start,
            end=end,
            detail=detail,
        )
    except GridError as exc:
        raise ApiError(
            code="RHYTHM_GRID_RANGE_INVALID",
            message=str(exc),
            status_code=422,
        ) from exc
    low = start_frame if start_frame is not None else 0
    high = end_frame if end_frame is not None else branch.source_duration_frames
    pulses = [pulse for pulse in branch.pulses if low <= pulse.source_frame <= high]
    return RhythmGridResponse(
        project_id=project_id,
        revision=project.revision,
        branch_id=branch.id,
        branch_revision=branch.revision,
        branch_validity=branch.grid_validity,
        source_sample_rate=project.sample_rate,
        source_duration_frames=branch.source_duration_frames,
        tempo_anchors=branch.tempo_anchors,
        meter_regions=branch.meter_regions,
        bar_origin=branch.bar_origin,
        pulses=pulses,
        grid=grid,
    )


@router.post(
    "/projects/{project_id}/rhythm-snap",
    response_model=SnapResult,
)
async def snap_rhythm_position(
    project_id: uuid.UUID,
    body: SnapRequest,
    request: Request,
) -> SnapResult:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    if project.sample_rate is None:
        raise RhythmGridUnavailableError(project_id)
    branch_id = project.rhythm_state.active_branch_id
    if branch_id is None:
        raise RhythmGridUnavailableError(project_id)
    branch: RhythmBranchRecord | None = await asyncio.to_thread(
        _rhythm(request).get_branch, branch_id
    )
    if branch is None or branch.project_id != project_id:
        raise RhythmGridUnavailableError(project_id)
    if body.position_frames > branch.source_duration_frames:
        raise ApiError(
            code="RHYTHM_SNAP_INVALID",
            message="position lies beyond the project duration",
            status_code=422,
        )
    try:
        tempo_map = tempo_map_for_branch(branch, project.sample_rate)
        meter_map = meter_map_for_branch(branch)
        return snap_to_grid(
            body.position_frames,
            mode=body.mode,
            tempo_map=tempo_map,
            meter_map=meter_map,
            bar_origin=branch.bar_origin,
            frames_per_pixel=body.frames_per_pixel,
            radius_css_px=body.radius_css_px,
            event_candidates=[
                (candidate.frame, candidate.label) for candidate in body.event_candidates
            ],
        )
    except (SnapError, ValueError, GridError) as exc:
        raise ApiError(
            code="RHYTHM_SNAP_INVALID",
            message=str(exc),
            status_code=422,
        ) from exc


@router.post(
    "/projects/{project_id}/metronome-schedule",
    response_model=MetronomeSchedule,
)
async def get_metronome_schedule(
    project_id: uuid.UUID,
    body: MetronomeScheduleRequest,
    request: Request,
) -> MetronomeSchedule:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    if project.sample_rate is None:
        raise RhythmGridUnavailableError(project_id)
    branch_id = project.rhythm_state.active_branch_id
    if branch_id is None:
        raise RhythmGridUnavailableError(project_id)
    branch: RhythmBranchRecord | None = await asyncio.to_thread(
        _rhythm(request).get_branch, branch_id
    )
    if branch is None or branch.project_id != project_id:
        raise RhythmGridUnavailableError(project_id)
    try:
        tempo_map = tempo_map_for_branch(branch, project.sample_rate)
        meter_map = meter_map_for_branch(branch)
        start = (
            tempo_map.map_source_to_musical(body.start_frame)
            if body.start_frame is not None
            else None
        )
        end = (
            tempo_map.map_source_to_musical(body.end_frame) if body.end_frame is not None else None
        )
        return build_metronome_schedule(
            tempo_map,
            meter_map,
            branch.bar_origin,
            project.rhythm_state.metronome,
            start=start,
            end=end,
        )
    except (MetronomeError, ValueError, GridError) as exc:
        raise ApiError(
            code="METRONOME_SCHEDULE_INVALID",
            message=str(exc),
            status_code=422,
        ) from exc


@router.post(
    "/projects/{project_id}/count-in-plan",
    response_model=CountInPlan,
)
async def get_count_in_plan(
    project_id: uuid.UUID,
    body: CountInPlanRequest,
    request: Request,
) -> CountInPlan:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    if project.sample_rate is None:
        raise RhythmGridUnavailableError(project_id)
    branch_id = project.rhythm_state.active_branch_id
    if branch_id is None:
        raise RhythmGridUnavailableError(project_id)
    branch: RhythmBranchRecord | None = await asyncio.to_thread(
        _rhythm(request).get_branch, branch_id
    )
    if branch is None or branch.project_id != project_id:
        raise RhythmGridUnavailableError(project_id)
    try:
        return build_count_in_plan(
            tempo_map_for_branch(branch, project.sample_rate),
            meter_map_for_branch(branch),
            project.rhythm_state.count_in,
            target_source_frame=body.start_frame,
            playback_rate=body.playback_rate,
            source_sample_rate=project.sample_rate,
        )
    except (CountInError, ValueError, GridError) as exc:
        raise ApiError(
            code="COUNT_IN_PLAN_INVALID",
            message=str(exc),
            status_code=422,
        ) from exc


def _commands(request: Request) -> RhythmCommandService:
    return cast(RhythmCommandService, request.app.state.rhythm_command_service)


def _raise_rhythm_error(exc: Exception) -> NoReturn:
    if isinstance(exc, StaleRevisionError):
        raise ApiError(
            code="STALE_REVISION",
            message="The project was modified elsewhere; reload it and retry",
            status_code=409,
            details={"current_revision": exc.current_revision},
        ) from exc
    if isinstance(exc, RhythmCommandConflict):
        raise ApiError(
            code="RHYTHM_COMMAND_CONFLICT",
            message=str(exc),
            status_code=409,
            details={"current_revision": exc.current_revision}
            if exc.current_revision is not None
            else {},
        ) from exc
    if isinstance(exc, RhythmCommandError):
        raise ApiError(
            code="RHYTHM_COMMAND_INVALID",
            message=str(exc),
            status_code=422,
        ) from exc
    raise exc


@router.post(
    "/projects/{project_id}/rhythm-commands",
    response_model=RhythmCommandResult,
)
async def apply_rhythm_command(
    project_id: uuid.UUID, body: RhythmCommandRequest, request: Request
) -> RhythmCommandResult:
    try:
        return await asyncio.to_thread(_commands(request).apply, project_id, body)
    except Exception as exc:  # noqa: BLE001 - mapped to a typed API error
        _raise_rhythm_error(exc)


@router.post(
    "/projects/{project_id}/rhythm-undo",
    response_model=RhythmCommandResult,
)
async def undo_rhythm_command(
    project_id: uuid.UUID, body: HistoryRequest, request: Request
) -> RhythmCommandResult:
    try:
        return await asyncio.to_thread(_commands(request).undo, project_id, body.base_revision)
    except Exception as exc:  # noqa: BLE001
        _raise_rhythm_error(exc)


@router.post(
    "/projects/{project_id}/rhythm-redo",
    response_model=RhythmCommandResult,
)
async def redo_rhythm_command(
    project_id: uuid.UUID, body: HistoryRequest, request: Request
) -> RhythmCommandResult:
    try:
        return await asyncio.to_thread(_commands(request).redo, project_id, body.base_revision)
    except Exception as exc:  # noqa: BLE001
        _raise_rhythm_error(exc)


@router.get(
    "/projects/{project_id}/rhythm-results",
    response_model=list[RhythmResultSummary],
)
async def list_rhythm_results(project_id: uuid.UUID, request: Request) -> list[RhythmResultSummary]:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    results = await asyncio.to_thread(_rhythm(request).list_results_for_project, project_id)
    return [
        RhythmResultSummary(
            id=result.id,
            run_id=result.run_id,
            activation_artifact_id=result.activation_artifact_id,
            stage=result.stage.value,
            status=result.status.value,
            decoder_profile_id=result.decoder_profile.profile_id,
            accepted_count=len(result.accepted_pulses),
            candidate_count=len(result.candidate_pulses),
            created_at=result.created_at.isoformat().replace("+00:00", "Z"),
        )
        for result in results
    ]


@router.get(
    "/projects/{project_id}/rhythm-results/{result_id}",
    response_model=RhythmResultSummary,
)
async def get_rhythm_result(
    project_id: uuid.UUID, result_id: uuid.UUID, request: Request
) -> RhythmResultSummary:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    result = await asyncio.to_thread(_rhythm(request).get_result, result_id)
    if result is None or result.project_id != project_id:
        raise ApiError(
            code="RHYTHM_RESULT_NOT_FOUND",
            message="The requested rhythm result does not exist",
            status_code=404,
        )
    return RhythmResultSummary(
        id=result.id,
        run_id=result.run_id,
        activation_artifact_id=result.activation_artifact_id,
        stage=result.stage.value,
        status=result.status.value,
        decoder_profile_id=result.decoder_profile.profile_id,
        accepted_count=len(result.accepted_pulses),
        candidate_count=len(result.candidate_pulses),
        created_at=result.created_at.isoformat().replace("+00:00", "Z"),
    )


@router.get(
    "/projects/{project_id}/rhythm-branches",
    response_model=list[RhythmBranchSummary],
)
async def list_rhythm_branches(
    project_id: uuid.UUID, request: Request
) -> list[RhythmBranchSummary]:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    branches = await asyncio.to_thread(_rhythm(request).list_branches_for_project, project_id)
    return [
        RhythmBranchSummary(
            id=branch.id,
            revision=branch.revision,
            parent_automatic_result_id=branch.parent_automatic_result_id,
            grid_validity=branch.grid_validity.value,
            pulse_count=len(branch.pulses),
            tempo_anchor_count=len(branch.tempo_anchors),
            meter_region_count=len(branch.meter_regions),
            updated_at=branch.updated_at.isoformat().replace("+00:00", "Z"),
        )
        for branch in branches
    ]


@router.get(
    "/projects/{project_id}/rhythm-branches/{branch_id}",
    response_model=RhythmBranchRecord,
)
async def get_rhythm_branch(
    project_id: uuid.UUID, branch_id: uuid.UUID, request: Request
) -> RhythmBranchRecord:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    branch = await asyncio.to_thread(_rhythm(request).get_branch, branch_id)
    if branch is None or branch.project_id != project_id:
        raise ApiError(
            code="RHYTHM_BRANCH_NOT_FOUND",
            message="The requested rhythm branch does not exist",
            status_code=404,
        )
    return branch


@router.get("/rhythm-activations/{artifact_id}")
async def get_rhythm_activation_range(
    artifact_id: uuid.UUID,
    request: Request,
    kind: Annotated[str, Query(pattern="^(beat|downbeat)$")] = "beat",
    start_frame: Annotated[int, Query(ge=0)] = 0,
    count: Annotated[int, Query(gt=0, le=4096)] = 128,
) -> Response:
    import numpy as np

    from basseparate.rhythm.activations import RhythmActivationStore
    from basseparate.storage.paths import resolve_storage_paths

    paths = resolve_storage_paths(request.app.state.storage_paths.root)
    artifact = await asyncio.to_thread(_rhythm(request).get_artifact, artifact_id)
    if artifact is None:
        raise ApiError(
            code="RHYTHM_ACTIVATION_NOT_FOUND",
            message="The requested activation artifact does not exist",
            status_code=404,
        )
    store = RhythmActivationStore(paths.data / "rhythm")
    directory = store.artifact_dir(artifact_id)
    filename = "beat.npy" if kind == "beat" else "downbeat.npy"
    path = directory / filename
    if not path.is_file():
        raise ApiError(
            code="RHYTHM_ACTIVATION_MISSING",
            message="The activation array is missing",
            status_code=404,
        )
    try:
        array = np.load(path, mmap_mode="r", allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise ApiError(
            code="RHYTHM_ACTIVATION_INVALID",
            message=str(exc),
            status_code=422,
        ) from exc
    start = min(start_frame, int(array.size))
    stop = min(int(array.size), start + count)
    chunk = np.asarray(array[start:stop], dtype="<f4")
    return Response(
        content=chunk.tobytes(),
        media_type="application/octet-stream",
        headers={
            "X-Activation-Kind": kind,
            "X-Start-Frame": str(start),
            "X-Frame-Count": str(max(0, stop - start)),
            "X-Total-Frames": str(int(array.size)),
            "X-Content-Hash": artifact.content_hash,
            "X-Frame-Rate": "50",
        },
    )


@router.get("/rhythm-modules", response_model=list[RhythmPipelineStage])
async def list_rhythm_modules() -> list[RhythmPipelineStage]:
    return module_catalog()


# ---------------------------------------------------------------------------
# Analyze Rhythm runs (M3.17 §19.2-§19.3)
# ---------------------------------------------------------------------------


class RhythmRunRequestBody(BaseModel):
    model_id: str | None = None
    device: str | None = None
    force_rerun: bool | None = None
    threads: int | None = None


class RhythmRunSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    input_asset_id: uuid.UUID
    input_hash: str
    model_manifest_id: str
    model_preset: str
    requested_device: str
    actual_device: str | None
    activation_artifact_id: uuid.UUID | None
    decoded_result_id: uuid.UUID | None
    started_at: str | None
    ended_at: str | None
    warnings: list[str]


def _run_summary(run: RhythmAnalysisRun) -> RhythmRunSummary:
    return RhythmRunSummary(
        id=run.id,
        project_id=run.project_id,
        status=run.status.value,
        input_asset_id=run.input_asset_id,
        input_hash=run.input_hash,
        model_manifest_id=run.model_manifest_id,
        model_preset=run.model_preset.value,
        requested_device=run.requested_device.value,
        actual_device=(
            run.actual_device.value if run.actual_device is not None else None
        ),
        activation_artifact_id=run.activation_artifact_id,
        decoded_result_id=run.decoded_result_id,
        started_at=(
            run.started_at.isoformat().replace("+00:00", "Z")
            if run.started_at is not None
            else None
        ),
        ended_at=(
            run.ended_at.isoformat().replace("+00:00", "Z")
            if run.ended_at is not None
            else None
        ),
        warnings=list(run.warnings),
    )


def _pipeline(request: Request) -> RhythmPipelineService:
    existing = getattr(request.app.state, "rhythm_pipeline", None)
    if existing is not None:
        return cast(RhythmPipelineService, existing)
    paths = request.app.state.storage_paths
    service = RhythmPipelineService(
        paths=paths,
        projects=_projects(request),
        rhythm=_rhythm(request),
    )
    request.app.state.rhythm_pipeline = service
    return service


@router.post(
    "/projects/{project_id}/rhythm-runs",
    response_model=RhythmRunSummary,
    status_code=202,
)
async def start_rhythm_run(
    project_id: uuid.UUID,
    body: RhythmRunRequestBody,
    request: Request,
) -> RhythmRunSummary:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    service = _pipeline(request)
    try:
        run = await asyncio.to_thread(
            service.start,
            project_id,
            RhythmRunRequest(
                model_id=body.model_id or BEAT_THIS_FINAL0_ID,
                device=body.device or "cpu",
                force_rerun=bool(body.force_rerun),
                threads=body.threads or 4,
            ),
        )
    except RhythmPipelineError as exc:
        status_code = 404 if exc.code == "PROJECT_NOT_FOUND" else 409
        raise ApiError(
            code=exc.code,
            message=exc.message,
            status_code=status_code,
        ) from exc
    return _run_summary(run)


@router.get(
    "/projects/{project_id}/rhythm-runs",
    response_model=list[RhythmRunSummary],
)
async def list_rhythm_runs(
    project_id: uuid.UUID,
    request: Request,
) -> list[RhythmRunSummary]:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    runs = await asyncio.to_thread(_rhythm(request).list_runs_for_project, project_id)
    return [_run_summary(run) for run in runs]


@router.get(
    "/projects/{project_id}/rhythm-runs/{run_id}",
    response_model=RhythmRunSummary,
)
async def get_rhythm_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    request: Request,
) -> RhythmRunSummary:
    project = await asyncio.to_thread(_projects(request).get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    run = await asyncio.to_thread(_rhythm(request).get_run, run_id)
    if run is None or run.project_id != project_id:
        raise ApiError(
            code="RHYTHM_RUN_NOT_FOUND",
            message="The rhythm run does not exist",
            status_code=404,
        )
    return _run_summary(run)
