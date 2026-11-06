"""First-run setup service and job runners."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from basseparate.config import RuntimePaths, runtime_paths
from basseparate.jobs import JobCancelled, JobContext, JobManager
from basseparate.model_registry import ModelRegistryError, load_registry, verify_registry
from basseparate.setup.checks import system_checks
from basseparate.setup.download import Fetch
from basseparate.setup.environments import (
    ENV_VARIANTS,
    RunUv,
    create_environment,
    environments_status,
)
from basseparate.setup.errors import SetupCancelled, SetupError
from basseparate.setup.models import install_models
from basseparate.setup.state import SetupStateStore
from basseparate.setup.tools import ToolInstaller, install_tools, tools_status

Progress = Callable[[float, str], None]


class SetupService:
    def __init__(
        self,
        runtime: RuntimePaths | None = None,
        *,
        state: SetupStateStore | None = None,
        fetch: Fetch | None = None,
        run_uv: RunUv | None = None,
        tool_installer: ToolInstaller | None = None,
        disk_probe: Callable[[Any], object] | None = None,
        which: Callable[[str], str | None] | None = None,
    ) -> None:
        self.runtime = runtime or runtime_paths()
        self.state = state or SetupStateStore(self.runtime)
        self.fetch = fetch
        self.run_uv = run_uv
        self.tool_installer = tool_installer
        self.disk_probe = disk_probe
        self.which = which

    def status(self) -> dict[str, Any]:
        checks = system_checks(
            self.runtime,
            disk_probe=self.disk_probe,
            which=self.which,
        )
        tools = tools_status(self.runtime)
        environments = environments_status(self.runtime)
        registry_error: str | None = None
        models: list[dict[str, Any]] = []
        try:
            registry = load_registry(self.runtime.registry_path)
            states = verify_registry(
                registry,
                self.runtime.models_root,
                app_root=self.runtime.app_root,
            )
            models = [state.to_dict() for state in states]
        except ModelRegistryError as error:
            registry_error = str(error)
        state = self.state.load()
        skipped = state.get("skipped") is True
        checks_ok = all(bool(check.get("ok")) for check in checks.values())
        env_ready = any(bool(item.get("installed")) for item in environments.values())
        model_ready = any(item.get("status") == "installed" for item in models)
        tools_ready = all(bool(item.get("installed")) for item in tools.values())
        ready = checks_ok and env_ready and model_ready and not skipped
        return {
            "mode": self.runtime.mode,
            "ready": ready,
            "skipped": skipped,
            "skip": skipped,
            "requires_model_choice": not model_ready,
            "roots": {
                "app_root": str(self.runtime.app_root),
                "data_root": str(self.runtime.data_root),
                "web_dir": str(self.runtime.web_dir),
                "analysis_dir": str(self.runtime.analysis_dir),
                "models_root": str(self.runtime.models_root),
                "tools_root": str(self.runtime.tools_root),
                "environments_root": str(self.runtime.environments_root),
                "uv": str(self.runtime.uv),
            },
            "checks": checks,
            "tools": tools,
            "environments": environments,
            "models": models,
            "registry_error": registry_error,
            "readiness": {
                "ready": ready,
                "checks_ok": checks_ok,
                "tools_ready": tools_ready,
                "environment_ready": env_ready,
                "model_ready": model_ready,
                "requires_model_choice": not model_ready,
            },
            "setup_complete": bool(
                state.get("models_completed") and state.get("environments_completed")
            ),
            "state": state,
        }

    def skip(self, skipped: bool) -> dict[str, Any]:
        self.state.skip(skipped)
        return self.status()

    def _job_progress(self, context: JobContext) -> Progress:
        def report(fraction: float, message: str = "") -> None:
            context.check_cancelled()
            context.progress(fraction, message)

        return report

    def install_tools_job(self, context: JobContext, params: Mapping[str, Any]) -> object:
        if not params.get("accept_licenses"):
            raise SetupError("licence acceptance is required before installing tools")
        try:
            result = install_tools(
                self.runtime,
                progress=self._job_progress(context),
                cancel=lambda: context.cancelled,
                installer=self.tool_installer,
            )
        except SetupCancelled as error:
            raise JobCancelled(context.job_id) from error
        self.state.record("tools", installed=result)
        return {"tools": result}

    def install_environments_job(self, context: JobContext, params: Mapping[str, Any]) -> object:
        variants = params.get("variants") or list(ENV_VARIANTS)
        results: dict[str, object] = {}
        count = len(variants)
        try:
            for index, variant in enumerate(variants):
                context.check_cancelled()

                def report_environment(
                    fraction: float,
                    message: str,
                    *,
                    base: int = index,
                ) -> None:
                    self._job_progress(context)((base + fraction) / count, message)

                results[variant] = create_environment(
                    variant,
                    runtime=self.runtime,
                    run_uv=self.run_uv,
                    progress=report_environment,
                    cancel=lambda: context.cancelled,
                )
        except SetupCancelled as error:
            raise JobCancelled(context.job_id) from error
        self.state.record("environments", installed=results)
        return {"environments": results}

    def install_models_job(self, context: JobContext, params: Mapping[str, Any]) -> object:
        if not params.get("accept_licenses"):
            raise SetupError("licence acceptance is required before installing models")
        model_ids = params.get("model_ids") or []
        try:
            states = install_models(
                model_ids,
                runtime=self.runtime,
                fetch=self.fetch,
                progress=self._job_progress(context),
                cancel=lambda: context.cancelled,
                force=bool(params.get("force")),
            )
        except SetupCancelled as error:
            raise JobCancelled(context.job_id) from error
        result = [state.to_dict() for state in states]
        self.state.record("models", installed=result)
        return {"models": result}

    def register(self, manager: JobManager) -> None:
        manager.register("setup_tools", self.install_tools_job)
        manager.register("setup_environments", self.install_environments_job)
        manager.register("setup_models", self.install_models_job)
