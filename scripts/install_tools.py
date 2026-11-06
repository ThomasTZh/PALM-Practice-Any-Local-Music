#!/usr/bin/env python3
"""Install the external tools that basseparate does not redistribute.

The script only downloads files from their official release channels, verifies
every byte against a pinned SHA-256 value, and writes them below the ignored
``storage/`` and ``models/`` directories. It never copies third-party files
into git and never claims that the project's MIT licence covers them.

Run ``python scripts/install_tools.py --help`` for the options.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "storage" / "tools"
SV_DIR = TOOLS / "sv"
PLUGIN_DIR = TOOLS / "plugins"
NATIVE_PLUGIN_DIR = TOOLS / "vamp-plugins"
MODEL_DIR = ROOT / "models" / "htdemucs_ft"
CHECKPOINTS = ROOT / "analysis" / "checkpoints.json"

SV_VERSION = "5.2.1"
SV_URL = (
    "https://github.com/sonic-visualiser/sonic-visualiser/releases/download/"
    f"sv_v{SV_VERSION}/SonicVisualiser-{SV_VERSION}-x86_64.AppImage"
)
SV_SHA256 = "e31e7b970db7a9d6e5943c050c0a06c193d2c3fd4a82b6283aa08a9dc798599c"

PACK_VERSION = "2.0"
PACK_URL = (
    "https://github.com/vamp-plugins/vamp-plugin-pack/releases/download/"
    f"v{PACK_VERSION}/vamp-plugin-pack-installer-{PACK_VERSION}"
)
PACK_SHA256 = "e8ed873f6e7dbdf8e11e61bd2fbc54f63469ff7c4a449c25a0fa14b52c42126f"
PACK_LICENSE = "AGPL-3.0 (pack); individual plugins GPL/AGPL"

PRESET_URL = (
    "https://raw.githubusercontent.com/facebookresearch/demucs/"
    "b1ea86542ca11d7695cba4238909f461752283b5/demucs/remote/htdemucs_ft.yaml"
)
PRESET_NAME = "htdemucs_ft.yaml"
PRESET_SHA256 = "69470b8c1bbd674437b51bc9fb491327a10ab0396b702c93389b9cf750016346"
PRESET_SIZE = 149
MODEL_BASE_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/"
MODEL_TERMS = (
    "The Demucs code is MIT, but the pretrained htdemucs_ft weights are not "
    "covered by that grant. The upstream author has described them as research "
    "use, and the training data includes MUSDB18-HQ, which is a research corpus. "
    "This installer downloads them from Meta's public release at your request; "
    "it does not redistribute them and does not claim a licence for them."
)


@dataclass(frozen=True)
class PluginBlob:
    index: int
    offset: int
    size: int
    sha256: str


# Carved from the verified Vamp Plugin Pack 2.0 Linux AppImage. The pack
# installer embeds these shared libraries; the offsets and hashes are pins.
PLUGIN_BLOBS: tuple[PluginBlob, ...] = (
    PluginBlob(
        1, 986211, 305216, "e077f871df96f49323816f85f2ea57c1dfb5ee801fdc10fe411be19944358021"
    ),
    PluginBlob(
        2, 1291431, 163672, "05caf41777c4a68a4b53a0ae2e32de72926bf0891ea5c48d043d76aa6a42e46d"
    ),
    PluginBlob(
        3, 1459512, 940176, "d60b960a093b18eb727b2543a138780ca63ce8b316177c8f07debdafde5e5b68"
    ),
    PluginBlob(
        4, 2401252, 6154816, "dbf62ff76c987cfd5604a6ce5cdd25d8d43b0cf320a9db6b2c66bb8c862a59a2"
    ),
    PluginBlob(
        5, 8559277, 173352, "d3bc6d96fe15ad4aee072751abee90be45758842d583aec7c447ef50280e0c4f"
    ),
    PluginBlob(
        6, 8751718, 136408, "b78e3f4d509a259344363f9b0c3d849df5195d9dbf663bf8f4009c01034d182b"
    ),
    PluginBlob(
        7, 8888130, 347672, "2908cb28c59c01330efd1bcb13300c7567b995d867e5ec796b55de5830e564ed"
    ),
    PluginBlob(
        8, 9260481, 120768, "a70fe4e92a9f1024440b23085a3094e3ef7aa5d50eb6574f483b365a5f7995f7"
    ),
    PluginBlob(
        9, 9391429, 302848, "f0a35d34d9527402a7c501a616fbac6f14ffb25602413008c3f26141fcdf5098"
    ),
    PluginBlob(
        10, 9709416, 312080, "a8a539d77b0daf6189bfc3cef5e17af96c55cf356f3f36c0ee551b8ac6a9452e"
    ),
    PluginBlob(
        11, 10054364, 270136, "9a39f318b503adafe319209624ae76bc82ba54112019e7cf64d8102397b135ea"
    ),
    PluginBlob(
        12, 10378903, 928616, "f666669739f9645d84909f2c36f3bd2c5a60822dbd9804ac0daa316ab21c7275"
    ),
    PluginBlob(
        13, 11309252, 231264, "29a0f1bd6b5ff44d493af165cf53cd3b929830f31d9aee16e3b838caa2846017"
    ),
    PluginBlob(
        14, 12329802, 411888, "6e5838e4b2d036ce62a0a2dc218425b5a8b51730e62ed5ec31b968a3476cf30f"
    ),
    PluginBlob(
        15, 12830010, 185152, "3744f3b07a46838868cf0ff4efd1d843a9feeea0d622ace630890fbc7b3ea06f"
    ),
    PluginBlob(
        16, 13015166, 3083352, "cbd10f5d08dee747d6006720458f4596e1ec023f9b8b0faa8e97ed5a65d38519"
    ),
    PluginBlob(
        17, 16105237, 218144, "fadbb323ef3674d079991ac941caf89f41a53d17956869cffe1531435371533d"
    ),
    PluginBlob(
        18, 16341429, 475496, "0ca29396c44d6bfa581775f54be6831e9c31129ca14d14fb392dfaced0760cfc"
    ),
    PluginBlob(
        19, 16816929, 257080, "c93254f98c17973261b14cc3e32532131de3b36005b9c94b5e6f09df4da36117"
    ),
    PluginBlob(
        20, 17074013, 370480, "3d3b9bb9c75624b44185fa555c9dd92f00541f3abe9880d326c73c2061219b41"
    ),
    PluginBlob(
        21, 17463057, 230304, "0e9a9eacd99676a3fa7351c8d4a8fdf1870fef285475696abcabe805e4e0b51d"
    ),
    PluginBlob(
        22, 17698945, 172480, "b9f8dea7993a13c389dd1da05fc1989dbcb957b85fa3564127adbf5eb614679b"
    ),
    PluginBlob(
        23, 17871429, 285464, "a38a2cb04ca28d4f710f162e99abecbacbfdcabcaf3f36c1b18202d753fed762"
    ),
)

# The three libraries the application needs, as carved names.
CHORDINO = "embed-07-8888130.so"
KEY_AND_BEAT = "embed-12-10378903.so"
BEATROOT = "embed-02-1291431.so"


class InstallError(RuntimeError):
    """A failed check, download, verification or extraction."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify(path: Path, expected_sha: str, expected_size: int | None = None) -> None:
    if expected_size is not None and path.stat().st_size != expected_size:
        raise InstallError(
            f"size mismatch for {path}: expected {expected_size}, got {path.stat().st_size}"
        )
    actual = _sha256_file(path)
    if actual != expected_sha:
        raise InstallError(f"checksum mismatch for {path}: expected {expected_sha}, got {actual}")


