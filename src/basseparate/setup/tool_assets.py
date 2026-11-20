"""Pinned Windows/macOS tool assets and per-user extraction.

Linux uses the preserved Sonic Visualiser/Piper AppImage installer. Windows
and macOS use the official Sonic Annotator and Vamp Plugin Pack releases,
downloaded only after the setup licence gate and extracted below the writable
data root. No asset is installed system-wide and no elevation is requested.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from basseparate import platform_support
from basseparate.config import RuntimePaths
from basseparate.platform_support import hidden_process_kwargs, plugin_suffix
from basseparate.setup.download import download_verified
from basseparate.setup.errors import SetupCancelled, SetupInstallError

PlatformName = Literal["linux", "windows", "macos"]
Runner = Callable[[list[str]], subprocess.CompletedProcess[str] | None]
Downloader = Callable[["PinnedToolAsset", Path], None]
Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]


@dataclass(frozen=True)
class PinnedToolAsset:
    tool: Literal["sonic_annotator", "vamp_plugin_pack"]
    platform: Literal["windows", "macos"]
    version: str
    url: str
    sha256: str
    size: int
    filename: str
    kind: Literal["zip", "tar.gz", "exe", "dmg"]
    install_name: str


PLATFORM_ASSETS: dict[tuple[str, str], PinnedToolAsset] = {
    ("windows", "sonic_annotator"): PinnedToolAsset(
        tool="sonic_annotator",
        platform="windows",
        version="1.7",
        url="https://github.com/sonic-visualiser/sonic-annotator/releases/download/sonic-annotator-1.7/sonic-annotator-1.7-win64.zip",
        sha256="c40717e029210cf1e1c97bc7dadea00cf4386327e67fdf9ca66027a91ea26693",
        size=6_618_013,
        filename="sonic-annotator-1.7-win64.zip",
        kind="zip",
        install_name="sonic-annotator-1.7.0",
    ),
    ("macos", "sonic_annotator"): PinnedToolAsset(
        tool="sonic_annotator",
        platform="macos",
        version="1.7",
        url="https://github.com/sonic-visualiser/sonic-annotator/releases/download/sonic-annotator-1.7/sonic-annotator-1.7.0-macos.tar.gz",
        sha256="cb54f46af0f6c16b8274998d025019021b3b6c50410b8a8e2024d0aa7e65b040",
        size=10_638_233,
        filename="sonic-annotator-1.7.0-macos.tar.gz",
        kind="tar.gz",
        install_name="sonic-annotator-1.7.0",
    ),
    ("windows", "vamp_plugin_pack"): PinnedToolAsset(
        tool="vamp_plugin_pack",
        platform="windows",
        version="1.0.0",
        url="https://github.com/ThomasTZh/PALM-Practice-Any-Local-Music/releases/download/plugins-win64-v1/vamp-plugins-win64.zip",
        sha256="41475f374966a3d2126c84e0d434fbc774738e427c01b5aeccfd025dfc143863",
        size=1_430_285,
        filename="vamp-plugins-win64.zip",
        kind="zip",
        install_name="vamp-plugins",
    ),
    ("macos", "vamp_plugin_pack"): PinnedToolAsset(
        tool="vamp_plugin_pack",
        platform="macos",
        version="2.0",
        url="https://github.com/vamp-plugins/vamp-plugin-pack/releases/download/v2.0/Vamp.Plugin.Pack.Installer-2.0.dmg",
        sha256="60e2569ab064dbaf9ca8a4c3cf8465298b91ea3be1b34c5395d45c1ca4c53f10",
        size=48_745_081,
        filename="Vamp.Plugin.Pack.Installer-2.0.dmg",
        kind="dmg",
        install_name="vamp-plugins",
    ),
}


def platform_name() -> PlatformName:
    if platform_support.WINDOWS:
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def asset_for(platform: PlatformName, tool: str) -> PinnedToolAsset:
    try:
        return PLATFORM_ASSETS[(platform, tool)]
    except KeyError as error:
        raise SetupInstallError(f"no pinned {tool} asset for {platform}") from error


def _safe_members(names: list[str], destination: Path) -> list[str]:
    root = destination.resolve()
    safe: list[str] = []
    for name in names:
        target = (destination / name).resolve()
        if target != root and root not in target.parents:
            raise SetupInstallError(f"tool archive contains an unsafe path: {name}")
        safe.append(name)
    return safe


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        names = _safe_members(bundle.namelist(), destination)
        bundle.extractall(destination, members=names)


def _extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as bundle:
        names = set(_safe_members(bundle.getnames(), destination))
        members = [member for member in bundle.getmembers() if member.name in names]
        bundle.extractall(destination, members=members, filter="data")


def _find(root: Path, filename: str) -> Path | None:
    return next((path for path in root.rglob(filename) if path.is_file()), None)


def _publish_tree(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    try:
        bundle = staging / "bundle"
        shutil.copytree(source, bundle, symlinks=True)
        if target.exists():
            shutil.rmtree(target)
        bundle.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _verify_archive(asset: PinnedToolAsset, path: Path) -> None:
    if not path.is_file():
        raise SetupInstallError(f"the {asset.filename} download is missing")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.stat().st_size != asset.size or digest != asset.sha256:
        raise SetupInstallError(
            f"{asset.filename} failed size/SHA-256 verification; refusing to extract"
        )


def _download(asset: PinnedToolAsset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    download_verified(
        asset.url,
        path,
        size_bytes=asset.size,
        sha256=asset.sha256,
    )


def standard_vamp_dirs() -> tuple[Path, ...]:
    """Windows' usual Vamp plugin locations, in search order."""
    directories: list[Path] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(key)
        if base:
            directories.append(Path(base) / "Vamp Plugins")
    return tuple(dict.fromkeys(directories))


