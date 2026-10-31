"""Server configuration and the on-disk data layout.

The data root is configurable through ``BASSEPARATE_DATA_DIR`` and defaults to
the per-user application data directory. Tests and the make harness point it at
a scratch directory. Everything the server owns lives below this one root, so a
practice session is portable and easy to remove.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent

DEFAULT_SAMPLE_RATE = 48_000
SUPPORTED_SAMPLE_RATES = (44_100, 48_000, 88_200, 96_000)
MAX_UPLOAD_BYTES = 4 * 1024**3


def default_web_dir() -> Path:
    """The Vite build output, relative to the checkout (not the package)."""
    return REPO_ROOT / "web" / "dist"


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

    data_dir: Path = Field(
        default_factory=lambda: Path(user_data_dir("basseparate", appauthor=False))
    )
    web_dir: Path = Field(default_factory=default_web_dir)
    sample_rate: int = DEFAULT_SAMPLE_RATE
    max_upload_bytes: int = MAX_UPLOAD_BYTES

    @property
    def data_paths(self) -> DataPaths:
        return DataPaths.from_root(self.data_dir)