def _download(url: str, destination: Path, expected_sha: str, size: int | None = None) -> None:
    if not url.startswith("https://"):
        raise InstallError(f"refusing non-HTTPS download: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "basseparate-installer/1"})
        with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                handle.write(chunk)
        actual = digest.hexdigest()
        if actual != expected_sha:
            raise InstallError(
                f"checksum mismatch for {url}: expected {expected_sha}, got {actual}"
            )
        if size is not None and part.stat().st_size != size:
            raise InstallError(
                f"size mismatch for {url}: expected {size}, got {part.stat().st_size}"
            )
        part.replace(destination)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        part.unlink(missing_ok=True)
        raise InstallError(f"download failed for {url}: {error}") from error
    except InstallError:
        part.unlink(missing_ok=True)
        raise


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _tool_version(command: str, args: tuple[str, ...]) -> str | None:
    if shutil.which(command) is None:
        return None
    result = _run([command, *args])
    if result.returncode != 0:
        return None
    return (result.stdout or result.stderr).strip().splitlines()[0]


def _distro_hint() -> str:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return "install FFmpeg with your distribution package manager"
    fields = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value.strip().strip('"')
    distro = fields.get("ID", "").lower()
    if distro in {"fedora", "nobara", "rhel", "centos"}:
        return "sudo dnf install ffmpeg"
    if distro in {"debian", "ubuntu", "linuxmint", "pop"}:
        return "sudo apt install ffmpeg"
    if distro in {"arch", "manjaro", "endeavouros"}:
        return "sudo pacman -S ffmpeg"
    return "install FFmpeg with your distribution package manager"


def check_environment() -> list[str]:
    """Return the problems that prevent a complete setup."""
    problems: list[str] = []
    print("[checks]")
    if platform.system() != "Linux":
        problems.append("Linux is the supported platform for the packaged tools")
        print(f"  FAIL  OS: {platform.system()} (Linux expected)")
    else:
        print(f"  ok    OS: {platform.system()} ({platform.release()})")

    version = sys.version_info
    if version < (3, 11):
        problems.append("Python 3.11 or newer is required")
        print(f"  FAIL  Python: {version.major}.{version.minor}")
    else:
        print(f"  ok    Python: {version.major}.{version.minor}.{version.micro}")

    for command, args, label in (
        ("node", ("--version",), "Node.js 22 or newer"),
        ("uv", ("--version",), "uv"),
        ("pnpm", ("--version",), "pnpm"),
        ("ffmpeg", ("-version",), "FFmpeg"),
        ("ffprobe", ("-version",), "FFprobe"),
        ("make", ("--version",), "make"),
    ):
        found = _tool_version(command, args)
        if found is None:
            print(f"  FAIL  {label}: not found")
            if command in {"ffmpeg", "ffprobe"}:
                print(f"        hint: {_distro_hint()}")
            elif command == "node":
                print("        hint: install Node.js from https://nodejs.org/")
            elif command == "pnpm":
                print("        hint: install pnpm from https://pnpm.io/installation")
            elif command == "uv":
                print("        hint: install uv from https://docs.astral.sh/uv/")
            problems.append(f"{label} is missing")
        else:
            print(f"  ok    {label}: {found.splitlines()[0]}")

    if shutil.which("node"):
        node_version = _tool_version("node", ("--version",)) or ""
        try:
            if int(node_version.lstrip("v").split(".")[0]) < 22:
                print("  warn  Node.js 22 or newer is recommended")
        except ValueError:
            pass

    app_python = ROOT / ".venv" / "bin" / "python"
    analysis_python = ROOT / "analysis" / ".venv" / "bin" / "python"
    if not app_python.is_file():
        problems.append("application environment missing")
        print("  FAIL  .venv: run `uv sync`")
    else:
        print("  ok    .venv")
    if not analysis_python.is_file():
        problems.append("analysis environment missing")
        print("  FAIL  analysis/.venv: run `(cd analysis && uv sync)`")
    else:
        print("  ok    analysis/.venv")

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for entry in ("/models/", "/storage/", "audio2test/"):
        if entry not in gitignore:
            problems.append(f".gitignore does not exclude {entry}")
            print(f"  FAIL  .gitignore: missing {entry}")
    if not any(item.startswith(".gitignore") for item in problems):
        print("  ok    .gitignore excludes model, tool and recording directories")
    return problems


def _appimage_extract(appimage: Path, destination: Path) -> Path:
    """Extract an AppImage into destination and return the squashfs root."""
    appimage.chmod(0o755)
    result = _run([str(appimage), "--appimage-extract"], cwd=destination)
    if result.returncode != 0:
        raise InstallError(
            "AppImage extraction failed: "
            + (result.stderr.strip() or result.stdout.strip() or "unknown error")
        )
    root = destination / "squashfs-root"
    if not root.is_dir():
        raise InstallError(f"AppImage did not produce {root}")
    return root


def install_sonic_visualiser(*, force: bool) -> None:
    piper = SV_DIR / "squashfs-root" / "usr" / "bin" / "piper-vamp-simple-server"
    if piper.is_file() and os.access(piper, os.X_OK) and not force:
        print(f"[tools] Sonic Visualiser already present: {piper}")
        return
    if SV_DIR.exists() and not force:
        raise InstallError(
            f"{SV_DIR} exists but Piper is missing; rerun with --force to replace it"
        )
    print(f"[tools] downloading Sonic Visualiser {SV_VERSION} (pinned SHA-256)")
    with tempfile.TemporaryDirectory(prefix="basseparate-sv-", dir=TOOLS) as scratch:
        work = Path(scratch)
        appimage = work / "SonicVisualiser.AppImage"
        _download(SV_URL, appimage, SV_SHA256)
        root = _appimage_extract(appimage, work)
        piper = root / "usr" / "bin" / "piper-vamp-simple-server"
        if not piper.is_file():
            raise InstallError("the Sonic Visualiser release does not contain Piper")
        piper.chmod(0o755)
        if SV_DIR.exists():
            shutil.rmtree(SV_DIR)
        SV_DIR.mkdir(parents=True)
        shutil.copytree(root, SV_DIR / "squashfs-root", symlinks=True)
    print(f"[tools] installed Sonic Visualiser into {SV_DIR}")


def elf_extent(data: bytes, offset: int) -> int:
    """Return the file size of the ELF image that starts at offset."""
    if data[offset : offset + 4] != b"\x7fELF":
        raise InstallError(f"no ELF image at offset {offset}")
    if data[offset + 4] != 2 or data[offset + 5] != 1:
        raise InstallError(f"unsupported ELF class at offset {offset}")

    def u16(position: int) -> int:
        return struct.unpack_from("<H", data, position)[0]

    def u64(position: int) -> int:
        return struct.unpack_from("<Q", data, position)[0]

    section_end = offset + u64(offset + 0x28) + u16(offset + 0x3A) * u16(offset + 0x3C)
    program_end = 0
    for index in range(u16(offset + 0x38)):
        base = offset + u64(offset + 0x20) + index * u16(offset + 0x36)
        program_end = max(program_end, offset + u64(base + 0x08) + u64(base + 0x20))
    size = max(section_end, program_end) - offset
    if size <= 0 or offset + size > len(data):
        raise InstallError(f"invalid ELF extent at offset {offset}")
    return size


def _required_plugin_names() -> dict[str, str]:
    return {
        CHORDINO: "nnls-chroma.so",
        KEY_AND_BEAT: "qm-vamp-plugins.so",
        BEATROOT: "beatroot-vamp.so",
    }


def install_plugin_pack(*, force: bool) -> None:
    required = _required_plugin_names()
    current_ok = all(
        (PLUGIN_DIR / carved).is_file() and _sha256_file(PLUGIN_DIR / carved) == _blob_hash(carved)
        for carved in required
    )
    if current_ok and not force:
        print(f"[tools] Vamp plugin pack already present: {PLUGIN_DIR}")
        return
    print(f"[tools] downloading Vamp Plugin Pack {PACK_VERSION} (pinned SHA-256)")
    with tempfile.TemporaryDirectory(prefix="basseparate-pack-", dir=TOOLS) as scratch:
        work = Path(scratch)
        appimage = work / "vamp-plugin-pack.AppImage"
        _download(PACK_URL, appimage, PACK_SHA256)
        root = _appimage_extract(appimage, work)
        installer = root / "usr" / "bin" / "vamp-plugin-pack-installer"
        if not installer.is_file():
            raise InstallError("the Vamp Plugin Pack release does not contain its installer")
        data = installer.read_bytes()
        offsets = []
        position = 1
        while True:
            found = data.find(b"\x7fELF", position)
            if found < 0:
                break
            offsets.append(found)
            position = found + 4
        if len(offsets) != len(PLUGIN_BLOBS):
            raise InstallError(
                f"unexpected pack layout: found {len(offsets)} ELF images, "
                f"expected {len(PLUGIN_BLOBS)}"
            )
        PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
        NATIVE_PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
        for blob, offset in zip(PLUGIN_BLOBS, offsets, strict=True):
            size = elf_extent(data, offset)
            carved = data[offset : offset + size]
            if _sha256_bytes(carved) != blob.sha256 or size != blob.size:
                raise InstallError(f"plugin {blob.index} does not match the pinned release")
            name = f"embed-{blob.index:02d}-{blob.offset}.so"
            target = PLUGIN_DIR / name
            target.write_bytes(carved)
            target.chmod(0o755)
        for carved, alias in _required_plugin_names().items():
            source = PLUGIN_DIR / carved
            destination = NATIVE_PLUGIN_DIR / alias
            destination.write_bytes(source.read_bytes())
            destination.chmod(0o644)
    print(f"[tools] installed {len(PLUGIN_BLOBS)} Vamp plugin libraries into {PLUGIN_DIR}")


def _blob_hash(name: str) -> str:
    for blob in PLUGIN_BLOBS:
        if name == f"embed-{blob.index:02d}-{blob.offset}.so":
            return blob.sha256
    raise InstallError(f"unknown plugin {name}")


def _model_manifest() -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    data = json.loads(CHECKPOINTS.read_text(encoding="utf-8"))
    return data["checkpoints"], data


def model_is_complete() -> bool:
    checkpoints, _ = _model_manifest()
    if not MODEL_DIR.is_dir():
        return False
    for name, record in checkpoints.items():
        path = MODEL_DIR / name
        if not path.is_file():
            return False
        if path.stat().st_size != int(record["size_bytes"]):
            return False
        if _sha256_file(path) != str(record["sha256"]):
            return False
    preset = MODEL_DIR / PRESET_NAME
    return (
        preset.is_file()
        and preset.stat().st_size == PRESET_SIZE
        and _sha256_file(preset) == PRESET_SHA256
    )


def install_model(*, accept_terms: bool, force: bool) -> bool:
    """Compatibility wrapper over the equal model installer."""
    print("[model]")
    print(MODEL_TERMS)
    if model_is_complete() and not force:
        print(f"[model] already installed and verified: {MODEL_DIR}")
        return True
    if not accept_terms:
        if sys.stdin.isatty():
            answer = input(
                "Type 'accept' to download the weights for research use, or press Enter to skip: "
            ).strip()
            accept_terms = answer == "accept"
        if not accept_terms:
            print("[model] skipped; rerun with --accept-model-terms to download")
            return False
    from basseparate.config import RuntimePaths
    from basseparate.setup.models import install_models

    runtime = RuntimePaths.from_environment(mode="source", app_root=ROOT, data_root=ROOT)
    states = install_models(["htdemucs_ft"], runtime=runtime, force=force, progress=lambda *_: None)
    if not all(state.installed for state in states):
        raise InstallError("model verification failed after download")
    print(f"[model] installed and verified: {MODEL_DIR}")
    return True


def run_doctor() -> int:
    if shutil.which("make") is None:
        print("[doctor] make not found; skipping")
        return 1
    print("[doctor] make doctor")
    result = subprocess.run(["make", "doctor"], cwd=ROOT, check=False)
    return result.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--accept-model-terms", action="store_true", help="download the Demucs weights"
    )
    parser.add_argument(
        "--skip-tools", action="store_true", help="do not fetch the Vamp/Piper tools"
    )
    parser.add_argument("--skip-model", action="store_true", help="do not fetch the Demucs weights")
    parser.add_argument("--skip-doctor", action="store_true", help="do not run make doctor")
    parser.add_argument(
        "--force", action="store_true", help="re-download and replace existing files"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    TOOLS.mkdir(parents=True, exist_ok=True)
    print(
        "[licences] Sonic Visualiser is GPL-2.0-or-later and the Vamp Plugin "
        "Pack is AGPL-3.0 with individual plugins under GPL/AGPL; they stay "
        "under those licences and are not bundled or relicensed here."
    )
    problems = check_environment()
    try:
        if not args.skip_tools:
            install_sonic_visualiser(force=args.force)
            install_plugin_pack(force=args.force)
        if not args.skip_model:
            install_model(accept_terms=args.accept_model_terms, force=args.force)
    except InstallError as error:
        print(f"install-tools: {error}", file=sys.stderr)
        return 1
    if problems:
        print("[summary] setup is incomplete:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
    if not args.skip_doctor:
        doctor_code = run_doctor()
        if doctor_code != 0:
            print("[doctor] reported missing or failing components", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
