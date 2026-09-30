#!/usr/bin/env python3
"""Generate dependency inventory and license notices (M0.11).

Reads the locked environments (uv.lock, pnpm-lock.yaml) and installed
package metadata to produce:
  - licenses/components.json  (machine-readable inventory)
  - licenses/NOTICES.md       (human-readable notices)

No network access is required. All data comes from local lock files and
installed .dist-info metadata.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UV_LOCK = ROOT / "uv.lock"
PNPM_LOCK = ROOT / "pnpm-lock.yaml"
LICENSES_DIR = ROOT / "licenses"

# Packages that are part of the basseparate application itself.
SELF_PACKAGE = "basseparate"


def _parse_uv_lock(path: Path) -> list[dict[str, str]]:
    """Parse uv.lock and return a list of package entries."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    packages: list[dict[str, str]] = []
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        if name == SELF_PACKAGE:
            continue
        packages.append(
            {
                "name": name,
                "version": pkg.get("version", ""),
                "ecosystem": "python",
            }
        )
    return packages


def _parse_pnpm_lock(path: Path) -> list[dict[str, str]]:
    """Parse pnpm-lock.yaml and return a list of package entries.

    Uses a simple line-based parser to extract package names and versions
    from the ``packages:`` section without requiring a YAML dependency.
    """
    if not path.exists():
        return []
    packages: list[dict[str, str]] = []
    seen: set[str] = set()
    in_packages = False
    package_re = re.compile(r"^\s{2}['\"]?([^'\":@]+)(?:@([^'\":]+))?['\"]?:")

    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.rstrip()
            if stripped.startswith("packages:"):
                in_packages = True
                continue
            if in_packages:
                if stripped and not stripped.startswith("  ") and not stripped.startswith("\t"):
                    break
                m = package_re.match(stripped)
                if m:
                    name = m.group(1)
                    version = m.group(2) or ""
                    key = f"{name}@{version}"
                    if key not in seen:
                        seen.add(key)
                        packages.append(
                            {
                                "name": name,
                                "version": version,
                                "ecosystem": "javascript",
                            }
                        )
    return packages


def _get_python_license(name: str, version: str) -> tuple[str, str]:
    """Look up license metadata from installed package .dist-info."""
    try:
        dist = importlib.metadata.distribution(f"{name}=={version}")
    except importlib.metadata.PackageNotFoundError:
        try:
            dist = importlib.metadata.distribution(name)
        except importlib.metadata.PackageNotFoundError:
            return "unresolved", ""
    license_str = ""
    metadata = dist.metadata
    if metadata:
        license_value = metadata.get("License") or metadata.get("License-Expression", "")
        if license_value:
            license_str = license_value.strip()
    if not license_str:
        licenses_files = dist.read_text("LICENSE") or dist.read_text("LICENSE.txt") or ""
        if licenses_files:
            first_line = licenses_files.split("\n", 1)[0].strip()
            if first_line:
                license_str = first_line[:100]
    if not license_str:
        license_str = "unresolved"
    homepage = ""
    if metadata:
        homepage = metadata.get("Home-page", "") or metadata.get("Project-URL", "")
        if homepage:
            homepage = homepage.split(",")[0].strip()
    return license_str, homepage


def _get_js_homepage(name: str) -> str:
    """Derive a likely homepage URL for a JS package."""
    if name.startswith("@"):
        scope, pkg = name.split("/", 1)
        return f"https://github.com/{scope}/{pkg}"
    return f"https://www.npmjs.com/package/{name}"


def _classify_role(name: str, ecosystem: str, direct_names: set[str]) -> str:
    if name in direct_names:
        return "direct"
    return "transitive"


