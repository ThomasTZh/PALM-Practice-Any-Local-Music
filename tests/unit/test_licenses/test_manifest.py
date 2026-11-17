"""Licence manifest and bundled-text audit."""

from __future__ import annotations

import copy
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import audit  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


def test_manifest_is_complete_and_texts_are_reachable() -> None:
    audit.validate(ROOT)


def test_palm_mit_is_not_applied_to_third_party() -> None:
    data = audit.load_manifest(ROOT)
    assert data["palm_license"]["license_file"] == "licenses/LICENSE"
    for component in data["components"]:
        for key in ("license_file", "notice_file"):
            path = component.get(key)
            if path:
                assert path.startswith("licenses/third_party/"), (component["id"], path)


def test_manifest_matches_platform_docs() -> None:
    data = audit.load_manifest(ROOT)
    portable = (ROOT / "THIRD_PARTY.md").read_text()
    downloads = (ROOT / "THIRD_PARTY_DOWNLOADS.md").read_text()
    assert "licenses/third_party/manifest.json" in portable
    for cid in (
        "ffmpeg-linux-x86_64",
        "ffprobe-linux-x86_64",
        "ffmpeg-macos-arm64",
        "ffprobe-macos-arm64",
        "ffmpeg-windows-x86_64",
        "ffprobe-windows-x86_64",
        "sonic-annotator",
        "vamp-plugin-pack",
        "psutil",
        "python",
        "uv",
    ):
        if cid.startswith("ffmpeg"):
            alias = "FFmpeg"
        elif cid.startswith("ffprobe"):
            alias = "FFprobe"
        elif cid == "7zip-helper":
            alias = "7-Zip"
        else:
            alias = cid
        folded = portable.casefold()
        assert (
            cid in portable
            or cid.replace("-", " ").casefold() in folded
            or alias.casefold() in folded
        ), cid
    for component in data["components"]:
        if component["distribution"] == "downloaded":
            assert component["source_url"] in downloads, component["id"]


def test_missing_text_fails(tmp_path: Path) -> None:
    root = tmp_path
    shutil.copytree(ROOT / "licenses", root / "licenses")
    data = copy.deepcopy(audit.load_manifest(ROOT))
    data["components"][0]["license_file"] = "licenses/third_party/licenses/does-not-exist.txt"
    try:
        audit.validate(root, data)
    except audit.LicenseAuditError as error:
        assert "missing file" in str(error)
    else:
        raise AssertionError("missing licence text was accepted")


def test_unlisted_text_fails(tmp_path: Path) -> None:
    root = tmp_path
    shutil.copytree(ROOT / "licenses", root / "licenses")
    (root / "licenses/third_party/notices/unlisted.txt").write_text("not listed")
    try:
        audit.validate(root)
    except audit.LicenseAuditError as error:
        assert "unlisted" in str(error)
    else:
        raise AssertionError("unlisted text was accepted")


def test_bundled_tool_fails(tmp_path: Path) -> None:
    root = tmp_path
    shutil.copytree(ROOT / "licenses", root / "licenses")
    data = copy.deepcopy(audit.load_manifest(ROOT))
    for component in data["components"]:
        if component["id"] == "sonic-annotator":
            component["distribution"] = "bundled"
            break
    try:
        audit.validate(root, data)
    except audit.LicenseAuditError as error:
        assert "must not be bundled" in str(error)
    else:
        raise AssertionError("bundled tool was accepted")


def test_bundled_model_fails(tmp_path: Path) -> None:
    root = tmp_path
    shutil.copytree(ROOT / "licenses", root / "licenses")
    data = copy.deepcopy(audit.load_manifest(ROOT))
    for component in data["components"]:
        if component["id"] == "demucs-weights":
            component["distribution"] = "bundled"
            break
    try:
        audit.validate(root, data)
    except audit.LicenseAuditError as error:
        assert "must not be bundled" in str(error)
    else:
        raise AssertionError("bundled model was accepted")


def test_absolute_path_fails(tmp_path: Path) -> None:
    root = tmp_path
    shutil.copytree(ROOT / "licenses", root / "licenses")
    data = copy.deepcopy(audit.load_manifest(ROOT))
    data["components"][0]["license_file"] = "/home/user/secret.txt"
    try:
        audit.validate(root, data)
    except audit.LicenseAuditError as error:
        assert "absolute" in str(error)
    else:
        raise AssertionError("absolute path was accepted")


def test_media_tools_pins_and_manifest_cannot_diverge() -> None:
    from basseparate.setup.media_tools import PLATFORM_MEDIA_ASSETS

    data = audit.load_manifest(ROOT)
    components = {component["id"]: component for component in data["components"]}
    channels = {
        "linux": "linux-x86_64",
        "macos": "macos-arm64",
        "windows": "windows-x86_64",
    }
    for (platform, tool), pin in PLATFORM_MEDIA_ASSETS.items():
        component = components[f"{tool}-{channels[platform]}"]
        assert component["version"] == pin.version
        assert component["build"] == pin.build
        assert component["source_url"] == pin.source_url
        assert component["asset_url"] == pin.url
        assert component["sha256"] == pin.sha256
        assert component["size"] == pin.size
        assert component["license"] == "GPL-3.0-or-later"
        assert component["distribution"] == "downloaded"
