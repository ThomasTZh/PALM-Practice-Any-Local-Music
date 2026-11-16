"""User-initiated update and uninstall helpers.

The running app only checks metadata, downloads/stages a verified asset below
the data root, and launches a helper outside the app. The helper waits for the
app to exit before swapping, keeps a rollback copy, and never touches the data
root. Uninstall is also delegated to a helper so the running executable is not
deleted underneath itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from basseparate.platform_support import hidden_process_kwargs


class UpdateError(RuntimeError):
    """A user-facing update or uninstall failure."""


@dataclass(frozen=True)
class UpdateAsset:
    channel: str
    version: str
    name: str
    url: str
    sha256: str
    kind: str


@dataclass(frozen=True)
class InstallMetadata:
    channel: str
    version: str
    app_root: Path
    data_root: Path
    assets: Mapping[str, UpdateAsset]

    @property
    def asset(self) -> UpdateAsset:
        try:
            return self.assets[self.channel]
        except KeyError as error:
            raise UpdateError(
                f"install metadata has no asset for channel {self.channel!r}"
            ) from error


def load_metadata(
    app_root: Path,
    data_root: Path,
    *,
    metadata_path: Path | None = None,
) -> InstallMetadata:
    """Read install.json from the app root; never infer a channel from PATH."""
    path = metadata_path or app_root / "install.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpdateError(f"cannot read install metadata {path}: {error}") from error
    channel = payload.get("channel")
    version = payload.get("version")
    assets = payload.get("assets", {})
    if not isinstance(channel, str) or not channel or not isinstance(version, str):
        raise UpdateError("install metadata needs channel and version")
    if not isinstance(assets, dict):
        raise UpdateError("install metadata assets must be a mapping")
    parsed: dict[str, UpdateAsset] = {}
    for key, raw in assets.items():
        if not isinstance(raw, dict):
            raise UpdateError(f"install metadata asset {key!r} is not an object")
        try:
            parsed[str(key)] = UpdateAsset(
                channel=str(key),
                version=str(raw.get("version", version)),
                name=str(raw["name"]),
                url=str(raw["url"]),
                sha256=str(raw["sha256"]).lower(),
                kind=str(raw.get("kind", "tar.gz")),
            )
        except KeyError as error:
            raise UpdateError(f"install metadata asset {key!r} is missing {error}") from error
    return InstallMetadata(channel, version, app_root, data_root, parsed)


def select_update(metadata: InstallMetadata, release: Mapping[str, Any]) -> UpdateAsset | None:
    """Select the asset for the installed channel from a release manifest."""
    channels = release.get("channels", release.get("assets"))
    if not isinstance(channels, dict):
        raise UpdateError("release manifest has no channels/assets")
    raw = channels.get(metadata.channel)
    if not isinstance(raw, dict):
        return None
    version = str(raw.get("version", release.get("version", "")))
    if version == metadata.version:
        return None
    try:
        candidate = UpdateAsset(
            channel=metadata.channel,
            version=version,
            name=str(raw["name"]),
            url=str(raw["url"]),
            sha256=str(raw["sha256"]).lower(),
            kind=str(raw.get("kind", "tar.gz")),
        )
    except KeyError as error:
        raise UpdateError(f"release asset for {metadata.channel} is missing {error}") from error
    if not candidate.url.startswith("https://"):
        raise UpdateError("update URL must use https")
    if len(candidate.sha256) != 64:
        raise UpdateError("update SHA-256 must be 64 hex characters")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_update(
    candidate: UpdateAsset,
    data_root: Path,
    *,
    download: Callable[[str, Path], None] | None = None,
) -> Path:
    """Download and verify an asset under <data>/updates; never touch app root."""
    directory = data_root / "updates" / candidate.version
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / candidate.name
    part = target.with_suffix(target.suffix + ".part")
    if download is None:

        def fetch(url: str, destination: Path) -> None:
            with urlopen(url, timeout=120) as response, destination.open("wb") as out:  # noqa: S310
                shutil.copyfileobj(response, out)

        download = fetch
    try:
        download(candidate.url, part)
    except OSError as error:
        part.unlink(missing_ok=True)
        raise UpdateError(f"update download failed: {error}") from error
    actual = _sha256(part)
    if actual != candidate.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError(f"update checksum mismatch: expected {candidate.sha256}, got {actual}")
    part.replace(target)
    return target


def write_plan(
    metadata: InstallMetadata,
    candidate: UpdateAsset,
    staged: Path,
    helper: Path,
    *,
    restart: list[str] | None = None,
) -> Path:
    """Write a pending plan; the app is still untouched."""
    directory = metadata.data_root / "updates"
    directory.mkdir(parents=True, exist_ok=True)
    plan = directory / "pending.json"
    payload = {
        "version": candidate.version,
        "channel": candidate.channel,
        "asset": str(staged),
        "kind": candidate.kind,
        "app_root": str(metadata.app_root),
        "data_root": str(metadata.data_root),
        "helper": str(helper),
        "pid": os.getpid(),
        "restart": restart
        or (
            [str(metadata.app_root / "bin" / "palm"), "--window"]
            if (metadata.app_root / "bin" / "palm").is_file()
            else []
        ),
    }
    plan.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return plan


def helper_path(app_root: Path) -> Path:
    """Return the external helper shipped beside the app (not inside it)."""
    return app_root.parent / "palm-update-helper.py"


def launch_helper(
    plan: Path, *, python: Path | None = None, popen: Callable[..., Any] | None = None
) -> None:
    """Launch an external, detached helper; the running app is not replaced."""
    try:
        payload = json.loads(plan.read_text(encoding="utf-8"))
        helper = Path(str(payload["helper"]))
    except (OSError, json.JSONDecodeError, KeyError) as error:
        raise UpdateError(f"cannot launch update helper: {error}") from error
    if not helper.is_file():
        raise UpdateError(f"update helper is missing: {helper}")
    if helper.resolve().is_relative_to(Path(payload["app_root"]).resolve()):
        raise UpdateError("update helper must live outside the app folder")
    executable = str(python or sys.executable)
    factory = popen or subprocess.Popen
    try:
        factory(
            [executable, str(helper), "--plan", str(plan)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            **hidden_process_kwargs(),
        )
    except OSError as error:
        raise UpdateError(f"cannot launch update helper: {error}") from error


def check_for_update(
    metadata: InstallMetadata,
    *,
    fetch_release: Callable[[str], Mapping[str, Any]] | None = None,
    release_url: str = "",
) -> UpdateAsset | None:
    """Check a release manifest for the installed channel."""
    if fetch_release is not None:
        release = fetch_release(release_url)
    else:
        if not release_url:
            raise UpdateError("no update release URL is configured")
        with urlopen(release_url, timeout=30) as response:  # noqa: S310
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise UpdateError("release manifest is not an object")
        release = value
    return select_update(metadata, release)


@dataclass(frozen=True)
class UninstallPlan:
    app_root: Path
    data_root: Path
    delete_data: bool
    pid: int
    shortcuts: tuple[Path, ...] = ()


def write_uninstall_plan(plan: UninstallPlan, helper: Path) -> Path:
    directory = plan.data_root / "updates"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "uninstall.json"
    path.write_text(
        json.dumps(
            {
                "app_root": str(plan.app_root),
                "data_root": str(plan.data_root),
                "delete_data": plan.delete_data,
                "pid": plan.pid,
                "shortcuts": [str(item) for item in plan.shortcuts],
                "helper": str(helper),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def launch_uninstall_helper(
    plan: UninstallPlan,
    helper: Path,
    *,
    python: Path | None = None,
    popen: Callable[..., Any] | None = None,
) -> Path:
    """Write and launch the external uninstall helper after the app exits."""
    if not helper.is_file():
        raise UpdateError(f"uninstall helper is missing: {helper}")
    if helper.resolve().is_relative_to(plan.app_root.resolve()):
        raise UpdateError("uninstall helper must live outside the app folder")
    path = write_uninstall_plan(plan, helper)
    executable = str(python or sys.executable)
    factory = popen or subprocess.Popen
    try:
        factory(
            [executable, str(helper), "--plan", str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            **hidden_process_kwargs(),
        )
    except OSError as error:
        raise UpdateError(f"cannot launch uninstall helper: {error}") from error
    return path


def default_delete_data(answer: bool) -> bool:
    """Keep data is the default; only an explicit true deletes it."""
    return answer is True