def main() -> int:
    if not UV_LOCK.exists():
        print(f"error: {UV_LOCK} not found", file=sys.stderr)
        return 1

    python_pkgs = _parse_uv_lock(UV_LOCK)
    js_pkgs = _parse_pnpm_lock(PNPM_LOCK)

    # Direct dependencies from pyproject.toml.
    direct_python: set[str] = set()
    pyproject = ROOT / "pyproject.toml"
    if pyproject.exists():
        with open(pyproject, "rb") as f:
            proj = tomllib.load(f)
        for dep in proj.get("project", {}).get("dependencies", []):
            direct_python.add(dep.split(">=")[0].split("<")[0].split("=")[0].strip())
        for dep in proj.get("dependency-groups", {}).get("dev", []):
            direct_python.add(dep.split(">=")[0].split("<")[0].split("=")[0].strip())

    direct_js: set[str] = set()
    frontend_pkg = ROOT / "frontend" / "package.json"
    if frontend_pkg.exists():
        with open(frontend_pkg, encoding="utf-8") as f:
            fdata = json.load(f)
        for section in ("dependencies", "devDependencies"):
            for dep in fdata.get(section, {}):
                direct_js.add(dep)

    components: list[dict[str, str]] = []

    for pkg in python_pkgs:
        license_str, homepage = _get_python_license(pkg["name"], pkg["version"])
        components.append(
            {
                "name": pkg["name"],
                "version": pkg["version"],
                "ecosystem": "python",
                "role": _classify_role(pkg["name"], "python", direct_python),
                "homepage": homepage or f"https://pypi.org/project/{pkg['name']}/",
                "license": license_str,
                "notice_location": "",
                "runtime_or_dev": "runtime" if pkg["name"] in {
                    "fastapi", "uvicorn", "pydantic", "pydantic-settings", "platformdirs",
                } else "development",
                "verification": "ok" if license_str != "unresolved" else "unresolved",
            }
        )

    for pkg in js_pkgs:
        homepage = _get_js_homepage(pkg["name"])
        components.append(
            {
                "name": pkg["name"],
                "version": pkg["version"],
                "ecosystem": "javascript",
                "role": _classify_role(pkg["name"], "javascript", direct_js),
                "homepage": homepage,
                "license": "unresolved",
                "notice_location": "",
                "runtime_or_dev": "runtime" if pkg["name"] in {
                    "react", "react-dom",
                } else "development",
                "verification": "unresolved",
            }
        )

    LICENSES_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {
        "generated": datetime.now(UTC).isoformat(),
        "project": "basseparate",
        "milestone": "0",
        "note": (
            "Milestone 0 bundles no model weights. "
            "No public license is claimed for the application itself; "
            "it is private and unpublished."
        ),
        "components": components,
    }

    manifest_path = LICENSES_DIR / "components.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Generate human-readable NOTICES.md.
    lines: list[str] = [
        "# basseparate — Dependency Notices",
        "",
        f"Generated: {manifest['generated']}",
        "",
        "Milestone 0 bundles **no model weights**.",
        "The application itself is **private and unpublished**.",
        "",
        "## Python",
        "",
        "| Package | Version | License | Role |",
        "|---------|---------|---------|------|",
    ]
    for c in components:
        if c["ecosystem"] == "python":
            lines.append(
                f"| {c['name']} | {c['version']} | {c['license']} | {c['role']} |"
            )

    lines.extend([
        "",
        "## JavaScript / Frontend",
        "",
        "| Package | Version | License | Role |",
        "|---------|---------|---------|------|",
    ])
    for c in components:
        if c["ecosystem"] == "javascript":
            lines.append(
                f"| {c['name']} | {c['version']} | {c['license']} | {c['role']} |"
            )

    lines.extend([
        "",
        "## Unresolved Licenses",
        "",
        "The following components have missing or ambiguous license metadata:",
        "",
    ])
    unresolved = [c for c in components if c["verification"] == "unresolved"]
    if unresolved:
        for c in unresolved:
            lines.append(f"- **{c['name']}** ({c['ecosystem']}, {c['role']})")
    else:
        lines.append("None.")

    lines.append("")

    notices_path = LICENSES_DIR / "NOTICES.md"
    with open(notices_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"licenses/components.json: {len(components)} components")
    print(f"licenses/NOTICES.md: written")
    print(f"unresolved: {len(unresolved)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
