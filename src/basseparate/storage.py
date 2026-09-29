"""Application storage directory layout.

Categories follow the XDG base-directory specification: configuration, data,
cache, state, and a runtime category for instance locks and temporary session
metadata. ``--storage-root`` places every category beneath one explicit
directory for tests and portable development.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir, user_state_dir

from basseparate import APP_NAME


class StorageError(RuntimeError):
    """Raised when essential storage is unavailable."""


@dataclass(frozen=True, slots=True)
class StoragePaths:
    config: Path
    data: Path
    cache: Path
    state: Path
    runtime: Path

    @property
    def database_path(self) -> Path:
        return self.data / f"{APP_NAME}.db"


def default_storage_paths() -> StoragePaths:
    state = Path(user_state_dir(APP_NAME))
    return StoragePaths(
        config=Path(user_config_dir(APP_NAME)),
        data=Path(user_data_dir(APP_NAME)),
        cache=Path(user_cache_dir(APP_NAME)),
        state=state,
        runtime=state / "runtime",
    )


def resolve_storage_paths(storage_root: Path | None) -> StoragePaths:
    if storage_root is None:
        return default_storage_paths()
    root = storage_root.expanduser()
    return StoragePaths(
        config=root / "config",
        data=root / "data",
        cache=root / "cache",
        state=root / "state",
        runtime=root / "runtime",
    )


def initialize_storage_paths(paths: StoragePaths) -> None:
    """Create missing app-owned directories and verify writability.

    Never deletes or clears existing contents: a user-selected path is never
    treated as a directory to clear recursively.
    """

    for directory in (paths.config, paths.data, paths.cache, paths.state, paths.runtime):
        if directory.exists() and not directory.is_dir():
            raise StorageError(f"storage path exists and is not a directory: {directory}")
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"cannot create storage directory {directory}: {exc}") from exc
        if not os.access(directory, os.W_OK):
            raise StorageError(f"storage directory is not writable: {directory}")

    # Owner-only permissions for the sensitive categories.
    for directory in (paths.data, paths.runtime):
        try:
            directory.chmod(0o700)
        except OSError as exc:
            raise StorageError(f"cannot set owner-only permissions on {directory}: {exc}") from exc
