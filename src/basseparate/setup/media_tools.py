"""Managed FFmpeg/FFprobe assets, per-platform pins and setup installation.

The application never bundles FFmpeg. Setup may download a static build into
``<data>/tools/ffmpeg`` after the media-tool licence gate; the runtime resolver
prefers those executables over PATH and records the exact build/licence.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from basseparate.config import RuntimePaths, runtime_paths
from basseparate.setup.download import download_verified
from basseparate.setup.errors import SetupCancelled, SetupInstallError
from basseparate.setup.tool_assets import platform_name

MediaTool = Literal["ffmpeg", "ffprobe"]
PlatformName = Literal["linux", "windows", "macos"]
Downloader = Callable[["MediaToolAsset", Path], None]
Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]


@dataclass(frozen=True)
class MediaToolAsset:
    tool: MediaTool
    platform: PlatformName
    version: str
    build: str
    license: str
    source_url: str
    url: str
    sha256: str
    size: int
    filename: str
    member: str


PLATFORM_MEDIA_ASSETS: dict[tuple[str, str], MediaToolAsset] = {
    ("windows", "ffmpeg"): MediaToolAsset(
        tool="ffmpeg",
        platform="windows",
        version="8.1.2",
        build="gyan.dev ffmpeg-8.1.2-essentials_build (2026-06-27)",
        license="GPL-3.0-or-later",
        source_url="https://www.gyan.dev/ffmpeg/builds/",
        url="https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip",
        sha256="db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec",
        size=109_728_040,
        filename="ffmpeg-8.1.2-essentials_build.zip",
        member="ffmpeg-8.1.2-essentials_build/bin/ffmpeg.exe",
    ),
    ("windows", "ffprobe"): MediaToolAsset(
        tool="ffprobe",
        platform="windows",
        version="8.1.2",
        build="gyan.dev ffmpeg-8.1.2-essentials_build (2026-06-27)",
        license="GPL-3.0-or-later",
        source_url="https://www.gyan.dev/ffmpeg/builds/",
        url="https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip",
        sha256="db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec",
        size=109_728_040,
        filename="ffmpeg-8.1.2-essentials_build.zip",
        member="ffmpeg-8.1.2-essentials_build/bin/ffprobe.exe",
    ),
    ("linux", "ffmpeg"): MediaToolAsset(
        tool="ffmpeg",
        platform="linux",
        version="9.0.2",
        build="Martin Riedl release build 1789931100_9.0.2",
        license="GPL-3.0-or-later",
        source_url="https://ffmpeg.martin-riedl.de/",
        url="https://ffmpeg.martin-riedl.de/download/linux/amd64/1789931100_9.0.2/ffmpeg.zip",
        sha256="fa8ecf4abbd290d98f7d188b8649cc6b391ae209a98452be955a15aab1909d7f",
        size=33_326_445,
        filename="ffmpeg-9.0.2-linux-amd64.zip",
        member="ffmpeg",
    ),
    ("linux", "ffprobe"): MediaToolAsset(
        tool="ffprobe",
        platform="linux",
        version="9.0.2",
        build="Martin Riedl release build 1789931100_9.0.2",
        license="GPL-3.0-or-later",
        source_url="https://ffmpeg.martin-riedl.de/",
        url="https://ffmpeg.martin-riedl.de/download/linux/amd64/1789931100_9.0.2/ffprobe.zip",
        sha256="3f428c49070be3d24ec338602b76d412e401ffcb8a5641ef0e729181a232fc32",
        size=33_223_234,
        filename="ffprobe-9.0.2-linux-amd64.zip",
        member="ffprobe",
    ),
    ("macos", "ffmpeg"): MediaToolAsset(
        tool="ffmpeg",
        platform="macos",
        version="9.0.2",
        build="Martin Riedl release build 1789931890_9.0.2 (signed arm64)",
        license="GPL-3.0-or-later",
        source_url="https://ffmpeg.martin-riedl.de/",
        url="https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffmpeg.zip",
        sha256="c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924",
        size=28_395_699,
        filename="ffmpeg-9.0.2-macos-arm64.zip",
        member="ffmpeg",
    ),
    ("macos", "ffprobe"): MediaToolAsset(
        tool="ffprobe",
        platform="macos",
        version="9.0.2",
        build="Martin Riedl release build 1789931890_9.0.2 (signed arm64)",
        license="GPL-3.0-or-later",
        source_url="https://ffmpeg.martin-riedl.de/",
        url="https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffprobe.zip",
        sha256="fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6",
        size=28_317_701,
        filename="ffprobe-9.0.2-macos-arm64.zip",
        member="ffprobe",
    ),
}


def _platform() -> PlatformName:
    selected = platform_name()
    if selected not in {"linux", "windows", "macos"}:
        raise SetupInstallError(f"no managed media tools for {selected}")
    return selected


def media_tool_dir(runtime: RuntimePaths | None = None) -> Path:
    active = runtime or runtime_paths()
    return active.data_root / "tools" / "ffmpeg"


def _executable_name(tool: str, platform: str) -> str:
    return f"{tool}.exe" if platform == "windows" else tool


def media_tools_status(runtime: RuntimePaths | None = None) -> dict[str, dict[str, object]]:
    active = runtime or runtime_paths()
    bundled = active.app_root / "tools" / "ffmpeg"
    bundled_meta = active.app_root / "tools" / "bundled-tools.json"
    suffix = ".exe" if platform_name() == "windows" else ""
    if (bundled / f"ffmpeg{suffix}").is_file() and (bundled / f"ffprobe{suffix}").is_file():
        bundled_metadata: dict[str, object] = {}
        try:
            loaded = json.loads(bundled_meta.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                bundled_metadata = (
                    loaded.get("ffmpeg", {}) if isinstance(loaded.get("ffmpeg"), dict) else {}
                )
        except (OSError, json.JSONDecodeError):
            bundled_metadata = {}
        return {
            "ffmpeg": {
                "installed": True,
                "path": str(bundled / f"ffmpeg{suffix}"),
                "version": bundled_metadata.get("version", "9.0.2"),
                "build": "bundled Windows FFmpeg",
                "license": bundled_metadata.get("license", "GPL-3.0-or-later"),
                "source_url": bundled_metadata.get("source"),
            },
            "ffprobe": {
                "installed": True,
                "path": str(bundled / f"ffprobe{suffix}"),
                "version": bundled_metadata.get("version", "9.0.2"),
                "build": "bundled Windows FFmpeg",
                "license": bundled_metadata.get("license", "GPL-3.0-or-later"),
                "source_url": bundled_metadata.get("source"),
            },
        }
    root = media_tool_dir(active)
    metadata: dict[str, object] = {}
    metadata_path = root / "media-tools.json"
    if metadata_path.is_file():
        try:
            loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                metadata = loaded
        except (OSError, json.JSONDecodeError):
            metadata = {}
    status: dict[str, dict[str, object]] = {}
    for tool in ("ffmpeg", "ffprobe"):
        for platform in ("linux", "windows", "macos"):
            path = root / _executable_name(tool, platform)
            if path.is_file():
                loaded_record = metadata.get(tool)
                record: dict[str, object] = loaded_record if isinstance(loaded_record, dict) else {}
                status[tool] = {
                    "installed": True,
                    "path": str(path),
                    "version": record.get("version"),
                    "build": record.get("build"),
                    "license": record.get("license"),
                    "source_url": record.get("source_url"),
                }
                break
        else:
            status[tool] = {"installed": False, "path": str(root / tool)}
    return status


def media_tools_ready(runtime: RuntimePaths | None = None) -> bool:
    return all(bool(item["installed"]) for item in media_tools_status(runtime).values())


def _verify(asset: MediaToolAsset, archive: Path) -> None:
    if not archive.is_file():
        raise SetupInstallError(f"{asset.filename} is missing after download")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if archive.stat().st_size != asset.size or digest != asset.sha256:
        raise SetupInstallError(
            f"{asset.filename} failed size/SHA-256 verification; refusing to install"
        )


def _extract_member(archive: Path, member: str, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        try:
            source = bundle.open(member)
        except KeyError as error:
            raise SetupInstallError(f"{archive.name} has no {member}") from error
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source, destination.open("wb") as target:
            shutil.copyfileobj(source, target)
    destination.chmod(0o755)


def install_media_tools(
    runtime: RuntimePaths | None = None,
    *,
    platform: PlatformName | None = None,
    downloader: Downloader | None = None,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> dict[str, dict[str, object]]:
    """Download and verify managed FFmpeg/FFprobe under the data root."""
    active = runtime or runtime_paths()
    selected = platform or _platform()
    existing = media_tools_status(active)
    if all(item["installed"] for item in existing.values()):
        if progress is not None:
            progress(1.0, "media tools already installed")
        return existing
    root = active.ensure_data_path(media_tool_dir(active))
    downloaded: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix=".media-tools-", dir=active.data_root) as tmp:
        for index, tool in enumerate(("ffmpeg", "ffprobe")):
            if cancel is not None and cancel():
                raise SetupCancelled("media-tool installation cancelled")
            if existing.get(tool, {}).get("installed"):
                if progress is not None:
                    progress(0.1 + 0.4 * index, f"{tool} already installed")
                continue
            asset = PLATFORM_MEDIA_ASSETS.get((selected, tool))
            if asset is None:
                raise SetupInstallError(f"no pinned {tool} asset for {selected}")
            archive = downloaded.get(asset.url)
            if archive is None:
                archive = Path(tmp) / asset.filename
                if downloader is not None:
                    downloader(asset, archive)
                else:
                    download_verified(
                        asset.url,
                        archive,
                        size_bytes=asset.size,
                        sha256=asset.sha256,
                    )
                _verify(asset, archive)
                downloaded[asset.url] = archive
            if progress is not None:
                progress(0.1 + 0.4 * index, f"installing {tool}")
            _extract_member(
                archive,
                asset.member,
                root / _executable_name(asset.tool, asset.platform),
            )
        metadata = {
            tool: {
                "version": asset.version,
                "build": asset.build,
                "license": asset.license,
                "source_url": asset.source_url,
                "url": asset.url,
                "sha256": asset.sha256,
                "size": asset.size,
            }
            for tool in ("ffmpeg", "ffprobe")
            if (asset := PLATFORM_MEDIA_ASSETS[(selected, tool)])
        }
        (root / "media-tools.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
    if progress is not None:
        progress(1.0, "media tools installed")
    return media_tools_status(active)


__all__ = [
    "PLATFORM_MEDIA_ASSETS",
    "MediaToolAsset",
    "install_media_tools",
    "media_tool_dir",
    "media_tools_ready",
    "media_tools_status",
]
