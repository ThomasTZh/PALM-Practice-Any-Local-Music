#!/usr/bin/env python3
"""Build and validate the portable PALM release.

The local build is offline: it uses the preserved standalone CPython and the
already-installed app runtime, while still recording the pinned python-build-
standalone/uv/appimagetool manifest and exporting a hashed runtime lock. CI
runs `--online`, downloads only the pinned tools, and installs the runtime from
the hashed lock into the bundled interpreter.

No model weights, analysis environments, tools, caches, tests, recordings or
.git data are copied into the release.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
CACHE = ROOT / "storage" / "tmp-package-cache"
MAX_ASSET_BYTES = 2 * 1024**3
FORBIDDEN_ROOT_ENTRIES = {
    ".git",
    ".venv",
    "node_modules",
    "tests",
    "audio2test",
    "models",
    "tools",
    "cache",
    "storage",
}
REQUIRED_TAR_PARTS = (
    "bin/palm",
    "bin/uv",
    "web/dist/index.html",
    "src/basseparate/launcher.py",
    "analysis/models.json",
    "analysis/uv.lock",
    "analysis-models/uv.lock",
    "licenses/LICENSE",
    "palm.desktop",
    "palm.svg",
    "runtime-requirements.txt",
)


class PackageError(RuntimeError):
    """A packaging step failed with a user-facing message."""


@dataclass(frozen=True)
class PinnedAsset:
    version: str
    url: str
    sha256: str
    size: int
    dest: str
    optional: bool = False


def version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest() -> dict[str, Any]:
    path = ROOT / "packaging" / "build-manifest.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if int(data.get("schema_version", 0)) != 1:
        raise PackageError(f"unsupported build manifest at {path}")
    for key in ("python", "uv", "appimagetool"):
        entry = data.get(key)
        if not isinstance(entry, dict) or not entry.get("url") or not entry.get("sha256"):
            raise PackageError(f"build manifest is missing the pinned {key} URL/sha256")
    return data


def pinned(data: dict[str, Any], key: str) -> PinnedAsset:
    entry = data[key]
    return PinnedAsset(
        version=str(entry.get("version", "")),
        url=str(entry["url"]),
        sha256=str(entry["sha256"]),
        size=int(entry.get("size", 0)),
        dest=str(entry.get("dest", key)),
        optional=bool(entry.get("optional", False)),
    )


def download(asset: PinnedAsset, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256(destination) == asset.sha256:
        return
    temporary = destination.with_suffix(destination.suffix + ".part")
    print(f"package: downloading {asset.url}")
    try:
        with (
            urllib.request.urlopen(asset.url, timeout=120) as response,
            temporary.open("wb") as out,
        ):
            shutil.copyfileobj(response, out)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise PackageError(f"cannot download {asset.url}: {error}") from error
    if asset.size and temporary.stat().st_size != asset.size:
        temporary.unlink(missing_ok=True)
        raise PackageError(f"downloaded {asset.url} has the wrong size")
    actual = sha256(temporary)
    if actual != asset.sha256:
        temporary.unlink(missing_ok=True)
        raise PackageError(f"downloaded {asset.url} has sha256 {actual}, expected {asset.sha256}")
    temporary.replace(destination)


def find_cached_python(expected: PinnedAsset) -> Path:
    configured = os.environ.get("PALM_BUILD_PYTHON")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    uv_python = Path.home() / ".local" / "share" / "uv" / "python"
    if uv_python.is_dir():
        candidates.extend(sorted(uv_python.glob("cpython-3.11*-linux-x86_64-gnu")))
    for candidate in candidates:
        binary = candidate / "bin" / "python3.11"
        if binary.is_file():
            result = subprocess.run(
                [str(binary), "-c", "import sys; print(sys.version_info[:2])"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip() == "(3, 11)":
                return candidate
    raise PackageError(
        "no cached Python 3.11 found; set PALM_BUILD_PYTHON or run with --online "
        f"(manifest pins {expected.url})"
    )


def uv_environment() -> dict[str, str]:
    environment = dict(os.environ)
    if not environment.get("UV_CACHE_DIR"):
        cache = ROOT / "storage" / "tmp-uv-lock-cache"
        cache.mkdir(parents=True, exist_ok=True)
        environment["UV_CACHE_DIR"] = str(cache)
    return environment


def find_uv() -> Path | None:
    configured = os.environ.get("PALM_BUILD_UV")
    if configured and Path(configured).is_file():
        return Path(configured)
    found = shutil.which("uv")
    return Path(found) if found else None


def resolve_uv(manifest: dict[str, Any], *, online: bool) -> Path:
    existing = find_uv()
    if existing is not None:
        return existing
    if not online:
        raise PackageError("uv was not found; set PALM_BUILD_UV or run with --online")
    asset = pinned(manifest, "uv")
    cache = CACHE / "uv.tar.gz"
    download(asset, cache)
    with tempfile.TemporaryDirectory(prefix="palm-uv-") as scratch:
        with tarfile.open(cache, "r:gz") as archive:
            archive.extractall(scratch, filter="data")
        binaries = list(Path(scratch).rglob("uv"))
        if not binaries:
            raise PackageError("the pinned uv archive did not contain a uv binary")
        target = CACHE / "uv"
        shutil.copy2(binaries[0], target)
        target.chmod(0o755)
        return target


def prepare_python(stage: Path, manifest: dict[str, Any], *, online: bool) -> Path:
    asset = pinned(manifest, "python")
    dest = stage / asset.dest
    if dest.exists():
        shutil.rmtree(dest)
    if online:
        cache = CACHE / f"cpython-{asset.version}.tar.gz"
        download(asset, cache)
        with tempfile.TemporaryDirectory(prefix="palm-python-") as scratch:
            with tarfile.open(cache, "r:gz") as archive:
                archive.extractall(scratch, filter="data")
            roots = [path for path in Path(scratch).iterdir() if path.is_dir()]
            if len(roots) != 1:
                raise PackageError("the pinned Python archive did not contain one python/ tree")
            shutil.copytree(roots[0], dest, symlinks=True)
    else:
        cached = find_cached_python(asset)
        shutil.copytree(cached, dest, symlinks=True)
    binary = next(iter(sorted(dest.glob("bin/python3.11"))), None)
    if binary is None:
        raise PackageError("the bundled Python has no bin/python3.11")
    print(f"package: bundled Python {asset.version} at {dest.relative_to(stage)}")
    return dest


def copy_tree_filtered(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise PackageError(f"missing required staging input: {source}")
    shutil.copytree(
        source,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".mypy_cache", ".ruff_cache"),
    )


def copy_file(source: Path, destination: Path, *, executable: bool = False) -> None:
    if not source.is_file():
        raise PackageError(f"missing required packaging input: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if executable:
        destination.chmod(0o755)


def stage_app(stage: Path, manifest: dict[str, Any]) -> None:
    if not (ROOT / "web" / "dist" / "index.html").is_file():
        raise PackageError("web/dist/index.html is missing; run `make build-web` first")
    copy_tree_filtered(ROOT / "src" / "basseparate", stage / "src" / "basseparate")
    copy_tree_filtered(ROOT / "web" / "dist", stage / "web" / "dist")
    for name in (
        "models.json",
        "checkpoints.json",
        "separate_track.py",
        "separate_msst.py",
        "pyproject.toml",
        "uv.lock",
    ):
        copy_file(ROOT / "analysis" / name, stage / "analysis" / name)
    for name in ("pyproject.toml", "uv.lock", ".python-version"):
        source = ROOT / "analysis-models" / name
        if source.is_file():
            copy_file(source, stage / "analysis-models" / name)
    for name in ("LICENSE", "NOTICES.md", "components.json"):
        copy_file(ROOT / "licenses" / name, stage / "licenses" / name)
    copy_file(ROOT / "README.md", stage / "README.md")
    copy_file(ROOT / "packaging" / "launcher" / "palm", stage / "bin" / "palm", executable=True)
    copy_file(ROOT / "packaging" / "launcher" / "palm.desktop", stage / "palm.desktop")
    copy_file(ROOT / "packaging" / "palm.svg", stage / "palm.svg")
    copy_file(ROOT / "packaging" / "build-manifest.toml", stage / "BUILD-MANIFEST.toml")


def export_requirements(stage: Path, uv: Path) -> Path:
    target = stage / "runtime-requirements.txt"
    command = [
        str(uv),
        "export",
        "--project",
        str(ROOT / "packaging" / "app-runtime"),
        "--locked",
        "--format",
        "requirements.txt",
        "--no-header",
        "--output-file",
        str(target),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, check=False, env=uv_environment()
    )
    if result.returncode != 0:
        raise PackageError(f"cannot export the hashed runtime lock: {result.stderr.strip()}")
    return target


def lock_package_names() -> list[str]:
    with (ROOT / "packaging" / "app-runtime" / "uv.lock").open("rb") as handle:
        data = tomllib.load(handle)
    names: list[str] = []
    for entry in data.get("package", []):
        name = str(entry.get("name", ""))
        if name and name != "palm-app-runtime":
            names.append(name)
    return names


def copy_installed_runtime(stage_python: Path, stage: Path) -> None:
    source_site = ROOT / ".venv" / "lib" / "python3.11" / "site-packages"
    bundle_site = stage_python / "lib" / "python3.11" / "site-packages"
    if not source_site.is_dir():
        raise PackageError(f"the preserved runtime is missing: {source_site}")
    for name in lock_package_names():
        try:
            distribution = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise PackageError(
                f"runtime package {name} is not installed in .venv; use --online "
                "to install from the hashed lock"
            ) from error
        for relative in distribution.files or ():
            source = distribution.locate_file(relative)
            try:
                relative_path = source.resolve().relative_to(source_site.resolve())
            except ValueError:
                continue
            destination = bundle_site / relative_path
            if source.is_dir():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    verify_imports(stage_python)


def online_runtime(stage_python: Path, requirements: Path, uv: Path) -> None:
    command = [
        str(uv),
        "pip",
        "install",
        "--python",
        str(stage_python / "bin" / "python3.11"),
        "--require-hashes",
        "--requirement",
        str(requirements),
        "--no-config",
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, check=False, env=uv_environment()
    )
    if result.returncode != 0:
        raise PackageError(f"hashed runtime install failed: {result.stderr.strip()}")
    verify_imports(stage_python)


def verify_imports(stage_python: Path) -> None:
    binary = stage_python / "bin" / "python3.11"
    code = (
        "import fastapi, uvicorn, pydantic, pydantic_settings, platformdirs, numpy; "
        "print('runtime imports ok')"
    )
    result = subprocess.run([str(binary), "-c", code], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise PackageError(f"bundled runtime imports failed: {result.stderr.strip()}")
    print(f"package: {result.stdout.strip()}")


def clean_runtime_tests(root: Path) -> None:
    """Remove test packages shipped inside third-party runtime distributions."""
    for path in sorted(root.rglob("tests"), reverse=True):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def clean_bytecode(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.name == "__pycache__" and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.suffix == ".pyc" and path.is_file():
            path.unlink(missing_ok=True)


def write_release_notes(stage: Path, version_value: str, appimage: str | None) -> Path:
    commit = (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        or "unknown"
    )
    notes = stage / "RELEASE-NOTES.md"
    content = f"""# PALM {version_value}

