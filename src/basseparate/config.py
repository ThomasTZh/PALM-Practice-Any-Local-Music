"""Server configuration and the on-disk data layout.

The data root is configurable through ``BASSEPARATE_DATA_DIR`` and defaults to
the per-user application data directory. Tests and the make harness point it at
a scratch directory. Everything the server owns lives below this one root, so a
practice session is portable and easy to remove.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent

RuntimeMode = Literal["source", "packaged"]


class RuntimePathError(RuntimeError):
    """A runtime path would write outside the writable data root."""


@dataclass(frozen=True)
class RuntimePaths:
    """Resolve read-only application resources and writable user data.

    Source mode keeps the checkout layout used by the repository. Packaged
    mode treats ``app_root`` as read-only and places models, tools,
    environments, logs and setup state below ``data_root``. The defaults are
    resolved from ``PALM_MODE``, ``PALM_APP_ROOT`` and ``PALM_DATA_DIR``.
    """

    mode: RuntimeMode
    app_root: Path
    data_root: Path

    @classmethod
    def from_environment(
        cls,
        *,
        mode: str | None = None,
        app_root: Path | str | None = None,
        data_root: Path | str | None = None,
    ) -> RuntimePaths:
        raw_mode = mode if mode is not None else os.environ.get("PALM_MODE", "source")
        raw_mode = raw_mode.strip().lower()
        if raw_mode not in {"source", "packaged"}:
            raise RuntimePathError(
                f"unknown PALM_MODE {raw_mode!r}; expected 'source' or 'packaged'"
            )
        runtime_mode: RuntimeMode = raw_mode  # type: ignore[assignment]
        if app_root is not None:
            resolved_app = Path(app_root)
        elif os.environ.get("PALM_APP_ROOT"):
            resolved_app = Path(os.environ["PALM_APP_ROOT"])
        elif runtime_mode == "packaged":
            resolved_app = Path(sys.executable).resolve().parent
        else:
            resolved_app = REPO_ROOT
        if data_root is not None:
            resolved_data = Path(data_root)
        elif os.environ.get("PALM_DATA_DIR"):
            resolved_data = Path(os.environ["PALM_DATA_DIR"])
        elif runtime_mode == "packaged":
            resolved_data = Path(user_data_dir("palm", appauthor=False))
        elif os.environ.get("BASSEPARATE_DATA_DIR"):
            resolved_data = Path(os.environ["BASSEPARATE_DATA_DIR"])
        else:
            resolved_data = Path(user_data_dir("basseparate", appauthor=False))
        return cls(
            mode=runtime_mode,
            app_root=resolved_app.expanduser().resolve(),
            data_root=resolved_data.expanduser().resolve(),
        )

    @property
    def packaged(self) -> bool:
        return self.mode == "packaged"

    @property
    def web_dir(self) -> Path:
        return self.app_root / "web" / "dist"

    @property
    def analysis_dir(self) -> Path:
        """Read-only analysis scripts, registry and checkpoint manifest."""
        return self.app_root / "analysis"

    @property
    def models_root(self) -> Path:
        return self.data_root if self.packaged else self.app_root

    @property
    def tools_root(self) -> Path:
        return self.data_root / "tools" if self.packaged else self.app_root / "storage" / "tools"

    @property
    def environments_root(self) -> Path:
        """Root of the Python environments; writable in packaged mode."""
        return self.data_root / "environments" if self.packaged else self.app_root

    @property
    def uv(self) -> Path:
        if self.packaged:
            return self.app_root / "bin" / "uv"
        found = shutil.which("uv")
        return Path(found) if found else Path("uv")

    @property
    def uv_path(self) -> Path:
        return self.uv

    @property
    def demucs_python(self) -> Path:
        if self.packaged:
            return self.environments_root / "demucs" / "bin" / "python"
        return self.app_root / "analysis" / ".venv" / "bin" / "python"

    @property
    def msst_python(self) -> Path:
        if self.packaged:
            return self.environments_root / "msst" / "bin" / "python"
        return self.app_root / "analysis-models" / ".venv" / "bin" / "python"

    @property
    def analysis_python(self) -> Path:
        return self.demucs_python

    @property
    def analysis_models_python(self) -> Path:
        return self.msst_python

    @property
    def demucs_worker(self) -> Path:
        return self.analysis_dir / "separate_track.py"

    @property
    def msst_worker(self) -> Path:
        return self.analysis_dir / "separate_msst.py"

    @property
    def workers(self) -> dict[str, Path]:
        return {"demucs": self.demucs_worker, "msst": self.msst_worker}

    def worker(self, engine: str) -> Path:
        try:
            return self.workers[engine]
        except KeyError as error:
            raise RuntimePathError(f"unknown separation engine {engine!r}") from error

    def environment_python(self, engine: str) -> Path:
        if engine == "demucs":
            return self.demucs_python
        if engine == "msst":
            return self.msst_python
        raise RuntimePathError(f"unknown separation engine {engine!r}")

    @property
    def registry_path(self) -> Path:
        return self.analysis_dir / "models.json"

    @property
    def checkpoint_manifest(self) -> Path:
        return self.analysis_dir / "checkpoints.json"

    @property
    def logs_root(self) -> Path:
        return self.data_root / "logs"

    @property
    def setup_state(self) -> Path:
        return self.data_root / "setup.json"

    @property
    def caches_root(self) -> Path:
        return self.data_root / "cache"

    def with_data_root(self, data_root: Path | str) -> RuntimePaths:
        return replace(self, data_root=Path(data_root).expanduser().resolve())

    def _within_data_root(self, path: Path) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.data_root / candidate
        try:
            candidate.resolve().relative_to(self.data_root.resolve())
        except (OSError, ValueError) as error:
            raise RuntimePathError(
                f"writable path {candidate} is outside the data root {self.data_root}"
            ) from error
        return candidate

    def data_path(self, *parts: str | Path) -> Path:
        """Return a path below data_root, rejecting traversal outside it."""
        candidate = self.data_root.joinpath(*parts)
        return self._within_data_root(candidate)

    def ensure_data_path(self, path: Path | str) -> Path:
        """Create a directory or parent below data_root; never touch app_root."""
        target = self._within_data_root(Path(path))
        directory = target if not target.suffix else target.parent
        directory.mkdir(parents=True, exist_ok=True)
        return target


def runtime_paths(
    *,
    mode: str | None = None,
    app_root: Path | str | None = None,
    data_root: Path | str | None = None,
) -> RuntimePaths:
    """The one runtime path resolver used by the server and its helpers."""
    return RuntimePaths.from_environment(mode=mode, app_root=app_root, data_root=data_root)


DEFAULT_SAMPLE_RATE = 48_000
SUPPORTED_SAMPLE_RATES = (44_100, 48_000, 88_200, 96_000)
MAX_UPLOAD_BYTES = 4 * 1024**3


def default_web_dir() -> Path:
    """The Vite build output in the resolved application root."""
    return runtime_paths().web_dir


@dataclass(frozen=True)
class DataPaths:
    """One place that decides where each kind of server data lives."""

    root: Path
    projects: Path
    assets: Path
    uploads: Path
    tmp: Path
    locks: Path

    @classmethod
    def from_root(cls, root: Path) -> DataPaths:
        root = Path(root).expanduser()
        return cls(
            root=root,
            projects=root / "projects",
            assets=root / "assets",
            uploads=root / "uploads",
            tmp=root / "tmp",
            locks=root / ".locks",
        )

    def ensure(self) -> DataPaths:
        directories = (self.root, self.projects, self.assets, self.uploads, self.tmp, self.locks)
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def project_file(self, project_id: str) -> Path:
        return self.projects / f"{project_id}.json"

    def asset_dir(self, asset_id: str) -> Path:
        return self.assets / asset_id

    def upload_dir(self, token: str) -> Path:
        return self.uploads / token


class Settings(BaseSettings):
    """Boundary configuration; environment variables use the BASSEPARATE_ prefix."""

    model_config = SettingsConfigDict(env_prefix="BASSEPARATE_", extra="ignore")

    data_dir: Path = Field(default_factory=lambda: runtime_paths().data_root)
    web_dir: Path = Field(default_factory=default_web_dir)
    sample_rate: int = DEFAULT_SAMPLE_RATE
    max_upload_bytes: int = MAX_UPLOAD_BYTES

    @property
    def data_paths(self) -> DataPaths:
        return DataPaths.from_root(self.data_dir)

    def runtime_paths(self) -> RuntimePaths:
        """Resolve runtime paths with this settings object's data choice."""
        return runtime_paths(data_root=self.data_dir)
