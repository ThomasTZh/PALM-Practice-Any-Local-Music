"""Project documents and the JSON-safe response mapper.

The canonical document is snake_case and stays stable; the response mapper adds
the camelCase aliases the UI client reads. Both are pure functions so the wire
shape can be tested without a server.
"""

from __future__ import annotations

import pytest

from basseparate.projects import (
    AudioInfo,
    PeakInfo,
    Project,
    build_audio_info,
    build_project,
    project_response,
    validate_project_id,
)


def audio_info() -> AudioInfo:
    return build_audio_info(
        asset_id="asset123",
        source_name="tone_48k_stereo.wav",
        source_format="wav",
        sample_rate=48_000,
        channels=2,
        frames=48_000,
        content_sha256="a" * 64,
        peak_counts={256: 188, 1024: 47, 4096: 12, 16384: 3},
    )


def test_audio_info_records_rate_frames_channels_duration_and_hash() -> None:
    audio = audio_info()
    assert audio.sample_rate == 48_000
    assert audio.channels == 2
    assert audio.frames == 48_000
    assert audio.duration_seconds == pytest.approx(1.0)
    assert audio.content_sha256 == "a" * 64
    assert audio.asset_id == "asset123"
    assert audio.peaks["256"] == PeakInfo(
        bucket_size=256, count=188, channels=2, frames=48_000, byte_size=20 + 188 * 2 * 4
    )


def test_build_project_is_deterministic_with_injected_id_and_clock() -> None:
    project = build_project(
        audio_info(),
        name="Practice take",
        project_id="pj-1",
        now="2026-01-02T03:04:05Z",
    )
    assert project.id == "pj-1"
    assert project.name == "Practice take"
    assert project.created_at == project.updated_at == "2026-01-02T03:04:05Z"
    assert project.revision == 1
    assert project.document == {}
    assert project.audio == audio_info()


def test_project_response_has_canonical_and_ui_aliases() -> None:
    project = build_project(
        audio_info(), name="Take", project_id="pj-1", now="2026-01-02T03:04:05Z"
    )
    payload = project_response(project)

    assert payload["id"] == "pj-1"
    assert payload["name"] == payload["title"] == "Take"
    assert payload["duration_seconds"] == pytest.approx(1.0)
    assert payload["durationSeconds"] == pytest.approx(1.0)
    assert payload["audio"]["sample_rate"] == 48_000
    assert payload["audio"]["frames"] == 48_000
    assert payload["asset"]["id"] == "asset123"
    assert payload["asset"]["title"] == "Take"
    assert payload["asset"]["durationSeconds"] == pytest.approx(1.0)
    assert payload["asset"]["sampleRate"] == 48_000
    assert payload["asset"]["channels"] == 2
    assert payload["asset"]["frames"] == 48_000
    assert payload["grid"] is None
    assert payload["key"] is None
    assert payload["stems"] == []
    assert payload["document"] == {}


def test_project_response_surfaces_document_fields_filled_later() -> None:
    project = build_project(audio_info(), name="Take", project_id="pj-1")
    project.document = {
        "grid": {"bpm": 120.0, "meter": {"numerator": 4, "denominator": 4}},
        "key": "C major",
        "stems": [{"id": "bass", "name": "Bass", "role": "bass"}],
    }
    payload = project_response(project)
    assert payload["grid"]["bpm"] == 120.0
    assert payload["key"] == "C major"
    assert payload["stems"] == [{"id": "bass", "name": "Bass", "role": "bass"}]


def test_project_response_round_trips_through_pydantic_json() -> None:
    project = build_project(audio_info(), name="Take", project_id="pj-1")
    payload = project_response(project)
    again = Project.model_validate_json(project.model_dump_json())
    assert again == project
    assert project_response(again)["id"] == payload["id"]


@pytest.mark.parametrize("bad", ["", "a/b", "../x", "x" * 65, "spaces here", ".hidden"])
def test_validate_project_id_rejects_unsafe_values(bad: str) -> None:
    with pytest.raises(ValueError, match="project id"):
        validate_project_id(bad)


def test_validate_project_id_accepts_slug_and_uuid() -> None:
    assert validate_project_id("abc-123_DEF") == "abc-123_DEF"
    assert validate_project_id("0" * 32) == "0" * 32
