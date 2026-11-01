"""Stem waveform peaks: BSPK bytes, headers, caching and 404s (t27)."""

from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from basseparate import stems
from basseparate.peaks import (
    PEAK_BUCKET_SIZES,
    PEAK_HEADER_SIZE,
    PEAK_MAGIC,
    PEAK_VERSION,
    compute_peaks,
    decode_peaks,
    encode_peaks,
)

from .test_range_http import make_stem_workspace


def quantise(values: NDArray[np.float32]) -> NDArray[np.float32]:
    scaled = np.clip(values.astype(np.float64) * 32767.0, -32767.0, 32767.0)
    return (np.round(scaled) / 32767.0).astype(np.float32)


def reference(pcm: NDArray[np.float32], bucket_size: int) -> tuple[NDArray, NDArray]:
    frames, channels = pcm.shape
    count = math.ceil(frames / bucket_size)
    mins = np.zeros((count, channels), dtype=np.float32)
    maxs = np.zeros((count, channels), dtype=np.float32)
    for bucket in range(count):
        block = pcm[bucket * bucket_size : (bucket + 1) * bucket_size]
        mins[bucket] = block.min(axis=0)
        maxs[bucket] = block.max(axis=0)
    return mins, maxs


def peak_file(root: Path, key: str, label: str, buckets: int) -> Path:
    return root / "stems" / key / f"peaks-{label}-{buckets}.bin"


def read_stem(root: Path, key: str, label: str, channels: int) -> NDArray[np.float32]:
    payload = (root / "stems" / key / f"{label}.f32").read_bytes()
    return np.frombuffer(payload, dtype="<f4").reshape(-1, channels)


def test_all_labels_all_bucket_sizes_match_the_recomputed_reference(tmp_path: Path) -> None:
    client, project, _expected, frames, channels = make_stem_workspace(tmp_path)
    settings_root = tmp_path / "data"
    key = project.document["stemCacheKey"]
    with client:
        for label in ("drums", "bass", "other", "vocals"):
            pcm = read_stem(settings_root, key, label, channels)
            for buckets in PEAK_BUCKET_SIZES:
                response = client.get(
                    f"/api/projects/{project.id}/stems/{label}/peaks",
                    params={"buckets": buckets},
                )
                assert response.status_code == 200, (label, buckets, response.text)
                assert response.headers["content-type"] == "application/octet-stream"
                assert response.headers["x-bucket-size"] == str(buckets)
                assert response.headers["x-channels"] == str(channels)
                assert response.headers["x-sample-rate"] == "48000"
                assert response.headers["x-stem-label"] == label
                decoded = decode_peaks(response.content)
                assert decoded.bucket_size == buckets
                assert decoded.channels == channels
                assert decoded.sample_rate == 48_000
                expected_min, expected_max = reference(pcm, buckets)
                np.testing.assert_array_equal(decoded.mins, quantise(expected_min))
                np.testing.assert_array_equal(decoded.maxs, quantise(expected_max))
                # The endpoint serves the same pure BSPK container, byte for byte.
                assert response.content == encode_peaks(
                    compute_peaks(pcm, buckets), sample_rate=48_000
                )
                assert len(response.content) == (
                    PEAK_HEADER_SIZE + decoded.bucket_count * channels * 4
                )
                assert response.content[:4] == PEAK_MAGIC
                magic, version, header_channels, _reserved, rate, count, per_bucket = (
                    struct.unpack_from("<4sBBHIII", response.content, 0)
                )
                assert (magic, version, header_channels, rate) == (
                    PEAK_MAGIC,
                    PEAK_VERSION,
                    channels,
                    48_000,
                )
                assert per_bucket == buckets
                assert count == decoded.bucket_count == math.ceil(frames / buckets)


def test_second_request_uses_the_cached_file_without_recomputation(
    tmp_path: Path, monkeypatch
) -> None:
    client, project, _expected, _frames, _channels = make_stem_workspace(tmp_path)
    key = project.document["stemCacheKey"]
    root = tmp_path / "data"
    with client:
        first = client.get(f"/api/projects/{project.id}/stems/bass/peaks", params={"buckets": 1024})
        assert first.status_code == 200
        cached = peak_file(root, key, "bass", 1024)
        assert cached.is_file()

        def no_recompute(*args, **kwargs):
            raise AssertionError("a cached stem peak must not be recomputed")

        monkeypatch.setattr(stems, "compute_peaks_from_file", no_recompute)
        second = client.get(
            f"/api/projects/{project.id}/stems/bass/peaks", params={"buckets": 1024}
        )
        assert second.status_code == 200
        assert second.content == first.content


def test_a_truncated_cache_file_is_not_served_and_is_repaired(tmp_path: Path) -> None:
    client, project, _expected, _frames, _channels = make_stem_workspace(tmp_path)
    key = project.document["stemCacheKey"]
    root = tmp_path / "data"
    with client:
        first = client.get(f"/api/projects/{project.id}/stems/drums/peaks", params={"buckets": 256})
        assert first.status_code == 200
        path = peak_file(root, key, "drums", 256)
        path.write_bytes(first.content[: PEAK_HEADER_SIZE + 8])
        repaired = client.get(
            f"/api/projects/{project.id}/stems/drums/peaks", params={"buckets": 256}
        )
        assert repaired.status_code == 200
        assert repaired.content == first.content
        assert path.read_bytes() == first.content


def test_unknown_label_missing_stem_set_and_no_stem_project_are_404(tmp_path: Path) -> None:
    client, project, _expected, _frames, _channels = make_stem_workspace(tmp_path)
    with client:
        unknown = client.get(f"/api/projects/{project.id}/stems/guitar/peaks")
        assert unknown.status_code == 404
        assert "unknown stem" in unknown.json()["detail"]

        bad_bucket = client.get(
            f"/api/projects/{project.id}/stems/bass/peaks", params={"buckets": 999}
        )
        assert bad_bucket.status_code == 400
        assert "unsupported bucket" in bad_bucket.json()["detail"]

        # Remove the cache key: a project with no stem set has no stem peaks.
        from basseparate.projects import ProjectStore

        store = ProjectStore(tmp_path / "data" / "projects")
        current = store.get(project.id)
        document = {key: value for key, value in current.document.items() if key != "stemCacheKey"}
        store.save(current.model_copy(update={"document": document}))
        no_stems = client.get(f"/api/projects/{project.id}/stems/bass/peaks")
        assert no_stems.status_code == 404
        assert "no stem set" in no_stems.json()["detail"]

        # A cache key that points at no complete entry is also a 404.
        store = ProjectStore(tmp_path / "data" / "projects")
        current = store.get(project.id)
        store.update(project.id, document={**current.document, "stemCacheKey": "f" * 64})
        missing = client.get(f"/api/projects/{project.id}/stems/bass/peaks")
        assert missing.status_code == 404
        assert "missing or incomplete" in missing.json()["detail"]


def test_peak_headers_match_the_mix_peak_header_shape(tmp_path: Path) -> None:
    client, project, _expected, _frames, _channels = make_stem_workspace(tmp_path)
    with client:
        stem_response = client.get(
            f"/api/projects/{project.id}/stems/bass/peaks", params={"buckets": 1024}
        )
        assert stem_response.status_code == 200
        assert stem_response.headers["x-bucket-size"] == "1024"
        assert stem_response.headers["x-channels"] == "2"
        assert stem_response.headers["x-sample-rate"] == "48000"
        assert stem_response.headers["x-stem-label"] == "bass"
        assert stem_response.headers["cache-control"] == "private, max-age=3600"
