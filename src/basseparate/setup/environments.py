"""CPU/CUDA inference environment creation under the writable data root."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from basseparate.config import RuntimePaths, runtime_paths
from basseparate.platform_support import venv_python
from basseparate.setup.errors import SetupCancelled, SetupInstallError

EnvVariant = Literal["cpu", "cuda"]
ENV_VARIANTS: tuple[EnvVariant, ...] = ("cpu", "cuda")
PLATFORM_ENV_PROJECTS = {
    "cpu-windows": "Windows CPU",
    "cpu-macos": "macOS CPU",
    "msst-windows": "Windows MSST",
    "msst-macos": "macOS MSST",
}
ENV_INDEX_URLS: dict[EnvVariant, str] = {
    "cpu": "https://download.pytorch.org/whl/cpu",
    "cuda": "https://download.pytorch.org/whl/cu128",
}
RunUv = Callable[[list[str], dict[str, str], Path], None]
Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]


@dataclass(frozen=True)
class EnvironmentSpec:
    variant: EnvVariant
    project_dir: Path
    target: Path
    python: Path
    uv: Path
    cache_dir: Path
    index_url: str


def available_env_variants() -> tuple[EnvVariant, ...]:
    """CUDA is a Linux-only inference target."""
    from basseparate.platform_support import MACOS, WINDOWS

    if WINDOWS or MACOS:
        return ("cpu",)
    return ENV_VARIANTS


def environment_project_name(variant: EnvVariant) -> str:
    from basseparate.platform_support import MACOS, WINDOWS

    if variant == "cuda":
        return "cuda"
    if WINDOWS:
        return "cpu-windows"
    if MACOS:
        return "cpu-macos"
    return "cpu"


def environment_spec(variant: EnvVariant, runtime: RuntimePaths | None = None) -> EnvironmentSpec:
    active = runtime or runtime_paths()
    if variant not in available_env_variants():
        raise SetupInstallError(
            f"environment variant {variant!r} is not available on this platform"
        )
    project = active.analysis_dir / "envs" / environment_project_name(variant)
    target = active.data_path("environments", variant)
    python = active.bundled_python
    return EnvironmentSpec(
        variant=variant,
        project_dir=project,
        target=target,
        python=python,
        uv=active.uv,
        cache_dir=active.caches_root / "uv",
        index_url=ENV_INDEX_URLS[variant],
    )


def environment_status(
    variant: EnvVariant, runtime: RuntimePaths | None = None
) -> dict[str, object]:
    active = runtime or runtime_paths()
    spec = environment_spec(variant, active)
    python = venv_python(spec.target)
    installed = python.is_file()
    # The source checkout already has one working inference environment; keep
    # it visible as the CPU variant instead of making development run setup.
    if not installed and not active.packaged and variant == "cpu" and active.msst_python.is_file():
        python = active.msst_python
        installed = True
    return {
        "variant": variant,
        "installed": installed,
        "path": str(spec.target),
        "python": str(python),
        "project": str(spec.project_dir),
        "uv": str(spec.uv),
    }


def environments_status(runtime: RuntimePaths | None = None) -> dict[str, dict[str, object]]:
    return {variant: environment_status(variant, runtime) for variant in available_env_variants()}


def _default_run_uv(
    command: list[str],
    env: dict[str, str],
    cwd: Path,
    *,
    cancel: Cancel | None = None,
    progress: Progress | None = None,
) -> None:
    with (
        tempfile.TemporaryFile(mode="w+") as stdout_file,
        tempfile.TemporaryFile(mode="w+") as stderr_file,
    ):
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
        )
        if progress is not None:
            progress(0.25, "uv sync running")
        try:
            while process.poll() is None:
                if cancel is not None and cancel():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise SetupCancelled("environment creation cancelled")
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()
    if process.returncode != 0:
        detail = (stderr or stdout or "").strip().splitlines()
        raise SetupInstallError(
            f"uv sync failed ({process.returncode}): {detail[-1] if detail else 'no output'}"
        )
    if progress is not None:
        progress(0.7, "uv sync finished")


def create_environment(
    variant: EnvVariant,
    *,
    runtime: RuntimePaths | None = None,
    run_uv: RunUv | None = None,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
    offline: bool = False,
    uv: Path | None = None,
) -> dict[str, object]:
    """Create one environment in staging, then atomically publish it."""
    active = runtime or runtime_paths()
    spec = environment_spec(variant, active)
    if uv is not None:
        spec = EnvironmentSpec(
            variant=spec.variant,
            project_dir=spec.project_dir,
            target=spec.target,
            python=spec.python,
            uv=Path(uv),
            cache_dir=spec.cache_dir,
            index_url=spec.index_url,
        )
    if venv_python(spec.target).is_file():
        if progress is not None:
            progress(1.0, f"{variant} environment already installed")
        return environment_status(variant, active)
    parents = active.ensure_data_path(spec.target.parent)
    staging = parents / f".{variant}.staging-{uuid.uuid4().hex}"
    environment = dict(os.environ)
    environment["UV_PROJECT_ENVIRONMENT"] = str(staging)
    environment["UV_CACHE_DIR"] = str(spec.cache_dir)
    environment["UV_PYTHON"] = str(spec.python)
    environment["PALM_ENV_VARIANT"] = variant
    command = [str(spec.uv), "sync"]
    if offline:
        command.append("--offline")
    command.extend(
        [
            "--directory",
            str(spec.project_dir),
            "--python",
            str(spec.python),
        ]
    )
    runner = run_uv
    try:
        if cancel is not None and cancel():
            raise SetupCancelled(f"{variant} environment creation cancelled")
        if progress is not None:
            progress(0.1, f"creating {variant} environment")
        if runner is not None:
            runner(command, environment, spec.project_dir)
        else:
            _default_run_uv(
                command,
                environment,
                spec.project_dir,
                cancel=cancel,
                progress=progress,
            )
        if cancel is not None and cancel():
            raise SetupCancelled(f"{variant} environment creation cancelled")
        if not venv_python(staging).is_file():
            raise SetupInstallError(f"uv finished but {venv_python(staging)} is missing")
        if spec.target.exists():
            shutil.rmtree(spec.target)
        staging.replace(spec.target)
        if progress is not None:
            progress(1.0, f"{variant} environment installed")
        return environment_status(variant, active)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
