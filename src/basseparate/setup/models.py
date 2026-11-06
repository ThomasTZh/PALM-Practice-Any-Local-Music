"""Equal, file-based model installation with atomic publication."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

from basseparate.config import RuntimePaths, runtime_paths
from basseparate.model_registry import (
    ModelEntry,
    ModelState,
    load_registry,
    model_directory,
    verify_model,
)
from basseparate.setup.download import Fetch, download_verified
from basseparate.setup.errors import SetupCancelled, SetupInstallError

Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]


def install_model(
    entry: ModelEntry,
    *,
    runtime: RuntimePaths | None = None,
    fetch: Fetch | None = None,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
    force: bool = False,
) -> ModelState:
    """Install one model from its pinned files without a bundled special case."""
    active = runtime or runtime_paths()
    root = active.models_root
    state = verify_model(entry, root)
    if state.installed and not force:
        if progress is not None:
            progress(1.0, f"{entry.id} already installed")
        return state
    target = model_directory(entry, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{entry.id}.staging-", dir=target.parent))
    parts_root = active.caches_root / "model-parts" / entry.id
    parts_root.mkdir(parents=True, exist_ok=True)
    backup = target.parent / f".{entry.id}.backup-{os.getpid()}"
    published = False
    try:
        total = sum(item.size_bytes for item in entry.files) or 1
        completed = 0
        for item in entry.files:
            if cancel is not None and cancel():
                raise SetupCancelled(f"{entry.id} installation cancelled")
            if progress is not None:
                progress(completed / total, f"downloading {item.name}")
            part = parts_root / item.name

            def on_progress(
                done: int,
                item_total: int,
                *,
                base: int = completed,
                name: str = item.name,
                all_bytes: int = total,
            ) -> None:
                if progress is not None:
                    progress((base + done) / all_bytes, f"downloading {name}")

            download_verified(
                item.url,
                part,
                size_bytes=item.size_bytes,
                sha256=item.sha256,
                fetch=fetch,
                cancel=cancel,
                progress=on_progress if progress is not None else None,
            )
            shutil.copy2(part, staging / item.name)
            completed += item.size_bytes
        if cancel is not None and cancel():
            raise SetupCancelled(f"{entry.id} installation cancelled")
        if target.exists():
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            target.replace(backup)
        staging.replace(target)
        published = True
        installed = verify_model(entry, root)
        if not installed.installed:
            raise SetupInstallError(
                f"{entry.id}: post-install verification failed: {installed.detail}"
            )
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(parts_root, ignore_errors=True)
        if progress is not None:
            progress(1.0, f"{entry.id} installed and verified")
        return installed
    except BaseException:
        if published and target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if backup.exists() and not target.exists():
            backup.replace(target)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


def install_models(
    model_ids: Iterable[str],
    *,
    runtime: RuntimePaths | None = None,
    fetch: Fetch | None = None,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
    force: bool = False,
) -> list[ModelState]:
    active = runtime or runtime_paths()
    registry = load_registry(active.registry_path)
    ids = list(model_ids)
    states: list[ModelState] = []
    for index, model_id in enumerate(ids):
        entry = registry.get(model_id)
        if progress is not None:
            progress(index / max(1, len(ids)), f"preparing {entry.id}")
        states.append(
            install_model(
                entry,
                runtime=active,
                fetch=fetch,
                progress=progress,
                cancel=cancel,
                force=force,
            )
        )
    return states
