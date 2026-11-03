"""Stem PCM HTTP Range semantics with a pre-built cache (no inference)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from basseparate.app import create_app
from basseparate.config import Settings
from basseparate.projects import ProjectStore, build_audio_info, build_project
from basseparate.stems import STEM_LABELS


def make_stem_workspace(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "dist")
    paths = settings.data_paths.ensure()
    store = ProjectStore(paths.projects)
    frames, channels, rate = 2_048, 2, 48_000
    asset_id = "range-asset"
    pcm_dir = paths.asset_dir(asset_id)
    pcm_dir.mkdir(parents=True)
    (pcm_dir / "pcm.f32").write_bytes(b"\0" * (frames * channels * 4))
    audio = build_audio_info(
        asset_id=asset_id,
        source_name="range.wav",
        source_format="wav",
        sample_rate=rate,
        channels=channels,
        frames=frames,
        content_sha256="c" * 64,
        peak_counts={},
    )
    project = store.create(build_project(audio, name="Range stems"))

    key = "b" * 64
    cache = paths.root / "stems" / key
    cache.mkdir(parents=True)
    expected: dict[str, bytes] = {}
    rows = []
    for index, label in enumerate(STEM_LABELS):
        t = np.arange(frames, dtype=np.float64) / rate
        tone = 0.4 * np.sin(2 * np.pi * (220 + index * 110) * t)
        data = np.stack([tone, -tone], axis=1).astype("<f4")
        expected[label] = data.tobytes()
        (cache / f"{label}.f32").write_bytes(expected[label])
        rows.append(
            {
                "label": label,
                "file": f"{label}.f32",
                "frames": frames,
                "channels": channels,
            }
        )
    (cache / "stems.json").write_text(
        json.dumps(
            {
                "version": 1,
                "key": key,
                "sample_rate": rate,
                "channels": channels,
                "frames": frames,
                "stems": rows,
                "device": "cpu",
                "elapsed_seconds": 0.1,
            }
        )
    )
    store.update(project.id, document={"stemCacheKey": key})
    project = store.get(project.id)
    client = TestClient(create_app(settings))
    return client, project, expected, frames, channels


def test_stem_pcm_honors_http_range_byte_exactly(tmp_path: Path) -> None:
    client, project, expected, frames, channels = make_stem_workspace(tmp_path)
    frame_size = channels * 4
    start, end = 512 * frame_size, 767 * frame_size + frame_size - 1
    with client:
        metadata = client.get(f"/api/projects/{project.id}/stems")
        assert metadata.status_code == 200
        # A v1 cache has no stemModel document field; the route recovers the
        # implicit Demucs model from the cache metadata.
        assert metadata.json()["model"] == "htdemucs_ft"
        assert metadata.json()["active_model"] == "htdemucs_ft"
        for label in STEM_LABELS:
            response = client.get(
                f"/api/projects/{project.id}/stems/{label}/pcm",
                headers={"Range": f"bytes={start}-{end}"},
            )
            assert response.status_code == 206, (label, response.text)
            assert response.content == expected[label][start : end + 1]
            assert response.headers["content-range"] == (
                f"bytes {start}-{end}/{frames * frame_size}"
            )
            assert response.headers["accept-ranges"] == "bytes"
            assert response.headers["x-frame-start"] == "512"
            assert response.headers["x-frame-end"] == "768"
            assert response.headers["x-frame-count"] == "256"
            assert response.headers["x-stem-label"] == label


def test_stem_pcm_416_and_no_range_and_query_paths(tmp_path: Path) -> None:
    client, project, expected, frames, channels = make_stem_workspace(tmp_path)
    frame_size = channels * 4
    total = frames * frame_size
    with client:
        unsatisfiable = client.get(
            f"/api/projects/{project.id}/stems/bass/pcm",
            headers={"Range": f"bytes={total}-{total + 10}"},
        )
        assert unsatisfiable.status_code == 416
        assert unsatisfiable.headers["content-range"] == f"bytes */{total}"
        assert unsatisfiable.headers["accept-ranges"] == "bytes"
        assert "outside" in unsatisfiable.json()["detail"]

        full = client.get(f"/api/projects/{project.id}/stems/bass/pcm")
        assert full.status_code == 200
        assert full.content == expected["bass"]
        assert "content-range" not in full.headers

        query = client.get(
            f"/api/projects/{project.id}/stems/bass/pcm",
            params={"start": 100, "end": 200},
        )
        assert query.status_code == 200
        assert query.content == expected["bass"][100 * frame_size : 200 * frame_size]
        assert query.headers["x-frame-count"] == "100"
