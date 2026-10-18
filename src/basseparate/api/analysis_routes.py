"""Analysis, model, and separation-run interfaces (M2.17, spec §19).

Routes (all authenticated, loopback-only):

- POST /api/v1/projects/{id}/runs — request a separation. The route
  resolves the reference mix, the device, and the §9.1 cache key; it
  coalesces a live identical run, serves a valid cached result, or
  creates a queued run + separation job. Long work returns a job id.
- GET  /api/v1/projects/{id}/separation-results — the immutable result
  sets (spec name; the existing /result-sets path stays as an alias).
- GET  /api/v1/hardware — discovered devices merged with the M2.2
  qualification store and the default selection.
- GET  /api/v1/models — registry manifests, bundle presence, recorded
  verification, and qualification state.
- POST /api/v1/models/{id}/verify — hash the bundled artifacts against
  the registry (local only; no download), record and return the report.

No PyTorch import: the app environment only reads driver/qualification
facts, and separation execution happens in the analysis worker.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field

from basseparate.api.errors import ApiError, ProjectNotFoundError
from basseparate.api.result_set_routes import ResultSetSummary, list_result_sets
from basseparate.devices import (
    DeviceError,
    NvidiaSmiError,
    QualificationStore,
    build_device_records,
    discover_gpus,
    select_device,
)
from basseparate.domain.device import DeviceKind, DeviceRecord
from basseparate.domain.media_job import JobType
from basseparate.domain.project import ProjectStatus
from basseparate.domain.separation import (
    SeparationMode,
    SeparationRun,
    SeparationRunStatus,
)
from basseparate.jobs import JobManager
from basseparate.media.separation_cache import lookup_cached_result
from basseparate.media.separation_request import (
    SEPARATION_ADAPTER_VERSION,
    SEPARATION_DEFAULT_SEED,
    SEPARATION_ENGINE_VERSION,
    SeparationRequestError,
    device_profile,
    model_manifest,
    model_manifest_hash,
    model_manifest_id,
    reference_mix_plan,
    request_cache_key,
    requested_parameters,
)
from basseparate.models import (
    REGISTRY,
    BundleError,
    ProvenanceRecord,
    ProvenanceStore,
    VerificationRecord,
    VerificationStore,
    default_bundle_dir,
    verify_bundle,
)
from basseparate.storage import ProjectRepository, SeparationRepository
from basseparate.storage.paths import StoragePaths

router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _projects(request: Request) -> ProjectRepository:
    return cast(ProjectRepository, request.app.state.repository)


def _separations(request: Request) -> SeparationRepository:
    return cast(SeparationRepository, request.app.state.separation_repository)


def _manager(request: Request) -> JobManager:
    return cast(JobManager, request.app.state.job_manager)


def _paths(request: Request) -> StoragePaths:
    return cast(StoragePaths, request.app.state.storage_paths)


def _analysis_state(paths: StoragePaths) -> Path:
    return paths.state / "analysis"


def _device_records(paths: StoragePaths) -> list[DeviceRecord]:
    """Discovered GPUs merged with the persisted qualification state.

    No GPU/driver is a normal state (empty list); a corrupt qualification
    store degrades to untested devices rather than failing the route.
    """
    try:
        gpus = discover_gpus()
    except NvidiaSmiError:
        gpus = []
    store = QualificationStore(_analysis_state(paths) / "devices.json")
    try:
        entries = store.load()
    except DeviceError:
        entries = {}
    return build_device_records(gpus, entries)


def _select_run_device(
    records: list[DeviceRecord], requested: str | None
) -> DeviceRecord:
    """Resolve the run's device (spec §4.5).

    ``None``/``"auto"`` uses the default selection (first qualified GPU);
    ``"cpu"`` is always allowed explicitly (§4.3.4); a GPU identifier must
    be present and qualified — never silently substituted.
    """
    if requested is None or requested == "auto":
        selection = select_device(records)
        if selection.device is None:
            raise ApiError(
                code="NO_QUALIFIED_DEVICE",
                message="No qualified analysis device is available; select the CPU "
                "explicitly to run on the CPU",
                status_code=status.HTTP_409_CONFLICT,
                details={
                    "reason": selection.reason,
                    "cpu_offered": selection.cpu_offered,
                },
            )
        return selection.device
    if requested == "cpu":
        cpu = next(
            (record for record in records if record.kind is DeviceKind.CPU), None
        )
        if cpu is None:  # pragma: no cover - build_device_records always appends CPU
            raise ApiError(
                code="DEVICE_UNAVAILABLE",
                message="The CPU device is not available",
                status_code=status.HTTP_409_CONFLICT,
            )
        return cpu
    record = next((item for item in records if item.identifier == requested), None)
    if record is None:
        raise ApiError(
            code="DEVICE_UNAVAILABLE",
            message="The selected device is no longer present",
            status_code=status.HTTP_409_CONFLICT,
            details={"device": requested},
        )
    if not record.is_usable:
        raise ApiError(
            code="DEVICE_UNAVAILABLE",
            message="The selected device is not qualified for analysis",
            status_code=status.HTTP_409_CONFLICT,
            details={
                "device": requested,
                "reason": record.unavailability_reason,
            },
        )
    return record


def _verification_records(paths: StoragePaths) -> dict[str, VerificationRecord]:
    try:
        return VerificationStore(_analysis_state(paths) / "models.json").load()
    except BundleError:
        return {}


def _provenance_records(paths: StoragePaths) -> dict[str, ProvenanceRecord]:
    try:
        return ProvenanceStore(_analysis_state(paths) / "provenance.json").load()
    except BundleError:
        return {}


def _bundle_state(model_id: str) -> str:
    """Cheap presence/size check (hashing only happens on verify)."""
    manifest = REGISTRY[model_id]
    directory = default_bundle_dir(manifest)
    if not directory.is_dir():
        return "missing"
    for spec in manifest.artifacts:
        path = directory / spec.name
        if not path.is_file():
            return "missing"
        if path.stat().st_size != spec.size_bytes:
            return "corrupt"
    return "available"


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class CreateRunRequest(BaseModel):
    mode: Literal["four_stems", "bass_pair"] = "four_stems"
    #: None/"auto" = default selection, "cpu" = explicit CPU, otherwise a
    #: GPU identifier (driver UUID).
    device: str | None = Field(default=None, max_length=128)
    seed: int = Field(default=SEPARATION_DEFAULT_SEED, ge=0)


class CreateRunResponse(BaseModel):
    run_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    result_set_id: uuid.UUID | None = None
    cached: bool = False
    coalesced: bool = False
    device: str | None = None


class HardwareResponse(BaseModel):
    devices: list[DeviceRecord]
    selected: DeviceRecord | None = None
    cpu_offered: bool = False
    reason: str | None = None


class ModelVerificationInfo(BaseModel):
    state: str
    verified_at: str
    missing: list[str] = Field(default_factory=list)
    corrupt: list[str] = Field(default_factory=list)


class ModelStatus(BaseModel):
    model_id: str
    display_name: str
    input_sample_rate: int
    input_channels: int
    output_labels: list[str]
    bundle_dir: str
    bundle_state: str
    qualification_status: str
    qualification_detail: str | None = None
    license_notice: str
    last_verification: ModelVerificationInfo | None = None


class ModelListResponse(BaseModel):
    models: list[ModelStatus]


class ModelVerifyResponse(ModelVerificationInfo):
    model_id: str


# ---------------------------------------------------------------------------
# Separation runs
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/runs",
    response_model=CreateRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_separation_run(
    project_id: uuid.UUID,
    body: CreateRunRequest,
    request: Request,
    response: Response,
) -> CreateRunResponse:
    """Request a separation run (spec §3.2, §9.2).

    A live identical run is coalesced; a valid cached result is returned
    without a job; otherwise the run + job are created. Preparation and
    inference happen in the analysis worker.
    """
    projects = _projects(request)
    project = await asyncio.to_thread(projects.get_project, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))
    if project.status is not ProjectStatus.READY:
        raise ApiError(
            code="PROJECT_NOT_READY",
            message="The project must have canonical audio before separation",
            status_code=status.HTTP_409_CONFLICT,
        )

    canonical = (
        await asyncio.to_thread(projects.get_asset, project.canonical_asset_id)
        if project.canonical_asset_id
        else None
    )
    monitoring = (
        await asyncio.to_thread(projects.get_asset, project.monitoring_asset_id)
        if project.monitoring_asset_id
        else None
    )
    try:
        plan = reference_mix_plan(project, canonical, monitoring)
    except SeparationRequestError as exc:
        raise ApiError(
            code="REFERENCE_MIX_UNAVAILABLE",
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        ) from exc

    paths = _paths(request)
    records = await asyncio.to_thread(_device_records, paths)
    device = _select_run_device(records, body.device)
    device_type, gpu_uuid = device_profile(device)
    mode = SeparationMode(body.mode)
    manifest = model_manifest()
    parameters = requested_parameters()
    cache_key, transform_hash = request_cache_key(
        project=project,
        plan=plan,
        manifest=manifest,
        mode=mode,
        seed=body.seed,
        device_type=device_type,
        parameters=parameters,
    )

    separations = _separations(request)
    manager = _manager(request)

    active = await asyncio.to_thread(
        separations.find_active_run, project.id, cache_key
    )
    if active is not None:
        project_jobs = await manager.list_project_jobs(project.id)
        active_job = next(
            (
                job
                for job in project_jobs
                if job.job_type is JobType.SEPARATION
                and job.parameters.get("run_id") == str(active.id)
            ),
            None,
        )
        if active_job is not None and not active_job.is_terminal:
            response.status_code = status.HTTP_200_OK
            return CreateRunResponse(
                run_id=active.id,
                job_id=active_job.id,
                coalesced=True,
                device=device.identifier,
            )
        # A live row without a live job must not block future requests.
        await asyncio.to_thread(
            separations.fail_run,
            active.id,
            "STALE_RUN",
            "the run has no live job",
        )

    cached = await asyncio.to_thread(
        lookup_cached_result,
        project_id=project.id,
        cache_key=cache_key,
        storage_root=paths.data.parent,
        separation_repository=separations,
        asset_repository=projects,
    )
    if cached is not None:
        response.status_code = status.HTTP_200_OK
        return CreateRunResponse(
            result_set_id=cached.id,
            cached=True,
            device=device.identifier,
        )

    run = SeparationRun(
        id=uuid.uuid4(),
        project_id=project.id,
        input_asset_id=plan.asset_id,
        input_transform_hash=transform_hash,
        requested_mode=mode,
        model_manifest_id=model_manifest_id(manifest),
        model_manifest_hash=model_manifest_hash(manifest),
        engine_version=SEPARATION_ENGINE_VERSION,
        adapter_version=SEPARATION_ADAPTER_VERSION,
        requested_parameters=parameters,
        random_seed=body.seed,
        device_type=device_type,
        gpu_uuid=gpu_uuid,
        status=SeparationRunStatus.QUEUED,
        cache_key=cache_key,
    )
    await asyncio.to_thread(separations.create_run, run)
    try:
        job = await manager.create_job(
            project.id,
            JobType.SEPARATION,
            parameters={
                "run_id": str(run.id),
                "requested_mode": mode.value,
                "device": device.identifier,
            },
        )
    except Exception as exc:  # noqa: BLE001 - never leave a live run without a job
        await asyncio.to_thread(
            separations.fail_run, run.id, "SCHEDULING_FAILED", str(exc)
        )
        raise ApiError(
            code="RUN_SCHEDULING_FAILED",
            message="The separation job could not be scheduled",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"reason": str(exc)[:500]},
        ) from exc
    return CreateRunResponse(
        run_id=run.id,
        job_id=job.id,
        device=device.identifier,
    )


@router.get(
    "/projects/{project_id}/separation-results",
    response_model=list[ResultSetSummary],
)
async def list_separation_results(
    project_id: uuid.UUID, request: Request
) -> list[ResultSetSummary]:
    """Immutable result sets for the project (spec §19.1 name)."""
    return await list_result_sets(project_id, request)


# ---------------------------------------------------------------------------
# Hardware and models
# ---------------------------------------------------------------------------


@router.get("/hardware", response_model=HardwareResponse)
def get_hardware(request: Request) -> HardwareResponse:
    """Device qualification and availability (spec §4.4, §19.1)."""
    records = _device_records(_paths(request))
    selection = select_device(records)
    return HardwareResponse(
        devices=records,
        selected=selection.device,
        cpu_offered=selection.cpu_offered,
        reason=selection.reason,
    )


@router.get("/models", response_model=ModelListResponse)
def list_models(request: Request) -> ModelListResponse:
    """Registered bundled models with presence/verification state (§19.1)."""
    paths = _paths(request)
    verifications = _verification_records(paths)
    provenance = _provenance_records(paths)
    models: list[ModelStatus] = []
    for model_id in sorted(REGISTRY):
        manifest = REGISTRY[model_id]
        verification = verifications.get(model_id)
        record = provenance.get(model_id)
        models.append(
            ModelStatus(
                model_id=manifest.model_id,
                display_name=manifest.display_name,
                input_sample_rate=manifest.input_sample_rate,
                input_channels=manifest.input_channels,
                output_labels=list(manifest.output_labels),
                bundle_dir=str(default_bundle_dir(manifest)),
                bundle_state=_bundle_state(model_id),
                qualification_status=(
                    record.qualification_status if record else "not-qualified"
                ),
                qualification_detail=record.qualification_detail if record else None,
                license_notice=manifest.license_notice,
                last_verification=(
                    ModelVerificationInfo(
                        state=verification.state,
                        verified_at=verification.verified_at,
                        missing=list(verification.missing),
                        corrupt=list(verification.corrupt),
                    )
                    if verification is not None
                    else None
                ),
            )
        )
    return ModelListResponse(models=models)


@router.post("/models/{model_id}/verify", response_model=ModelVerifyResponse)
def verify_model(model_id: str, request: Request) -> ModelVerifyResponse:
    """Verify one bundled model by size and SHA-256 (spec §19.1).

    Local hashing only: no network, no inference. The result is recorded
    for ``GET /models``.
    """
    manifest = REGISTRY.get(model_id)
    if manifest is None:
        raise ApiError(
            code="MODEL_NOT_FOUND",
            message=f"Unknown model: {model_id}",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"model_id": model_id},
        )
    report = verify_bundle(default_bundle_dir(manifest), manifest)
    record = VerificationStore(_analysis_state(_paths(request)) / "models.json").record(
        report
    )
    return ModelVerifyResponse(
        model_id=manifest.model_id,
        state=report.state,
        verified_at=record.verified_at,
        missing=list(report.missing),
        corrupt=list(report.corrupt),
    )
