#!/usr/bin/env python3
"""Build the unsigned Windows x64 portable PALM ZIP.

The build uses the pinned standalone CPython and uv archives from
``packaging/windows/build-manifest.toml``. On Windows it installs the hashed
runtime directly into the embedded interpreter; on a POSIX build host it
cross-installs Windows wheels into ``python/Lib/site-packages`` with uv's
``--python-platform`` support. The ZIP contains only the app, web build,
analysis workers/registry/env definitions, launcher, licences and runtime.
FFmpeg, tools, plugins, models, environments and sources are excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "packaging" / "windows" / "build-manifest.toml"
DIST = ROOT / "dist"
CACHE = ROOT / "storage" / "tmp-windows-cache"
FORBIDDEN = {
    "models",
    "tools",
    "environments",
    "cache",
    "tests",
    "audio2test",
    "storage",
    ".git",
    "node_modules",
}
REQUIRED = (
    "palm.cmd",
    "python/python.exe",
    "bin/uv.exe",
    "web/dist/index.html",
    "analysis/models.json",
    "analysis/checkpoints.json",
    "analysis/separate_track.py",
    "analysis/separate_msst.py",
    "analysis/envs/cpu-windows/uv.lock",
    "analysis/envs/msst-windows/uv.lock",
    "analysis/envs/cpu-windows/pyproject.toml",
    "licenses/LICENSE",
    "licenses/third_party/manifest.json",
    "runtime-requirements.txt",
    "install.json",
    "RELEASE-NOTES.md",
    "PALM.exe",
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


def load_manifest() -> dict[str, Any]:
    data = tomllib.loads(MANIFEST.read_text())
    if data.get("schema_version") != 1:
        raise PackageError(f"unsupported Windows build manifest {MANIFEST}")
    for key in ("python", "uv"):
        entry = data.get(key)
        if not entry or not entry.get("url") or not entry.get("sha256"):
            raise PackageError(f"Windows build manifest lacks {key}")
    return data


def download(entry: dict[str, Any], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256(destination) == entry["sha256"]:
        return destination
    temporary = destination.with_suffix(destination.suffix + ".part")
    print(f"package-windows: downloading {entry['url']}")
    try:
        with (
            urllib.request.urlopen(entry["url"], timeout=180) as response,
            temporary.open("wb") as out,
        ):
            shutil.copyfileobj(response, out)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise PackageError(f"cannot download {entry['url']}: {error}") from error
    if temporary.stat().st_size != int(entry.get("size", 0)):
        temporary.unlink(missing_ok=True)
        raise PackageError(f"{entry['url']} has an unexpected size")
    actual = sha256(temporary)
    if actual != entry["sha256"]:
        temporary.unlink(missing_ok=True)
        raise PackageError(f"{entry['url']} has sha256 {actual}")
    temporary.replace(destination)
    return destination


def cached_asset(entry: dict[str, Any], name: str) -> Path:
    return CACHE / name


def extract_python(archive: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    with tempfile.TemporaryDirectory(prefix="palm-win-python-") as scratch:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(scratch, filter="data")
        roots = [path for path in Path(scratch).iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise PackageError("the Windows Python archive did not contain one python tree")
        shutil.copytree(roots[0], destination, symlinks=True)
    if not (destination / "python.exe").is_file():
        raise PackageError("the embedded Windows Python has no python.exe")


def extract_uv(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        candidates = [name for name in bundle.namelist() if name.endswith("uv.exe")]
        if not candidates:
            raise PackageError("the uv archive contains no uv.exe")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with bundle.open(candidates[0]) as source, destination.open("wb") as out:
            shutil.copyfileobj(source, out)
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
        env={**os.environ, "UV_CACHE_DIR": str(ROOT / "storage" / "tmp-windows-cache" / "uv")},
    )
    if result.returncode != 0:
        raise PackageError(f"cannot export runtime requirements: {result.stderr.strip()}")


def install_runtime(stage: Path, uv: Path, requirements: Path, *, host_uv: Path | None) -> None:
    python = stage / "python" / "python.exe"
    target = stage / "python" / "Lib" / "site-packages"
    target.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
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
        command = [
            str(host_uv or uv),
            "pip",
            "install",
            "--target",
            str(target),
            "--python-platform",
            "x86_64-pc-windows-msvc",
            "--python-version",
            "3.11",
            "--only-binary",
            ":all:",
            "--require-hashes",
            "--requirement",
            str(requirements),
            "--no-config",
        ]
    environment = dict(os.environ)
    environment.setdefault("UV_CACHE_DIR", str(ROOT / "storage" / "tmp-windows-cache" / "uv"))
    result = subprocess.run(command, capture_output=True, text=True, check=False, env=environment)
    if result.returncode != 0:
        raise PackageError(f"Windows runtime install failed: {result.stderr.strip()}")


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise PackageError(f"missing staging input {source}")
    shutil.copytree(
        source,
        destination,
        symlinks=False,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".mypy_cache", ".ruff_cache"),
    )


def build_launcher(destination: Path) -> None:
    """Build PALM.exe from source on Windows; use the committed fallback elsewhere."""
    source = ROOT / "packaging" / "windows" / "palm_launcher.c"
    script = ROOT / "packaging" / "windows" / "build_launcher.ps1"
    if not source.is_file() or not script.is_file():
        raise PackageError("native launcher source/build script is missing")
    if os.name == "nt":
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Out",
                str(destination),
            ],
            check=False,
        )
        if completed.returncode != 0 or not destination.is_file():
            raise PackageError("building PALM.exe from palm_launcher.c failed")
        return
    fallback = ROOT / "packaging" / "windows" / "PALM.exe"
    if not fallback.is_file():
        raise PackageError("prebuilt PALM.exe is missing on this non-Windows host")
    copy_file(fallback, destination)


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise PackageError(f"missing staging input {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def stage(stage: Path, manifest: dict[str, Any], requirements: Path, *, online: bool) -> None:
    if not (ROOT / "web" / "dist" / "index.html").is_file():
        raise PackageError("web/dist/index.html is missing; run make build-web first")
    python_archive = cached_asset(
        manifest["python"], f"python-{manifest['python']['version']}.tar.gz"
    )
    uv_archive = cached_asset(manifest["uv"], "uv-windows.zip")
    if online:
        download(manifest["python"], python_archive)
        download(manifest["uv"], uv_archive)
    elif not (python_archive.is_file() and uv_archive.is_file()):
        raise PackageError("Windows archives are not cached; run with --online")
    extract_python(python_archive, stage / "python")
    extract_uv(uv_archive, stage / "bin" / "uv.exe")
    copy_tree(ROOT / "src" / "basseparate", stage / "src" / "basseparate")
    copy_tree(ROOT / "web" / "dist", stage / "web" / "dist")
    for name in (
        "models.json",
        "checkpoints.json",
        "separate_track.py",
        "separate_msst.py",
        "pyproject.toml",
        "uv.lock",
    ):
        copy_file(ROOT / "analysis" / name, stage / "analysis" / name)
    for name in ("cpu-windows", "msst-windows"):
        copy_tree(ROOT / "analysis" / "envs" / name, stage / "analysis" / "envs" / name)
    copy_file(ROOT / "analysis" / "envs" / "cpu.json", stage / "analysis" / "envs" / "cpu.json")
    copy_file(ROOT / "analysis" / "envs" / "cuda.json", stage / "analysis" / "envs" / "cuda.json")
    copy_file(ROOT / "scripts" / "install_tools.py", stage / "scripts" / "install_tools.py")
    for name in ("LICENSE", "NOTICES.md", "components.json"):
        copy_file(ROOT / "licenses" / name, stage / "licenses" / name)
    copy_tree(ROOT / "licenses" / "third_party", stage / "licenses" / "third_party")
    build_launcher(stage / "PALM.exe")
    copy_file(ROOT / "pyproject.toml", stage / "pyproject.toml")
    write_install_json(stage / "install.json", "windows-x86_64", version())
    copy_file(ROOT / "README.md", stage / "README.md")
    copy_file(ROOT / "packaging" / "release-notes.md", stage / "RELEASE-NOTES.md")
    copy_file(ROOT / "palm.cmd", stage / "palm.cmd")
    copy_file(requirements, stage / "runtime-requirements.txt")
    copy_file(ROOT / "packaging" / "windows" / "build-manifest.toml", stage / "BUILD-MANIFEST.toml")
    install_runtime(stage, stage / "bin" / "uv.exe", requirements, host_uv=shutil.which("uv"))


def forbidden(name: str) -> bool:
    parts = Path(name).parts
    if "__pycache__" in parts or name.endswith(".pyc") or ".git" in parts:
        return True
    return len(parts) >= 2 and parts[1].lower() in FORBIDDEN


def clean_bytecode(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.name == "__pycache__" and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.suffix == ".pyc" and path.is_file():
            path.unlink(missing_ok=True)


def write_install_json(destination: Path, channel: str, version_value: str) -> None:
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


def build_zip(stage: Path, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(stage.rglob("*")):
            relative = path.relative_to(stage).as_posix()
            if path.is_file():
                info = zipfile.ZipInfo(f"{stage.name}/{relative}")
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                mode = path.stat().st_mode & 0o777
                if not mode & 0o111:
                    mode = 0o644
                info.create_system = 3
                info.external_attr = (0o100000 | mode) << 16
                archive.writestr(info, path.read_bytes())
    print(f"package-windows: wrote {output} ({output.stat().st_size} bytes)")
    return output


def check_zip(path: Path) -> int:
    if not path.is_file():
        raise PackageError(f"missing ZIP {path}")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    for required in REQUIRED:
        if not any(
            name.endswith("/" + required.replace("/", "\\")) or name.endswith("/" + required)
            for name in names
        ):
            raise PackageError(f"ZIP is missing {required}")
    bad = [name for name in names if forbidden(name)]
    if bad:
        raise PackageError(f"ZIP contains excluded paths: {bad[:5]}")
    payload_names = [
        name
        for name in names
        if "licenses/" not in name.lower()
        and ("ffmpeg" in name.lower() or "sonic-annotator" in name.lower())
    ]
    if payload_names:
        raise PackageError("ZIP contains FFmpeg/Sonic Annotator payload")
    print(f"package-windows-check: {len(names)} entries, required content present")
    return 0


def find_iscc() -> Path | None:
    configured = os.environ.get("ISCC")
    if configured and Path(configured).is_file():
        return Path(configured)
    found = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if found:
        return Path(found)
    for candidate in (
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


def build_installer(stage: Path, output_dir: Path, version_value: str) -> Path | None:
    """Build the Inno Setup installer from the same staged payload as the ZIP."""
    iscc = find_iscc()
    if iscc is None:
        if os.name == "nt":
            raise PackageError("ISCC.exe not found; install Inno Setup 6 or set ISCC")
        print("package-windows: ISCC.exe unavailable on this host; installer skipped")
        return None
    installer = output_dir / f"PALM-{version_value}-windows-x86_64-installer.exe"
    command = [
        str(iscc),
        f"/DPayloadDir={stage}",
        f"/DAppVersion={version_value}",
        f"/DOutputDir={output_dir}",
        f"/DOutputBaseFilename={installer.stem}",
        str(ROOT / "packaging" / "windows" / "PALM.iss"),
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0 or not installer.is_file():
        raise PackageError("Inno Setup installer build failed")
    print(f"package-windows: wrote {installer} ({installer.stat().st_size} bytes)")
    return installer


def build(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    version_value = version()
    output_dir = Path(args.output).resolve()
    stage_path = output_dir / f"palm-{version_value}-windows-x86_64"
    if stage_path.exists():
        shutil.rmtree(stage_path)
    stage_path.mkdir(parents=True)
    requirements = output_dir / "runtime-requirements.txt"
    export_requirements(requirements)
    try:
        stage(stage_path, manifest, requirements, online=args.online)
        clean_bytecode(stage_path)
        zip_path = build_zip(stage_path, output_dir / f"PALM-{version_value}-windows-x86_64.zip")
        check_zip(zip_path)
        build_installer(stage_path, output_dir, version_value)
        return 0
    except (PackageError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"package-windows: {error}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(DIST))
    parser.add_argument(
        "--online", action="store_true", help="download pinned Windows Python/uv archives"
    )
    parser.add_argument("--check", action="store_true", help="validate an existing ZIP")
    args = parser.parse_args(argv)
    if args.check:
        zips = sorted(Path(args.output).glob("PALM-*-windows-x86_64.zip"))
        if not zips:
            print("package-windows-check: no ZIP found", file=sys.stderr)
            return 1
        try:
            return check_zip(zips[-1])
        except (PackageError, OSError, zipfile.BadZipFile) as error:
            print(f"package-windows-check: {error}", file=sys.stderr)
            return 1
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