Practice Any Local Music, portable Linux x86_64 build.

- Commit: {commit}
- Build date: {time.strftime("%Y-%m-%d")}
- Launch: `bin/palm` (the tar root) or the AppImage
- First run: choose a separation model and the CPU/CUDA environment in the
  setup wizard; model weights and analysis tools are downloaded only there,
  never bundled here.
- Contents: application source, built UI, analysis code/registry/workers and
  environment definitions, launcher, desktop entry, icon, licences and the
  hashed runtime requirements.
- Not included: model weights, model/tool caches, analysis environments,
  recordings, tests, `.git`, `storage/` or any virtual environment.
- Runtime lock: `runtime-requirements.txt` (hashes from
  `packaging/app-runtime/uv.lock`).
- AppImage: {appimage or "not built (see APPIMAGE-FALLBACK.txt)"}.

See `licenses/LICENSE` (MIT for the application) and `licenses/NOTICES.md` for
third-party notices. Model weights keep their own terms.
"""
    notes.write_text(content, encoding="utf-8")
    return notes


def build_tar(stage: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz", compresslevel=6) as archive:
        for path in sorted(stage.rglob("*")):
            relative = path.relative_to(stage)
            info = archive.gettarinfo(str(path), arcname=f"{stage.name}/{relative.as_posix()}")
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            if path.is_file():
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
            else:
                archive.addfile(info)
    if output.stat().st_size >= MAX_ASSET_BYTES:
        raise PackageError(f"asset {output.name} is at least 2 GiB")
    print(f"package: wrote {output} ({output.stat().st_size} bytes)")
    return output


def build_appimage(
    stage: Path,
    output: Path,
    *,
    tool: Path | None,
    fallback: Path,
) -> Path | None:
    if tool is None or not tool.is_file():
        fallback.write_text(
            "PALM AppImage was not built: appimagetool is not available.\n"
            "Install the pinned appimagetool (see packaging/build-manifest.toml) "
            'or run `make package PACKAGE_ARGS="--appimage --online"` in CI.\n'
            "The tar.gz remains the supported portable asset.\n",
            encoding="utf-8",
        )
        print(f"package: AppImage skipped (fallback in {fallback})")
        return None
    appdir = stage.parent / "PALM.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    shutil.copytree(stage, appdir / "usr", symlinks=True)
    apprun = appdir / "AppRun"
    apprun.write_text('#!/bin/sh\nexec "$APPDIR/usr/bin/palm" "$@"\n', encoding="utf-8")
    apprun.chmod(0o755)
    shutil.copy2(stage / "palm.desktop", appdir / "palm.desktop")
    shutil.copy2(stage / "palm.svg", appdir / "palm.svg")
    (appdir / "usr" / "share" / "applications").mkdir(parents=True, exist_ok=True)
    shutil.copy2(stage / "palm.desktop", appdir / "usr" / "share" / "applications" / "palm.desktop")
    (appdir / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps").mkdir(
        parents=True, exist_ok=True
    )
    shutil.copy2(
        stage / "palm.svg",
        appdir / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / "palm.svg",
    )
    environment = dict(os.environ)
    environment.update({"ARCH": "x86_64", "APPIMAGE_EXTRACT_AND_RUN": "1"})
    result = subprocess.run(
        [str(tool), "--no-appstream", str(appdir), str(output)],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not output.is_file():
        fallback.write_text(
            "PALM AppImage build failed; use the tar.gz instead.\n"
            f"appimagetool exit {result.returncode}: {result.stderr[-2000:]}\n",
            encoding="utf-8",
        )
        print(f"package: AppImage failed; fallback in {fallback}")
        return None
    print(f"package: wrote {output} ({output.stat().st_size} bytes)")
    return output


def write_checksums(dist: Path, assets: Iterable[Path]) -> Path:
    path = dist / "SHA256SUMS"
    lines = [f"{sha256(asset)}  {asset.name}" for asset in assets if asset.is_file()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"package: wrote {path}")
    return path


def forbidden(name: str) -> bool:
    parts = Path(name).parts
    if "__pycache__" in parts or ".git" in parts or name.endswith(".pyc"):
        return True
    # The first component is the PALM root directory; only its direct children
    # (models/, tools/, storage/, tests/, ...) are forbidden. Third-party
    # packages legitimately contain directories named models/ or tests/.
    return len(parts) >= 2 and parts[1] in FORBIDDEN_ROOT_ENTRIES


def validate_tar(tar_path: Path) -> None:
    names: list[str] = []
    with tarfile.open(tar_path, "r:gz") as archive:
        for member in archive.getmembers():
            names.append(member.name)
            if member.isfile() and member.size >= MAX_ASSET_BYTES:
                raise PackageError(f"tar member {member.name} is at least 2 GiB")
    for required in REQUIRED_TAR_PARTS:
        if not any(name.endswith("/" + required) for name in names):
            raise PackageError(f"tar is missing required member {required}")
    bad = [name for name in names if forbidden(name)]
    if bad:
        raise PackageError(f"tar contains excluded paths: {bad[:10]}")
    print(f"package-check: tar structure ok ({len(names)} members)")


def extract_and_smoke(tar_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="palm-check-") as scratch:
        with tarfile.open(tar_path, "r:gz") as archive:
            archive.extractall(scratch, filter="data")
        roots = [path for path in Path(scratch).iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise PackageError("tar must contain one top-level PALM directory")
        app = roots[0]
        home = Path(scratch) / "home"
        home.mkdir()
        environment = {
            "HOME": str(home),
            "PATH": "/usr/bin:/bin",
            "PALM_MODE": "packaged",
            "PALM_APP_ROOT": str(app),
            "PALM_DATA_DIR": str(home / "data"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        result = subprocess.run(
            [str(app / "bin" / "palm"), "--help"],
            cwd=str(app),
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode != 0:
            raise PackageError(
                f"bundled bin/palm --help failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        print("package-check: bundled bin/palm --help ok")


def check_container(tar_path: Path) -> None:
    engine = shutil.which("podman") or shutil.which("docker")
    if engine is None:
        print("package-check: container smoke skipped (podman/docker not installed)")
        return
    image = "ubuntu:22.04"
    if Path(engine).name == "podman":
        exists = subprocess.run(
            [engine, "image", "exists", image], capture_output=True, check=False
        )
    else:
        exists = subprocess.run(
            [engine, "image", "inspect", image], capture_output=True, check=False
        )
    if exists.returncode != 0:
        print(f"package-check: container smoke skipped ({image} image not present offline)")
        return
    with tempfile.TemporaryDirectory(prefix="palm-container-") as scratch:
        with tarfile.open(tar_path, "r:gz") as archive:
            archive.extractall(scratch, filter="data")
        app = next(path for path in Path(scratch).iterdir() if path.is_dir())
        command = [
            engine,
            "run",
            "--rm",
            "-v",
            f"{app}:/palm:ro",
            "-e",
            "HOME=/tmp",
            image,
            "/palm/bin/palm",
            "--help",
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise PackageError(f"clean-container launch failed: {result.stderr.strip()}")
        print("package-check: clean Ubuntu 22.04 container launch ok")


def check_dist(dist: Path) -> int:
    tars = sorted(dist.glob("PALM-*-linux-x86_64.tar.gz"))
    if not tars:
        raise PackageError(f"no PALM tar found in {dist}; run `make package`")
    tar_path = tars[-1]
    validate_tar(tar_path)
    extract_and_smoke(tar_path)
    check_container(tar_path)
    checksums = dist / "SHA256SUMS"
    if not checksums.is_file():
        raise PackageError("SHA256SUMS is missing")
    for line in checksums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        asset = dist / name
        if not asset.is_file() or sha256(asset) != digest:
            raise PackageError(f"checksum mismatch for {name}")
    if not (dist / "RELEASE-NOTES.md").is_file():
        raise PackageError("RELEASE-NOTES.md is missing")
    for asset in (tar_path, *sorted(dist.glob("*.AppImage"))):
        if asset.stat().st_size >= MAX_ASSET_BYTES:
            raise PackageError(f"{asset.name} is at least 2 GiB")
    print("package-check: OK")
    return 0


def build(args: argparse.Namespace) -> int:
    data = load_manifest()
    version_value = version()
    dist = Path(args.output).resolve()
    stage = dist / f"palm-{version_value}-linux-x86_64"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        stage_python = prepare_python(stage, data, online=args.online)
        stage_app(stage, data)
        uv = resolve_uv(data, online=args.online)
        copy_file(uv, stage / "bin" / "uv", executable=True)
        requirements = export_requirements(stage, uv)
        if args.online:
            online_runtime(stage_python, requirements, uv)
        else:
            copy_installed_runtime(stage_python, stage)
        clean_runtime_tests(stage_python)
        clean_bytecode(stage)
        fallback = dist / "APPIMAGE-FALLBACK.txt"
        appimage: Path | None = None
        if args.appimage:
            tool = Path(args.appimagetool) if args.appimagetool else None
            if tool is None and args.online:
                tool_asset = pinned(data, "appimagetool")
                cache = CACHE / "appimagetool-x86_64.AppImage"
                download(tool_asset, cache)
                cache.chmod(0o755)
                tool = cache
            appimage = build_appimage(
                stage,
                dist / f"PALM-{version_value}-x86_64.AppImage",
                tool=tool,
                fallback=fallback,
            )
        release_notes = write_release_notes(stage, version_value, "built" if appimage else None)
        tar_path = build_tar(stage, dist / f"PALM-{version_value}-linux-x86_64.tar.gz")
        shutil.copy2(release_notes, dist / "RELEASE-NOTES.md")
        assets = [tar_path]
        if appimage is not None:
            assets.append(appimage)
        write_checksums(dist, assets)
        print(f"package: release assets in {dist}")
        return 0
    except (PackageError, OSError, tarfile.TarError) as error:
        print(f"package: {error}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DIST), help="release output directory")
    parser.add_argument(
        "--online", action="store_true", help="download pinned tools and runtime deps"
    )
    parser.add_argument("--appimage", action="store_true", help="build the optional AppImage")
    parser.add_argument("--appimagetool", default=None, help="path to a pinned appimagetool")
    parser.add_argument("--check", action="store_true", help="validate the built release")
    args = parser.parse_args(argv)
    if args.check:
        try:
            return check_dist(Path(args.output).resolve())
        except (PackageError, OSError, tarfile.TarError) as error:
            print(f"package-check: {error}", file=sys.stderr)
            return 1
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
