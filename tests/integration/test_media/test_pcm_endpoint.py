"""Ranged PCM: exact frames, exact bytes, clear out-of-range errors."""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient
from helpers import TONE_44K, TONE_48K_STEREO, asset_pcm, import_path, pcm_bytes


def test_full_range_returns_every_frame(client: TestClient, settings) -> None:
    payload = import_path(client, TONE_44K)
    total = payload["audio"]["frames"]
    response = client.get(f"/api/projects/{payload['id']}/pcm")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-frame-start"] == "0"
    assert response.headers["x-frame-end"] == str(total)
    assert response.headers["x-frame-count"] == str(total)
    assert response.headers["x-sample-rate"] == "44100"
    assert response.headers["x-channels"] == "1"
    assert response.content == asset_pcm(settings, payload).read_bytes()


def test_stereo_range_returns_exactly_the_requested_interleaved_frames(
    client: TestClient, settings
) -> None:
    payload = import_path(client, TONE_48K_STEREO)
    pcm = asset_pcm(settings, payload)
    start, end = 1_234, 5_678
    response = client.get(f"/api/projects/{payload['id']}/pcm", params={"start": start, "end": end})
    assert response.status_code == 200, response.text
    assert response.headers["x-frame-count"] == str(end - start)
    assert response.headers["x-channels"] == "2"
    assert response.content == pcm_bytes(pcm, start, end, channels=2)
    frames = np.frombuffer(response.content, dtype="<f4").reshape(end - start, 2)
    reference = np.fromfile(pcm, dtype="<f4").reshape(-1, 2)[start:end]
    np.testing.assert_array_equal(frames, reference)


def test_two_adjacent_ranges_reassemble_into_the_whole_file(client: TestClient, settings) -> None:
    payload = import_path(client, TONE_48K_STEREO)
    pcm = asset_pcm(settings, payload)
    total = payload["audio"]["frames"]
    first = client.get(f"/api/projects/{payload['id']}/pcm", params={"start": 0, "end": 20_000})
    second = client.get(
        f"/api/projects/{payload['id']}/pcm", params={"start": 20_000, "end": total}
    )
    assert first.content + second.content == pcm.read_bytes()


def test_empty_range_is_valid(client: TestClient) -> None:
    payload = import_path(client, TONE_44K)
    total = payload["audio"]["frames"]
    response = client.get(
        f"/api/projects/{payload['id']}/pcm", params={"start": total, "end": total}
    )
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["x-frame-count"] == "0"


def test_out_of_range_requests_are_rejected_with_a_clear_message(client: TestClient) -> None:
    payload = import_path(client, TONE_44K)
    total = payload["audio"]["frames"]
    cases = [
        ({"start": total + 1, "end": total + 2}, "outside"),
        ({"start": 0, "end": total + 1}, "outside"),
        ({"start": -1, "end": 10}, "negative"),
        ({"start": 100, "end": 10}, "before"),
    ]
    for params, fragment in cases:
        response = client.get(f"/api/projects/{payload['id']}/pcm", params=params)
        assert response.status_code == 416, (params, response.text)
        assert fragment in response.json()["detail"]


def test_invalid_query_types_are_validation_errors(client: TestClient) -> None:
    payload = import_path(client, TONE_44K)
    response = client.get(f"/api/projects/{payload['id']}/pcm", params={"start": "abc"})
    assert response.status_code == 422
    assert "start" in response.text


def test_unknown_project_is_404(client: TestClient) -> None:
    assert client.get("/api/projects/nope/pcm").status_code == 404
