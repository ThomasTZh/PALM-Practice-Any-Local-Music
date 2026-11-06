"""CPU/CUDA inference environment creation under the writable data root."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from basseparate.config import RuntimePaths, runtime_paths
from basseparate.setup.errors import SetupCancelled, SetupInstallError

EnvVariant = Literal["cpu", "cuda"]
ENV_VARIANTS: tuple[EnvVariant, ...] = ("cpu", "cuda")
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


def environment_spec(variant: EnvVariant, runtime: RuntimePaths | None = None) -> EnvironmentSpec:
    active = runtime or runtime_paths()
    if variant not in ENV_VARIANTS:
        raise SetupInstallError(f"unknown environment variant {variant!r}")
    project = active.analysis_dir.parent / "analysis-models"
    target = active.data_path("environments", variant)
    python = active.app_root / "bin" / "python" if active.packaged else Path(sys.executable)
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
    python = spec.target / "bin" / "python"
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
    return {variant: environment_status(variant, runtime) for variant in ENV_VARIANTS}


def _default_run_uv(command: list[str], env: dict[str, str], cwd: Path) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise SetupInstallError(
            f"uv sync failed ({result.returncode}): {detail[-1] if detail else 'no output'}"
        )


def create_environment(
    variant: EnvVariant,
    *,
    runtime: RuntimePaths | None = None,
    run_uv: RunUv | None = None,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> dict[str, object]:
    """Create one environment in staging, then atomically publish it."""
    active = runtime or runtime_paths()
    spec = environment_spec(variant, active)
    if (spec.target / "bin" / "python").is_file():
        if progress is not None:
            progress(1.0, f"{variant} environment already installed")
        return environment_status(variant, active)
    parents = active.ensure_data_path(spec.target.parent)
    staging = parents / f".{variant}.staging-{uuid.uuid4().hex}"
    environment = dict(os.environ)
    environment["UV_PROJECT_ENVIRONMENT"] = str(staging)
    environment["UV_CACHE_DIR"] = str(spec.cache_dir)
    environment["UV_PYTHON"] = str(spec.python)
    environment["UV_INDEX_URL"] = spec.index_url
    environment["PALM_ENV_VARIANT"] = variant
    command = [
        str(spec.uv),
        "sync",
        "--offline",
        "--directory",
        str(spec.project_dir),
        "--python",
        str(spec.python),
        "--index-url",
        spec.index_url,
    ]
    runner = run_uv if run_uv is not None else _default_run_uv
    try:
        if cancel is not None and cancel():
            raise SetupCancelled(f"{variant} environment creation cancelled")
        if progress is not None:
            progress(0.1, f"creating {variant} environment")
        runner(command, environment, spec.project_dir)
        if cancel is not None and cancel():
            raise SetupCancelled(f"{variant} environment creation cancelled")
        if not (staging / "bin" / "python").is_file():
            raise SetupInstallError(f"uv finished but {staging / 'bin' / 'python'} is missing")
        if spec.target.exists():
            shutil.rmtree(spec.target)
        staging.replace(spec.target)
        if progress is not None:
            progress(1.0, f"{variant} environment installed")
        return environment_status(variant, active)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
