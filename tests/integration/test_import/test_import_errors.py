"""Import failures map to actionable 4xx responses, never generic 500s."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
AUDIO = ROOT / "tests" / "fixtures" / "audio"
TONE = AUDIO / "tone_440hz.wav"


def _assert_setup_error(response) -> None:
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "Open Setup" in detail
    assert "Internal Server Error" not in detail
    assert "Traceback" not in detail


def test_missing_ffprobe_returns_setup_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from basseparate import media

    monkeypatch.setattr(media, "ffprobe_binary", lambda: "/missing/ffprobe")
    response = client.post("/api/imports", json={"path": str(TONE)})
    _assert_setup_error(response)
    assert "FFprobe" in response.json()["detail"]


def test_missing_ffmpeg_returns_setup_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from basseparate import media

    monkeypatch.setattr(media, "ffmpeg_binary", lambda: "/missing/ffmpeg")
    response = client.post("/api/imports", json={"path": str(TONE)})
    _assert_setup_error(response)
    assert "FFmpeg" in response.json()["detail"]


def test_malformed_audio_returns_client_error(client: TestClient, tmp_path: Path) -> None:
    broken = tmp_path / "not audio.wav"
    broken.write_bytes(b"this is not a wave file")
    response = client.post("/api/imports", json={"path": str(broken)})
    assert response.status_code == 400, response.text
    assert "Internal Server Error" not in response.text
    assert "Traceback" not in response.text


def test_spaces_and_non_ascii_name_import_succeeds(client: TestClient, tmp_path: Path) -> None:
    source = tmp_path / "bass take – naïve.wav"
    shutil.copyfile(TONE, source)
    response = client.post("/api/imports", json={"path": str(source), "name": "Bass naïve"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Bass naïve"
    assert body["audio"]["duration_seconds"] == 2.0


def test_successful_wav_import_returns_created(client: TestClient) -> None:
    response = client.post("/api/imports", json={"path": str(TONE)})
    assert response.status_code == 201, response.text
    assert response.json()["audio"]["sample_rate"] == 44_100


def test_unexpected_import_error_is_safe_500_and_logged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from basseparate.api import import_routes

    def explode(*_args, **_kwargs):
        raise RuntimeError("internal detail that must not leak")

    monkeypatch.setattr(import_routes, "import_media", explode)
    with caplog.at_level(logging.ERROR, logger="basseparate.api.import_routes"):
        response = client.post("/api/imports", json={"path": str(TONE)})
    assert response.status_code == 500, response.text
    detail = response.json()["detail"]
    assert "Import failed unexpectedly" in detail
    assert "internal detail" not in detail
    assert "Traceback" not in detail
    assert "unexpected import failure" in caplog.text


def test_decode_failure_returns_client_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from basseparate import media

    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\necho 'decode failed' >&2\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setattr(media, "ffmpeg_binary", lambda: str(fake))
    response = client.post("/api/imports", json={"path": str(TONE)})
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "ffmpeg could not decode" in detail.lower()
    assert "Internal Server Error" not in response.text


def test_wav_import_succeeds_when_windows_directory_fsync_is_noop(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sys
    import types

    from basseparate import platform_support

    monkeypatch.setattr(platform_support, "POSIX", False)
    monkeypatch.setattr(platform_support, "WINDOWS", True)
    fake_msvcrt = types.SimpleNamespace(
        LK_LOCK=1,
        LK_NBLCK=2,
        LK_UNLCK=3,
        locking=lambda *_args: None,
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    source = tmp_path / "windows take.wav"
    shutil.copyfile(TONE, source)
    response = client.post("/api/imports", json={"path": str(source)})
    assert response.status_code == 201, response.text
    assert response.json()["audio"]["duration_seconds"] == 2.0
