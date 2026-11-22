#!/usr/bin/env python3
"""Build the unsigned macOS Apple Silicon experimental PALM.app.

Pinned standalone CPython and uv archives are extracted into the app bundle.
The hashed app runtime is cross-installed for aarch64-apple-darwin on a POSIX
build host (or installed natively on macOS). The ZIP contains only the app,
embedded runtime, built UI, analysis workers/registry/env definitions, launcher
and licences. No FFmpeg, tools, plugins, models, environments or test sources
are bundled.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

try:
    from release_checksums import update_checksums
except ModuleNotFoundError:  # tests load this file directly via importlib
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parent))
    from release_checksums import update_checksums

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "packaging" / "macos" / "build-manifest.toml"
DIST = ROOT / "dist"
CACHE = ROOT / "storage" / "tmp-macos-cache"
FORBIDDEN_ROOT = {
    "models",
    "environments",
    "cache",
    "tests",
    "audio2test",
    "storage",
    ".git",
}
REQUIRED = (
    "PALM.app/Contents/Resources/app/tools/ffmpeg/ffmpeg",
    "PALM.app/Contents/Resources/app/tools/ffmpeg/ffprobe",
    "PALM.app/Contents/Resources/app/tools/sonic-annotator/sonic-annotator",
    "PALM.app/Contents/Resources/app/tools/vamp-plugins/qm-vamp-plugins.dylib",
    "PALM.app/Contents/Resources/app/licenses/bundled-tools/sources/ffmpeg-9.0.2.tar.xz",
    "PALM.app/Contents/MacOS/palm",
    "PALM.app/Contents/Info.plist",
    "PALM.app/Contents/Resources/app/bin/palm",
    "PALM.app/Contents/Resources/app/python/bin/python3.11",
    "PALM.app/Contents/Resources/app/bin/uv",
    "PALM.app/Contents/Resources/app/web/dist/index.html",
    "PALM.app/Contents/Resources/app/analysis/models.json",
    "PALM.app/Contents/Resources/app/analysis/checkpoints.json",
    "PALM.app/Contents/Resources/app/analysis/separate_track.py",
    "PALM.app/Contents/Resources/app/analysis/separate_msst.py",
    "PALM.app/Contents/Resources/app/analysis/envs/cpu-macos/uv.lock",
    "PALM.app/Contents/Resources/app/analysis/envs/msst-macos/uv.lock",
    "PALM.app/Contents/Resources/app/licenses/LICENSE",
    "PALM.app/Contents/Resources/app/licenses/third_party/manifest.json",
    "PALM.app/Contents/Resources/app/install.json",
    "PALM.app/Contents/Resources/app/RELEASE-NOTES.md",
    "PALM.app/Contents/Resources/app/runtime-requirements.txt",
)


class PackageError(RuntimeError):
    pass


def version() -> str:
    return str(tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest() -> dict[str, Any]:
    data = tomllib.loads(MANIFEST.read_text())
    if data.get("schema_version") != 1:
        raise PackageError(f"unsupported macOS manifest {MANIFEST}")
    for key in ("python", "uv"):
        if not data.get(key) or not data[key].get("url") or not data[key].get("sha256"):
            raise PackageError(f"macOS manifest lacks {key}")
    return data


def download(entry: dict[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256(destination) == entry["sha256"]:
        return destination
    part = destination.with_suffix(destination.suffix + ".part")
    print(f"package-macos: downloading {entry['url']}")
    try:
        with (
            urllib.request.urlopen(entry["url"], timeout=180) as response,
            part.open("wb") as out,
        ):
            shutil.copyfileobj(response, out)
    except OSError as error:
        part.unlink(missing_ok=True)
        raise PackageError(f"cannot download {entry['url']}: {error}") from error
    if part.stat().st_size != int(entry.get("size", 0)):
        part.unlink(missing_ok=True)
        raise PackageError(f"{entry['url']} has an unexpected size")
    actual = sha256(part)
    if actual != entry["sha256"]:
        part.unlink(missing_ok=True)
        raise PackageError(f"{entry['url']} has sha256 {actual}")
    part.replace(destination)
    return destination


def extract_python(archive: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    with tempfile.TemporaryDirectory(prefix="palm-mac-python-") as scratch:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(scratch, filter="data")
        roots = [path for path in Path(scratch).iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise PackageError("macOS Python archive did not contain one python tree")
        shutil.copytree(roots[0], destination, symlinks=True)
    if not (destination / "bin" / "python3.11").is_file():
        raise PackageError("embedded macOS Python has no bin/python3.11")


def extract_uv(archive: Path, destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="palm-mac-uv-") as scratch:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(scratch, filter="data")
        binaries = [path for path in Path(scratch).rglob("uv") if path.is_file()]
        if not binaries:
            raise PackageError("macOS uv archive contains no uv binary")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binaries[0], destination)
        destination.chmod(0o755)


def export_requirements(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    if uv is None:
        raise PackageError("uv is required to export the runtime lock")
    result = subprocess.run(
        [
            uv,
            "export",
            "--project",
            str(ROOT / "packaging" / "app-runtime"),
            "--locked",
            "--no-header",
            "--format",
            "requirements.txt",
            "--output-file",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "UV_CACHE_DIR": str(CACHE / "uv")},
    )
    if result.returncode != 0:
        raise PackageError(f"cannot export runtime requirements: {result.stderr.strip()}")


def install_runtime(app: Path, requirements: Path) -> None:
    python = app / "python" / "bin" / "python3.11"
    target = app / "python" / "lib" / "python3.11" / "site-packages"
    target.mkdir(parents=True, exist_ok=True)
    uv = app / "bin" / "uv"
    if sys.platform == "darwin":
        command = [
            str(uv),
            "pip",
            "install",
            "--python",
            str(python),
            "--require-hashes",
            "--requirement",
            str(requirements),
            "--no-config",
        ]
    else:
        host_uv = shutil.which("uv")
        if host_uv is None:
            raise PackageError("uv is required for a cross-platform macOS build")
        command = [
            host_uv,
            "pip",
            "install",
            "--target",
            str(target),
            "--python-platform",
            "aarch64-apple-darwin",
            "--python-version",
            "3.11",
            "--only-binary",
            ":all:",
            "--require-hashes",
            "--requirement",
            str(requirements),
            "--no-config",
        ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "UV_CACHE_DIR": str(CACHE / "uv")},
    )
    if result.returncode != 0:
        raise PackageError(f"macOS runtime install failed: {result.stderr.strip()}")


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise PackageError(f"missing staging input {source}")
    shutil.copytree(
        source,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".mypy_cache", ".ruff_cache"),
    )


def copy_file(source: Path, destination: Path, *, executable: bool = False) -> None:
    if not source.is_file():
        raise PackageError(f"missing staging input {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if executable:
        destination.chmod(0o755)


def clean_bytecode(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.name == "__pycache__" and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.suffix == ".pyc" and path.is_file():
            path.unlink(missing_ok=True)


def stage(stage_root: Path, data: dict[str, Any], requirements: Path, *, online: bool) -> Path:
    if not (ROOT / "web" / "dist" / "index.html").is_file():
        raise PackageError("web/dist/index.html is missing; run make build-web first")
    python_archive = CACHE / f"python-{data['python']['version']}.tar.gz"
    uv_archive = CACHE / "uv-macos.tar.gz"
    if online:
        download(data["python"], python_archive)
        download(data["uv"], uv_archive)
    elif not (python_archive.is_file() and uv_archive.is_file()):
        raise PackageError("macOS archives are not cached; run with --online")
    bundle = stage_root / "PALM.app"
    copy_tree(ROOT / "packaging" / "macos" / "PALM.app", bundle)
    app = bundle / "Contents" / "Resources" / "app"
    app.mkdir(parents=True, exist_ok=True)
    extract_python(python_archive, app / "python")
    extract_uv(uv_archive, app / "bin" / "uv")
    copy_file(ROOT / "packaging" / "launcher" / "palm", app / "bin" / "palm", executable=True)
    copy_tree(ROOT / "src" / "basseparate", app / "src" / "basseparate")
    copy_tree(ROOT / "web" / "dist", app / "web" / "dist")
    for name in (
        "models.json",
        "checkpoints.json",
        "separate_track.py",
        "separate_msst.py",
        "pyproject.toml",
        "uv.lock",
    ):
        copy_file(ROOT / "analysis" / name, app / "analysis" / name)
    for name in ("cpu-macos", "msst-macos"):
        copy_tree(ROOT / "analysis" / "envs" / name, app / "analysis" / "envs" / name)
    copy_file(ROOT / "analysis" / "envs" / "cpu.json", app / "analysis" / "envs" / "cpu.json")
    copy_file(ROOT / "analysis" / "envs" / "cuda.json", app / "analysis" / "envs" / "cuda.json")
    copy_file(ROOT / "scripts" / "install_tools.py", app / "scripts" / "install_tools.py")
    for name in ("LICENSE", "NOTICES.md", "components.json"):
        copy_file(ROOT / "licenses" / name, app / "licenses" / name)
    copy_tree(ROOT / "licenses" / "third_party", app / "licenses" / "third_party")
    write_install_json(app / "install.json", "macos-arm64", version())
    copy_file(ROOT / "README.md", app / "README.md")
    copy_file(ROOT / "packaging" / "release-notes.md", app / "RELEASE-NOTES.md")
    copy_file(requirements, app / "runtime-requirements.txt")
    copy_file(ROOT / "packaging" / "macos" / "build-manifest.toml", app / "BUILD-MANIFEST.toml")
    install_runtime(app, requirements)
    clean_bytecode(app)
    return bundle


def forbidden(name: str) -> bool:
    parts = Path(name).parts
    if "__pycache__" in parts or name.endswith(".pyc") or ".git" in parts:
        return True
    marker = ("PALM.app", "Contents", "Resources", "app")
    if len(parts) > len(marker) and tuple(parts[:4]) == marker:
        return parts[4].lower() in FORBIDDEN_ROOT
    return len(parts) >= 2 and parts[1].lower() in FORBIDDEN_ROOT


def check_zip(path: Path) -> int:
    if not path.is_file():
        raise PackageError(f"missing ZIP {path}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    for required in REQUIRED:
        if not any(name == required or name.endswith("/" + required) for name in names):
            raise PackageError(f"ZIP is missing {required}")
    bad = [name for name in names if forbidden(name)]
    if bad:
        raise PackageError(f"ZIP contains excluded paths: {bad[:5]}")
    print(f"package-macos-check: {len(names)} entries, required content present")
    return 0


def write_install_json(destination: Path, channel: str, version_value: str) -> None:
    import json

    mapping = json.loads((ROOT / "packaging" / "install.json").read_text(encoding="utf-8"))
    spec = mapping["channels"][channel]
    asset = str(spec["asset"]).format(version=version_value)
    destination.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "channel": channel,
                "version": version_value,
                "assets": {
                    channel: {
                        "name": asset,
                        "kind": spec["kind"],
                        "version": version_value,
                        "url": f"https://github.com/ThomasTZh/PALM-Practice-Any-Local-Music/releases/download/v{version_value}/{asset}",
                        "sha256": "",
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


MAC_BUNDLED = ROOT / "storage" / "bundled-tools" / "macos"


def stage_bundled_tools(app: Path) -> None:
    """Stage the approved macOS media/analysis payload."""
    if not (MAC_BUNDLED / "ffmpeg").is_file() or not (MAC_BUNDLED / "ffprobe").is_file():
        raise PackageError("macOS bundled FFmpeg/FFprobe are missing")
    tools = app / "tools"
    (tools / "ffmpeg").mkdir(parents=True, exist_ok=True)
    copy_file(MAC_BUNDLED / "ffmpeg", tools / "ffmpeg" / "ffmpeg", executable=True)
    copy_file(MAC_BUNDLED / "ffprobe", tools / "ffmpeg" / "ffprobe", executable=True)
    sonic_tar = MAC_BUNDLED / "sonic-annotator-1.7.0-macos.tar.gz"
    if not sonic_tar.is_file():
        raise PackageError("macOS Sonic Annotator archive is missing")
    with tarfile.open(sonic_tar, "r:gz") as archive:
        archive.extractall(tools / "sonic-annotator", filter="data")
    root = next(p for p in (tools / "sonic-annotator").iterdir() if p.is_dir())
    for item in list(root.iterdir()):
        item.rename(tools / "sonic-annotator" / item.name)
    root.rmdir()
    plugin_zip = MAC_BUNDLED / "vamp-plugins-macos-arm64.zip"
    if not plugin_zip.is_file():
        raise PackageError("macOS Vamp plugin bundle is missing")
    plugins = tools / "vamp-plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(plugin_zip) as archive:
        for name in archive.namelist():
            if name.endswith("/") or "/" in name:
                continue
            with archive.open(name) as source, (plugins / name).open("wb") as out:
                shutil.copyfileobj(source, out)
    copy_tree(MAC_BUNDLED / "licenses", app / "licenses" / "bundled-tools")
    copy_tree(MAC_BUNDLED / "sources", app / "licenses" / "bundled-tools" / "sources")
    for dylib in plugins.glob("*.dylib"):
        dylib.chmod(0o755)


def build_zip(bundle_parent: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(bundle_parent.rglob("*")):
            relative = path.relative_to(bundle_parent).as_posix()
            if path.is_file():
                info = zipfile.ZipInfo(relative)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                # ZipInfo defaults lose Unix modes. Record the file mode in the
                # high 16 bits and mark the entry as Unix (create_system=3) so
                # Contents/MacOS/palm, bin/palm, bin/uv and the embedded Python
                # stay executable after extraction.
                mode = stat.S_IMODE(path.stat().st_mode)
                if not mode & 0o111:
                    mode = 0o644
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | mode) << 16
                archive.writestr(info, path.read_bytes())
    print(f"package-macos: wrote {output} ({output.stat().st_size} bytes)")
    return output


def write_checksums(output_dir: Path, version_value: str) -> Path:
    """Merge ZIP/DMG basenames into the shared SHA256SUMS manifest."""
    files = sorted(
        path
        for path in output_dir.glob(f"PALM-{version_value}-macos-arm64.*")
        if path.suffix in {".zip", ".dmg"}
    )
    if not files:
        raise PackageError(f"no macOS artifacts found in {output_dir}")
    checksums = update_checksums(output_dir, files)
    print(f"package-macos: wrote {checksums} ({len(files)} mac entries)")
    return checksums


def build_dmg(bundle: Path, output: Path) -> Path | None:
    """Create a drag-to-Applications DMG containing PALM.app and /Applications.

    The app is unsigned and not notarized; this is not an installer package.
    """
    if sys.platform != "darwin":
        print("package-macos: DMG skipped (hdiutil is macOS-only)")
        return None
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="palm-dmg-", dir=output.parent) as scratch:
        root = Path(scratch) / "PALM"
        root.mkdir()
        shutil.copytree(bundle, root / bundle.name, symlinks=True)
        (root / "Applications").symlink_to("/Applications", target_is_directory=True)
        result = subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                "PALM",
                "-srcfolder",
                str(root),
                "-ov",
                "-format",
                "UDZO",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        raise PackageError(f"hdiutil failed: {result.stderr.strip()}")
    return output


def build(args: argparse.Namespace) -> int:
    data = manifest()
    version_value = version()
    output_dir = Path(args.output).resolve()
    stage_root = output_dir / f"palm-{version_value}-macos-arm64"
    if stage_root.exists():
        shutil.rmtree(stage_root)
    stage_root.mkdir(parents=True)
    requirements = output_dir / "runtime-requirements.txt"
    export_requirements(requirements)
    try:
        bundle = stage(stage_root, data, requirements, online=args.online)
        stage_bundled_tools(bundle / "Contents" / "Resources" / "app")
        zip_path = build_zip(stage_root, output_dir / f"PALM-{version_value}-macos-arm64.zip")
        check_zip(zip_path)
        if args.dmg:
            build_dmg(bundle, output_dir / f"PALM-{version_value}-macos-arm64.dmg")
        write_checksums(output_dir, version_value)
        return 0
    except (PackageError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"package-macos: {error}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DIST))
    parser.add_argument(
        "--online", action="store_true", help="download pinned macOS Python/uv archives"
    )
    parser.add_argument("--dmg", action="store_true", help="also create a DMG on macOS")
    parser.add_argument("--check", action="store_true", help="validate an existing ZIP")
    args = parser.parse_args(argv)
    if args.check:
        zips = sorted(Path(args.output).glob("PALM-*-macos-arm64.zip"))
        if not zips:
            print("package-macos-check: no ZIP found", file=sys.stderr)
            return 1
        try:
            return check_zip(zips[-1])
        except (PackageError, OSError, zipfile.BadZipFile) as error:
            print(f"package-macos-check: {error}", file=sys.stderr)
            return 1
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
