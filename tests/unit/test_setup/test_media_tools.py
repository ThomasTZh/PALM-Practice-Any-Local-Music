"""Managed FFmpeg/FFprobe pins, extraction, status and resolution."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from basseparate import platform_support
from basseparate.config import RuntimePaths
from basseparate.setup import media_tools
from basseparate.setup.errors import SetupInstallError
from basseparate.setup.media_tools import (
    PLATFORM_MEDIA_ASSETS,
    install_media_tools,
)


def _zip(tool: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(f"bundle/{tool}", b"binary")
    return stream.getvalue()


def _asset(platform: str, tool: str, data: bytes):
    current = PLATFORM_MEDIA_ASSETS[(platform, tool)]
    return replace(
        current,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        member=f"bundle/{tool}",
    )


def test_media_assets_are_pinned_for_all_platforms() -> None:
    expected = {
        (platform, tool)
        for platform in ("windows", "macos", "linux")
        for tool in ("ffmpeg", "ffprobe")
    }
    assert set(PLATFORM_MEDIA_ASSETS) == expected
    for asset in PLATFORM_MEDIA_ASSETS.values():
        assert asset.url.startswith("https://")
        assert len(asset.sha256) == 64
        assert asset.size > 0
        assert asset.version and asset.build and asset.license
        assert asset.source_url.startswith("https://")


def test_install_and_status_records_license_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = RuntimePaths.from_environment(
        mode="packaged",
        app_root=tmp_path / "app",
        data_root=tmp_path / "data with spaces",
    )
    runtime.app_root.mkdir()
    for tool in ("ffmpeg", "ffprobe"):
        data = _zip(tool)
        monkeypatch.setitem(
            PLATFORM_MEDIA_ASSETS,
            ("linux", tool),
            _asset("linux", tool, data),
        )
        monkeypatch.setattr(
            media_tools,
            "_asset_download",
            None,
            raising=False,
        )
    downloads = {
        "ffmpeg": _zip("ffmpeg"),
        "ffprobe": _zip("ffprobe"),
    }
    # Replace assets after constructing archives, then inject downloader by tool.
    for tool in ("ffmpeg", "ffprobe"):
        data = downloads[tool]
        monkeypatch.setitem(
            PLATFORM_MEDIA_ASSETS,
            ("linux", tool),
            _asset("linux", tool, data),
        )
    calls: dict[str, int] = {}

    def download(asset: media_tools.MediaToolAsset, path: Path) -> None:
        calls[asset.tool] = calls.get(asset.tool, 0) + 1
        path.write_bytes(downloads[asset.tool])

    result = install_media_tools(runtime, platform="linux", downloader=download)
    assert all(item["installed"] for item in result.values())
    metadata = json.loads((runtime.data_root / "tools/ffmpeg/media-tools.json").read_text())
    assert metadata["ffmpeg"]["license"] == "GPL-3.0-or-later"
    assert metadata["ffmpeg"]["version"] == "9.0.2"
    assert (runtime.data_root / "tools/ffmpeg/ffmpeg").stat().st_mode & 0o111
    assert calls == {"ffmpeg": 1, "ffprobe": 1}


def test_bad_media_hash_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = RuntimePaths.from_environment(
        mode="packaged", app_root=tmp_path / "app", data_root=tmp_path / "data"
    )
    runtime.app_root.mkdir()
    data = _zip("ffmpeg")
    asset = replace(_asset("linux", "ffmpeg", data), sha256="0" * 64)
    monkeypatch.setitem(PLATFORM_MEDIA_ASSETS, ("linux", "ffmpeg"), asset)
    with pytest.raises(SetupInstallError, match="SHA-256"):
        install_media_tools(
            runtime,
            platform="linux",
            downloader=lambda _asset, path: path.write_bytes(data),
        )


def test_managed_media_binary_preferred_and_override_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    managed_dir = data / "tools" / "ffmpeg"
    managed_dir.mkdir(parents=True)
    managed = managed_dir / "ffmpeg"
    managed.write_bytes(b"managed")
    monkeypatch.setenv("PALM_DATA_DIR", str(data))
    monkeypatch.delenv("PALM_FFMPEG", raising=False)
    monkeypatch.delenv("BASSEPARATE_FFMPEG", raising=False)
    assert platform_support.ffmpeg_binary(which=lambda _name: "/usr/bin/ffmpeg") == str(managed)
    monkeypatch.setenv("PALM_FFMPEG", str(tmp_path / "override"))
    assert platform_support.ffmpeg_binary(which=lambda _name: "/usr/bin/ffmpeg") == str(
        tmp_path / "override"
    )


def test_partial_recovery_reuses_installed_media_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = RuntimePaths.from_environment(
        mode="packaged", app_root=tmp_path / "app", data_root=tmp_path / "data"
    )
    runtime.app_root.mkdir()
    root = runtime.tools_root / "ffmpeg"
    root.mkdir(parents=True)
    for tool in ("ffmpeg", "ffprobe"):
        (root / tool).write_bytes(b"installed")
    calls: list[Path] = []

    def must_not_download(_asset, path):
        calls.append(path)
        raise AssertionError("completed media tools must not be downloaded again")

    result = install_media_tools(runtime, platform="linux", downloader=must_not_download)
    assert calls == []
    assert all(item["installed"] for item in result.values())
