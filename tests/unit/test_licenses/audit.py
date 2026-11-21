"""Shared validation for the authoritative third-party licence manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MANIFEST = Path("licenses/third_party/manifest.json")
REQUIRED_FIELDS = ("id", "name", "version", "copyright", "license", "source_url", "distribution")
DISTRIBUTIONS = {"bundled", "downloaded", "excluded"}
REQUIRED_IDS = {
    "python",
    "uv",
    "psutil",
    "ffmpeg-linux-x86_64",
    "ffprobe-linux-x86_64",
    "ffmpeg-macos-arm64",
    "ffprobe-macos-arm64",
    "ffmpeg-windows-x86_64",
    "ffprobe-windows-x86_64",
    "sonic-annotator",
    "vamp-plugin-pack",
    "demucs-weights",
    "scnet-weights",
    "bs-roformer-weights",
    "react",
    "signalsmith-stretch",
}
ABSOLUTE_PREFIXES = ("/", "\\", "C:", "c:", "D:", "d:")
PACKAGE_EXTENSIONS = {
    ".exe",
    ".dll",
    ".dylib",
    ".so",
    ".dmg",
    ".zip",
    ".ckpt",
    ".th",
    ".pt",
    ".onnx",
    ".bin",
}


class LicenseAuditError(AssertionError):
    """A licence manifest or package audit failed."""


def load_manifest(root: Path) -> dict[str, Any]:
    return json.loads((root / MANIFEST).read_text())


def _check_path(path: str, root: Path, *, label: str, errors: list[str]) -> None:
    if not isinstance(path, str) or not path:
        errors.append(f"{label}: empty path")
        return
    if path.startswith(ABSOLUTE_PREFIXES) or ".." in Path(path).parts:
        errors.append(f"{label}: absolute or escaping path {path!r}")
        return
    if not (root / path).is_file():
        errors.append(f"{label}: missing file {path}")


def validate(root: Path = Path(), data: dict[str, Any] | None = None) -> None:
    data = load_manifest(root) if data is None else data
    errors: list[str] = []
    components = data.get("components")
    if not isinstance(components, list) or not components:
        raise LicenseAuditError("manifest has no components")
    ids: set[str] = set()
    referenced: set[str] = set()
    for component in components:
        cid = str(component.get("id", "?"))
        for field in REQUIRED_FIELDS:
            if not component.get(field):
                errors.append(f"{cid}: missing {field}")
        if cid in ids:
            errors.append(f"{cid}: duplicate id")
        ids.add(cid)
        distribution = component.get("distribution")
        if distribution not in DISTRIBUTIONS:
            errors.append(f"{cid}: invalid distribution {distribution!r}")
        if not str(component.get("source_url", "")).startswith("https://"):
            errors.append(f"{cid}: source_url must be https")
        paths = [component.get("license_file"), component.get("notice_file")]
        paths.extend(component.get("license_files", []))
        for path in paths:
            if path:
                _check_path(str(path), root, label=f"{cid} licence", errors=errors)
                referenced.add(str(path))
        for path in component.get("bundled_paths", []):
            if str(path).startswith(ABSOLUTE_PREFIXES) or ".." in Path(str(path)).parts:
                errors.append(f"{cid}: absolute bundled path {path!r}")
        if distribution == "bundled" and component.get("component_type") in {"tool", "model"}:
            errors.append(f"{cid}: tool/model must not be bundled")
        if component.get("component_type") in {"tool", "model"} and distribution == "bundled":
            errors.append(f"{cid}: downloaded tool/model is bundled")
        if cid.startswith(("ffmpeg-", "ffprobe-")):
            if component.get("license") != "GPL-3.0-or-later":
                errors.append(f"{cid}: pinned static build must be GPL-3.0-or-later")
            notice = (root / str(component.get("notice_file", ""))).read_text(errors="ignore")
            if "-L" not in notice or "--enable-gpl" not in notice:
                errors.append(f"{cid}: exact ffmpeg -L/build licence evidence is missing")
    missing_ids = REQUIRED_IDS - ids
    if missing_ids:
        errors.append("missing required components: " + ", ".join(sorted(missing_ids)))
    if "palm_license" not in data:
        errors.append("missing palm_license")
    else:
        _check_path(
            str(data["palm_license"].get("license_file", "")),
            root,
            label="PALM licence",
            errors=errors,
        )
        if data["palm_license"].get("license") != "MIT":
            errors.append("PALM licence must be MIT")
    for key in ("license_texts", "notice_texts"):
        for path in data.get(key, []):
            _check_path(str(path), root, label=key, errors=errors)
            referenced.add(str(path))
    # Every text under third_party must be reachable from the manifest.
    third_party = root / "licenses" / "third_party"
    if third_party.is_dir():
        for path in third_party.rglob("*"):
            if path.is_file() and path.name != "manifest.json":
                relative = path.relative_to(root).as_posix()
                if relative not in referenced:
                    errors.append(f"unlisted licence text: {relative}")
    if errors:
        raise LicenseAuditError("\n".join(errors))


def archive_contents(path: Path) -> list[str]:
    if path.suffix == ".zip":
        import zipfile

        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    import tarfile

    with tarfile.open(path, "r:gz") as archive:
        return archive.getnames()


def assert_package_has_no_third_party_payload(path: Path) -> None:
    names = archive_contents(path)
    for name in names:
        parts = Path(name).parts
        # Ignore the archive's top-level app directory.
        body = parts[1:] if len(parts) > 1 else parts
        bundled_windows_tools = (
            path.name.lower().endswith(".zip")
            and len(body) >= 2
            and body[0] == "tools"
            and body[1] in {"ffmpeg", "sonic-annotator", "vamp-plugins", "bundled-tools.json"}
        )
        bundled_source = len(body) >= 3 and body[:3] == ("licenses", "bundled-tools", "sources")
        if (
            body
            and body[0] in {"models", "tools", "environments", "audio2test", ".git", "cache"}
            and not bundled_windows_tools
        ):
            raise LicenseAuditError(f"{path.name}: contains forbidden payload {name}")
        if (
            Path(name).suffix.lower() in PACKAGE_EXTENSIONS
            and Path(name).suffix.lower() not in {".so", ".dylib", ".dll", ".exe"}
            and not bundled_source
        ):
            raise LicenseAuditError(f"{path.name}: contains binary/archive {name}")