VAMP_REQUIRED_WINDOWS_DLLS = ("qm-vamp-plugins.dll", "nnls-chroma.dll")
VAMP_REQUIRED_WINDOWS_CATALOGS = ("qm-vamp-plugins.cat", "nnls-chroma.cat")
VAMP_REQUIRED_PLUGIN_IDS = ("qm-keydetector", "chordino", "qm-barbeattracker")
PE32_PLUS_X64 = 0x8664


def _pe_machine(path: Path) -> int:
    """Return the PE COFF machine type, or raise for a non-PE file."""
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        raise SetupInstallError(f"cannot read plugin library {path}: {error}") from error
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise SetupInstallError(f"{path.name} is not a PE library")
    offset = int.from_bytes(data[0x3C:0x40], "little")
    if offset + 6 > len(data) or data[offset : offset + 4] != b"PE\0\0":
        raise SetupInstallError(f"{path.name} has no PE header")
    return int.from_bytes(data[offset + 4 : offset + 6], "little")


def _plugin_ids(listing: str) -> set[str]:
    ids: set[str] = set()
    for line in listing.splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 4 and parts[0] == "vamp":
            ids.add(parts[2])
    return ids


def _verify_windows_plugins(target: Path, runtime: RuntimePaths) -> None:
    sonic = runtime.tools_root / "sonic-annotator-1.7.0" / "sonic-annotator.exe"
    if not sonic.is_file():
        raise SetupInstallError(
            "Sonic Annotator must be installed before the Windows Vamp plugins "
            "can be verified; rerun PALM Setup."
        )
    env = dict(os.environ)
    env["VAMP_PATH"] = str(target)
    try:
        result = subprocess.run(
            [str(sonic), "--list"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            **hidden_process_kwargs(),
        )
    except OSError as error:
        raise SetupInstallError(
            f"could not run Sonic Annotator to verify plugins: {error}"
        ) from error
    if result.returncode != 0:
        raise SetupInstallError(
            "Sonic Annotator could not list the installed Windows Vamp plugins: "
            f"{result.stderr.strip() or result.returncode}"
        )
    missing = sorted(set(VAMP_REQUIRED_PLUGIN_IDS) - _plugin_ids(result.stdout))
    if missing:
        raise SetupInstallError(
            "the Windows Vamp bundle did not expose required plugin ids: " + ", ".join(missing)
        )


def _install_vamp_windows(
    asset: PinnedToolAsset, archive: Path, target: Path, runtime: RuntimePaths
) -> None:
    if not archive.is_file():
        raise SetupInstallError(f"the {asset.filename} download is missing")
    runtime.ensure_data_path(runtime.tools_root)
    staging = Path(tempfile.mkdtemp(prefix=".vamp-windows-", dir=target.parent))
    try:
        extracted = staging / "extracted"
        extracted.mkdir()
        _extract_zip(archive, extracted)
        found: dict[str, Path] = {}
        for filename in (*VAMP_REQUIRED_WINDOWS_DLLS, *VAMP_REQUIRED_WINDOWS_CATALOGS):
            match = _find(extracted, filename)
            if match is None:
                raise SetupInstallError(
                    f"{asset.filename} is missing required Vamp file {filename}"
                )
            found[filename] = match
        for filename in VAMP_REQUIRED_WINDOWS_DLLS:
            machine = _pe_machine(found[filename])
            if machine != PE32_PLUS_X64:
                raise SetupInstallError(
                    f"{filename} is not 64-bit x86-64 (PE machine 0x{machine:04x}); "
                    "the Windows bundle must contain native 64-bit plugins"
                )
        published = staging / "published"
        published.mkdir()
        for filename, source in found.items():
            shutil.copy2(source, published / filename)
        _publish_tree(published, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    _verify_windows_plugins(target, runtime)


def _install_vamp_macos(
    asset: PinnedToolAsset, archive: Path, target: Path, runner: Runner
) -> None:
    target.mkdir(parents=True, exist_ok=True)
    mount = Path(tempfile.mkdtemp(prefix="palm-vamp-dmg-"))
    expanded = Path(tempfile.mkdtemp(prefix="palm-vamp-pkg-"))
    try:
        result = runner(
            ["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(archive)]
        )
        if result is not None and getattr(result, "returncode", 0) not in (0, None):
            raise SetupInstallError(f"hdiutil could not mount {asset.url}")
        package = next(iter(mount.rglob("*.pkg")), None)
        if package is not None:
            expanded_result = runner(["pkgutil", "--expand-full", str(package), str(expanded)])
            if expanded_result is not None and getattr(expanded_result, "returncode", 0) not in (
                0,
                None,
            ):
                raise SetupInstallError(f"pkgutil could not expand {package}")
            source_root = expanded
        else:
            source_root = mount
        binaries = sorted(source_root.rglob(f"*{plugin_suffix()}"))
        if not binaries:
            raise SetupInstallError(
                "the Vamp Plugin Pack DMG contained no plugin libraries; install it "
                "as the current user and retry."
            )
        for binary in binaries:
            shutil.copy2(binary, target / binary.name)
    finally:
        runner(["hdiutil", "detach", str(mount), "-quiet"])
        shutil.rmtree(mount, ignore_errors=True)
        shutil.rmtree(expanded, ignore_errors=True)


def install_sonic_annotator(
    runtime: RuntimePaths,
    *,
    platform: PlatformName | None = None,
    downloader: Downloader | None = None,
) -> Path:
    selected = platform or platform_name()
    asset = asset_for(selected, "sonic_annotator")
    target = runtime.tools_root / asset.install_name
    executable_name = "sonic-annotator.exe" if selected == "windows" else "sonic-annotator"
    executable = target / executable_name
    if executable.is_file():
        return executable
    runtime.ensure_data_path(runtime.tools_root)
    with tempfile.TemporaryDirectory(prefix=".sonic-annotator-", dir=runtime.tools_root) as tmp:
        archive = Path(tmp) / asset.filename
        if downloader is not None:
            downloader(asset, archive)
        else:
            _download(asset, archive)
        _verify_archive(asset, archive)
        extracted = Path(tmp) / "extracted"
        extracted.mkdir()
        if asset.kind == "zip":
            _extract_zip(archive, extracted)
        elif asset.kind == "tar.gz":
            _extract_tar(archive, extracted)
        else:
            raise SetupInstallError(f"unsupported Sonic Annotator archive: {asset.kind}")
        found = _find(extracted, executable_name)
        if found is None:
            raise SetupInstallError(f"{asset.filename} did not contain {executable_name}")
        _publish_tree(found.parent, target)
        executable = target / executable_name
        executable.chmod(executable.stat().st_mode | 0o111)
        return executable


def install_vamp_plugin_pack(
    runtime: RuntimePaths,
    *,
    platform: PlatformName | None = None,
    downloader: Downloader | None = None,
    runner: Runner | None = None,
) -> Path:
    selected = platform or platform_name()
    asset = asset_for(selected, "vamp_plugin_pack")
    target = runtime.tools_root / asset.install_name
    if selected == "windows":
        required = [
            target / name for name in (*VAMP_REQUIRED_WINDOWS_DLLS, *VAMP_REQUIRED_WINDOWS_CATALOGS)
        ]
        if all(path.is_file() for path in required):
            for path in required:
                if path.suffix == ".dll" and _pe_machine(path) != PE32_PLUS_X64:
                    raise SetupInstallError(f"{path.name} is not 64-bit x86-64")
            _verify_windows_plugins(target, runtime)
            return target
    plugin = target / f"qm-vamp-plugins{plugin_suffix()}"
    if selected != "windows" and plugin.is_file():
        return target
    runtime.ensure_data_path(runtime.tools_root)
    run = runner or (
        lambda command: subprocess.run(
            command, capture_output=True, text=True, check=False, **hidden_process_kwargs()
        )
    )
    cache = runtime.tools_root / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / asset.filename
    if downloader is not None:
        downloader(asset, archive)
    else:
        _download(asset, archive)
    _verify_archive(asset, archive)
    if selected == "windows":
        _install_vamp_windows(asset, archive, target, runtime)
    elif selected == "macos":
        _install_vamp_macos(asset, archive, target, run)
    else:
        raise SetupInstallError("Vamp pack platform extraction is only for Windows/macOS")
    if not plugin.is_file():
        raise SetupInstallError(f"Vamp plugin pack did not install {plugin.name} under {target}")
    return target


def install_platform_tools(
    runtime: RuntimePaths,
    *,
    platform: PlatformName | None = None,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
    downloader: Downloader | None = None,
    runner: Runner | None = None,
) -> None:
    selected = platform or platform_name()
    if selected == "linux":
        raise SetupInstallError("use the preserved Linux Piper installer")
    if progress is not None:
        progress(0.05, "installing Sonic Annotator")
    install_sonic_annotator(runtime, platform=selected, downloader=downloader)
    if cancel is not None and cancel():
        raise SetupCancelled("tool installation cancelled")
    if progress is not None:
        progress(0.6, "installing Vamp plugin pack")
    install_vamp_plugin_pack(runtime, platform=selected, downloader=downloader, runner=runner)
    if progress is not None:
        progress(1.0, "tools installed")


__all__ = [
    "PLATFORM_ASSETS",
    "PinnedToolAsset",
    "VAMP_REQUIRED_WINDOWS_CATALOGS",
    "VAMP_REQUIRED_WINDOWS_DLLS",
    "VAMP_REQUIRED_PLUGIN_IDS",
    "asset_for",
    "install_platform_tools",
    "install_sonic_annotator",
    "install_vamp_plugin_pack",
    "platform_name",
]
