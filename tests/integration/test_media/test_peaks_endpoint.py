"""Peak levels over HTTP: same bytes for the UI asset route and the project route."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from helpers import TONE_48K_STEREO, asset_pcm, import_path

from basseparate.peaks import PEAK_BUCKET_SIZES, decode_peaks

QUANT = 32767.0


def reference(path, channels: int, bucket_size: int) -> tuple[np.ndarray, np.ndarray]:
    pcm = np.fromfile(path, dtype="<f4").reshape(-1, channels)
    count = (pcm.shape[0] + bucket_size - 1) // bucket_size
    mins = np.zeros((count, channels), dtype=np.float64)
    maxs = np.zeros((count, channels), dtype=np.float64)
    for bucket in range(count):
        block = pcm[bucket * bucket_size : (bucket + 1) * bucket_size]
        mins[bucket] = block.min(axis=0)
        maxs[bucket] = block.max(axis=0)
    return (
        np.round(np.clip(mins * QUANT, -QUANT, QUANT)) / QUANT,
        np.round(np.clip(maxs * QUANT, -QUANT, QUANT)) / QUANT,
    )


@pytest.mark.parametrize("bucket_size", PEAK_BUCKET_SIZES)
def test_project_peaks_match_recomputed_reference(
    client: TestClient, settings, bucket_size: int
) -> None:
    payload = import_path(client, TONE_48K_STEREO)
    response = client.get(f"/api/projects/{payload['id']}/peaks/{bucket_size}")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/octet-stream"
    decoded = decode_peaks(response.content)
    assert decoded.sample_rate == 48_000
    assert decoded.channels == 2
    assert decoded.bucket_size == bucket_size
    expected_min, expected_max = reference(asset_pcm(settings, payload), 2, bucket_size)
    assert decoded.bucket_count == expected_min.shape[0]
    np.testing.assert_allclose(decoded.mins, expected_min, rtol=1e-6, atol=1e-7)
    np.testing.assert_allclose(decoded.maxs, expected_max, rtol=1e-6, atol=1e-7)


@pytest.mark.parametrize("bucket_size", PEAK_BUCKET_SIZES)
def test_asset_peaks_query_route_serves_identical_bytes(
    client: TestClient, bucket_size: int
) -> None:
    payload = import_path(client, TONE_48K_STEREO)
    asset_id = payload["audio"]["asset_id"]
    project_bytes = client.get(f"/api/projects/{payload['id']}/peaks/{bucket_size}").content
    asset_response = client.get(f"/api/assets/{asset_id}/peaks", params={"buckets": bucket_size})
    assert asset_response.status_code == 200
    assert asset_response.content == project_bytes
    decoded = decode_peaks(asset_response.content)
    assert decoded.bucket_size == bucket_size
    assert decoded.bucket_count == payload["audio"]["peaks"][str(bucket_size)]["count"]
    assert len(asset_response.content) == payload["audio"]["peaks"][str(bucket_size)]["byte_size"]


def test_default_asset_bucket_size_is_1024(client: TestClient) -> None:
    payload = import_path(client, TONE_48K_STEREO)
    response = client.get(f"/api/assets/{payload['audio']['asset_id']}/peaks")
    assert response.status_code == 200
    assert decode_peaks(response.content).bucket_size == 1024


def test_unsupported_bucket_size_is_a_clear_400(client: TestClient) -> None:
    payload = import_path(client, TONE_48K_STEREO)
    response = client.get(f"/api/projects/{payload['id']}/peaks/999")
    assert response.status_code == 400
    assert "unsupported bucket" in response.json()["detail"]
    response = client.get(
        f"/api/assets/{payload['audio']['asset_id']}/peaks", params={"buckets": 999}
    )
    assert response.status_code == 400


def test_unknown_asset_peaks_is_404(client: TestClient) -> None:
    assert client.get("/api/assets/missing/peaks").status_code == 404
