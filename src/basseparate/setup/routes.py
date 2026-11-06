"""HTTP surface for the first-run setup wizard."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from basseparate.config import RuntimePaths
from basseparate.jobs import JobContext, JobManager
from basseparate.model_registry import ModelRegistryError, load_registry
from basseparate.setup.environments import ENV_VARIANTS
from basseparate.setup.errors import SetupError
from basseparate.setup.service import SetupService


class SetupToolsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept_licenses: bool = False
    accept_licences: bool = False
    accept_license: bool = False
    accept_license_terms: bool = False
    consent: bool = False
    force: bool = False
    tools: list[str] = Field(default_factory=list)

    @property
    def consented(self) -> bool:
        return (
            self.accept_licenses
            or self.accept_licences
            or self.accept_license
            or self.accept_license_terms
            or self.consent
        )


class SetupEnvironmentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant: Literal["cpu", "cuda"] | None = None
    variants: list[Literal["cpu", "cuda"]] = Field(default_factory=list)
    accept_licenses: bool = False
    accept_licences: bool = False
    accept_license: bool = False
    accept_license_terms: bool = False
    consent: bool = False
    offline: bool = False

    @property
    def consented(self) -> bool:
        return (
            self.accept_licenses
            or self.accept_licences
            or self.accept_license
            or self.accept_license_terms
            or self.consent
        )


class SetupModelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str | None = None
    model_ids: list[str] = Field(default_factory=list)
    accept_licenses: bool = False
    accept_licences: bool = False
    accept_license: bool = False
    accept_license_terms: bool = False
    consent: bool = False
    force: bool = False
    accepted_model_ids: list[str] = Field(default_factory=list)
    model_consents: dict[str, bool] = Field(default_factory=dict)

    @property
    def consented(self) -> bool:
        return (
            self.accept_licenses
            or self.accept_licences
            or self.accept_license
            or self.accept_license_terms
            or self.consent
        )

    def accepted_ids(self) -> set[str]:
        accepted = {model_id for model_id in self.accepted_model_ids if model_id}
        accepted.update(model_id for model_id, value in self.model_consents.items() if value)
        return accepted


class SetupSkipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skip: bool = True


def _submit(jobs: JobManager, kind: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        job = jobs.submit(kind, params)
    except KeyError as error:
        raise HTTPException(status_code=500, detail="setup jobs are not installed") from error
    return job.to_dict()


def install(app: Any) -> None:
    """Register setup state, routes and job kinds on this app instance."""
    if getattr(app.state, "setup_installed", False):
        return
    service = getattr(app.state, "setup", None)
    if not isinstance(service, SetupService):
        runtime: RuntimePaths = app.state.settings.runtime_paths()
        service = SetupService(runtime)
        app.state.setup = service
    jobs: JobManager = app.state.jobs
    service.register(jobs)

    def guarded_environments(context: JobContext, params: Mapping[str, Any]) -> object:
        if not params.get("accept_licenses"):
            raise SetupError("licence acceptance is required before installing environments")
        return service.install_environments_job(context, params)

    def guarded_models(context: JobContext, params: Mapping[str, Any]) -> object:
        if not params.get("accept_licenses"):
            raise SetupError("licence acceptance is required before installing models")
        requested = params.get("model_ids") or []
        accepted = set(params.get("accepted_model_ids") or [])
        unaccepted = [model_id for model_id in requested if model_id not in accepted]
        if unaccepted:
            raise SetupError(
                "licence acceptance is required for each requested model: " + ", ".join(unaccepted)
            )
        return service.install_models_job(context, params)

    jobs.register("setup_environments", guarded_environments)
    jobs.register("setup_models", guarded_models)
    router = APIRouter(tags=["setup"])

    @router.get("/setup/status")
    def setup_status() -> dict[str, Any]:
        return service.status()

    @router.post("/setup/skip")
    def setup_skip(body: SetupSkipRequest) -> dict[str, Any]:
        return service.skip(body.skip)

    @router.post("/setup/tools", status_code=status.HTTP_202_ACCEPTED)
    def setup_tools(body: SetupToolsRequest) -> dict[str, Any]:
        if not body.consented:
            raise HTTPException(
                status_code=400,
                detail="licence acceptance is required before installing tools",
            )
        return _submit(
            jobs,
            "setup_tools",
            {"accept_licenses": True, "force": body.force},
        )

    @router.post("/setup/environments", status_code=status.HTTP_202_ACCEPTED)
    def setup_environments(body: SetupEnvironmentsRequest) -> dict[str, Any]:
        if not body.consented:
            raise HTTPException(
                status_code=400,
                detail="licence acceptance is required before installing environments",
            )
        variants = list(body.variants)
        if body.variant is not None:
            variants = [body.variant]
        if not variants:
            variants = list(ENV_VARIANTS)
        return _submit(
            jobs,
            "setup_environments",
            {
                "variants": variants,
                "accept_licenses": True,
                "offline": body.offline,
            },
        )

    @router.post("/setup/models", status_code=status.HTTP_202_ACCEPTED)
    def setup_models(body: SetupModelsRequest) -> dict[str, Any]:
        if not body.consented:
            raise HTTPException(
                status_code=400,
                detail="licence acceptance is required before installing models",
            )
        try:
            registry = load_registry(service.runtime.registry_path)
        except ModelRegistryError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        requested = list(body.model_ids)
        if body.model_id:
            requested = [body.model_id, *requested]
        if not requested:
            requested = [entry.id for entry in registry.models]
        accepted = body.accepted_ids()
        missing_consent = [model_id for model_id in requested if model_id not in accepted]
        if missing_consent:
            raise HTTPException(
                status_code=400,
                detail=(
                    "licence acceptance is required for each requested model: "
                    + ", ".join(missing_consent)
                ),
            )
        try:
            for model_id in requested:
                registry.get(model_id)
        except ModelRegistryError as error:
            raise HTTPException(
                status_code=400,
                detail=f"{error}; install models from the setup screen",
            ) from error
        return _submit(
            jobs,
            "setup_models",
            {
                "model_ids": requested,
                "accepted_model_ids": sorted(accepted),
                "accept_licenses": True,
                "force": body.force,
            },
        )

    app.include_router(router, prefix="/api")
    app.state.setup_installed = True
