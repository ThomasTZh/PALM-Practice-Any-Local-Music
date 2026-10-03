"""Waveform pyramid engine tests (M1.8).

Covers the generation algorithm (spec §10.2): exact extrema vs a direct
numpy reference, no zero padding of partial buckets, block-boundary
invariance, odd channel counts, partial final buckets, multi-tile long
files, determinism, cancellation cleanup, and the validation helpers
(spec §10.4).
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

from basseparate.domain.waveform import (
    TILE_BUCKETS,
    WAVEFORM_CACHE_VERSION,
    WaveformManifest,
    expected_levels,
    tile_byte_count,
    validate_manifest,
)
from basseparate.media.waveform import (
    WaveformCancelledError,
    WaveformFailedError,
    build_waveform_cache,
    validate_tile_bytes,
)


def _sine_pgm(frames: int, channels: int, rate: int = 44100) -> np.ndarray:
    t = np.arange(frames, dtype="<f8") / rate
    mono = 0.5 * np.sin(2.0 * np.pi * 440.0 * t).astype("<f4")
    return np.repeat(mono[:, None], channels, axis=1).ravel().astype("<f4")


def _build(
    tmp_path: Path,
    samples: np.ndarray,
    *,
    channel_count: int,
    block_bytes: int = 4 * 1024 * 1024,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
    source_hash: str | None = None,
    name: str = "cache",
) -> WaveformManifest:
    src = tmp_path / f"src-{name}.pcm"
    data = samples.tobytes()
    src.write_bytes(data)
    frame_count = len(data) // (channel_count * 4)
    digest = hashlib.sha256(data).hexdigest()
    return build_waveform_cache(
        src,
        tmp_path / name,
        source_hash=source_hash if source_hash is not None else digest,
        sample_rate=44100,
        frame_count=frame_count,
        channel_count=channel_count,
        block_bytes=block_bytes,
        cancel_event=cancel_event,
        on_progress=on_progress,
    )


def _tile(cache_dir: Path, level: int, index: int, channels: int = 2) -> np.ndarray:
    path = cache_dir / f"level_{level}" / f"tile_{index:06d}.bin"
    return np.fromfile(path, dtype="<f4").reshape(-1, channels, 2)


def _all_tiles(cache_dir: Path, manifest: WaveformManifest) -> dict[int, bytes]:
    out: dict[int, bytes] = {}
    for index, level in enumerate(manifest.levels):
        for tile_index in range(level.tile_count):
            out[(index, tile_index)] = (
                cache_dir / f"level_{index}" / f"tile_{tile_index:06d}.bin"
            ).read_bytes()
    return out


class TestExpectedLevels:
    def test_single_bucket(self) -> None:
        levels = expected_levels(64)
        assert len(levels) == 1
        assert levels[0].bucket_count == 1
        assert levels[0].final_tile_buckets == 1

    def test_partial_single_bucket(self) -> None:
        levels = expected_levels(63)
        assert len(levels) == 1
        assert levels[0].bucket_count == 1

    def test_one_tile_boundary(self) -> None:
        levels = expected_levels(64 * TILE_BUCKETS)
        assert len(levels) == 1
        assert levels[0].tile_count == 1

    def test_two_levels(self) -> None:
        levels = expected_levels(64 * TILE_BUCKETS + 1)
        assert len(levels) == 2
        assert levels[0].tile_count == 2
        assert levels[1].bucket_frame_count == 256
        assert levels[1].tile_count == 1

    def test_long_file_geometry(self) -> None:
        # 1.2 M frames needs three levels (level 1 has 4688 buckets > 4096).
        levels = expected_levels(1_200_000)
        assert [lv.bucket_frame_count for lv in levels] == [64, 256, 1024]
        assert [lv.bucket_count for lv in levels] == [18750, 4688, 1172]
        assert [lv.tile_count for lv in levels] == [5, 2, 1]
        assert [lv.final_tile_buckets for lv in levels] == [2366, 592, 1172]

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError):
            expected_levels(0)


class TestLevelZeroAccuracy:
    def test_sine_extrema_match_reference(self, tmp_path: Path) -> None:
        frames, channels = 64 * 10 + 7, 2
        samples = _sine_pgm(frames, channels)
        manifest = _build(tmp_path, samples, channel_count=channels)
        assert manifest.levels[0].bucket_count == 11

        reference = samples[: 64 * 10 * channels].reshape(-1, channels).reshape(-1, 64, channels)
        tile = _tile(tmp_path / "cache", 0, 0)
        for bucket in range(10):
            for channel in range(channels):
                ref_min = reference[bucket, :, channel].min()
                ref_max = reference[bucket, :, channel].max()
                assert tile[bucket, channel, 0] == pytest.approx(ref_min, abs=1e-7)
                assert tile[bucket, channel, 1] == pytest.approx(ref_max, abs=1e-7)

    def test_partial_final_bucket_uses_real_samples_only(self, tmp_path: Path) -> None:
        # 10 full buckets + 5 frames; the last bucket must cover exactly
        # those 5 frames (no zero padding — an all-positive tail keeps a
        # positive minimum).
        channels = 2
        samples = np.full((64 * 10 + 5) * channels, 0.25, dtype="<f4")
        samples[: 64 * 10 * channels] = -0.5
        _build(tmp_path, samples, channel_count=channels)
        tile = _tile(tmp_path / "cache", 0, 0)
        last = tile[-1]
        assert (last[:, 0] == 0.25).all()
        assert (last[:, 1] == 0.25).all()

    def test_all_positive_signal_not_skewed_by_padding(self, tmp_path: Path) -> None:
        samples = np.linspace(0.1, 0.9, 64 * 3 + 11, dtype="<f4")
        _build(tmp_path, samples, channel_count=1)
        tile = _tile(tmp_path / "cache", 0, 0)
        assert (tile[..., 0] > 0).all()  # minima stay positive
        assert (tile[..., 1] > 0).all()

    def test_all_negative_signal_not_skewed_by_padding(self, tmp_path: Path) -> None:
        samples = np.linspace(-0.9, -0.1, 64 * 3 + 11, dtype="<f4")
        _build(tmp_path, samples, channel_count=1)
        tile = _tile(tmp_path / "cache", 0, 0)
        assert (tile[..., 0] < 0).all()
        assert (tile[..., 1] < 0).all()


class TestAggregation:
    def test_level_one_is_extrema_of_four_level_zero(self, tmp_path: Path) -> None:
        channels = 2
        frames = 64 * (TILE_BUCKETS + 4)  # forces a second level
        rng = np.random.default_rng(7)
        samples = (rng.random((frames, channels), dtype="<f8") - 0.5).astype("<f4").ravel()
        manifest = _build(tmp_path, samples, channel_count=channels, name="cache2")
        assert len(manifest.levels) == 2

        level0 = _tile(tmp_path / "cache2", 0, 0)
        level1 = _tile(tmp_path / "cache2", 1, 0)
        for group in range(TILE_BUCKETS // 4):
            chunk = level0[group * 4 : group * 4 + 4]
            assert level1[group, :, 0] == pytest.approx(chunk[:, :, 0].min(axis=0), abs=1e-7)
            assert level1[group, :, 1] == pytest.approx(chunk[:, :, 1].max(axis=0), abs=1e-7)


class TestBlockBoundaryInvariance:
    @pytest.mark.parametrize(
        ("frames", "channels"),
        [(64 * 5 + 33, 2), (64 * 100 + 17, 3), (64 * 10, 8)],
    )
    def test_tiny_blocks_match_single_pass(
        self, tmp_path: Path, frames: int, channels: int
    ) -> None:
        rng = np.random.default_rng(11)
        samples = (rng.random((frames, channels), dtype="<f8") - 0.5).astype("<f4").ravel()
        # Three buckets worth of samples per "block" — forces carries at
        # every boundary, including mid-bucket and mid-channel cuts.
        tiny = 64 * channels * 3
        big = _build(tmp_path, samples, channel_count=channels, name="big")
        small = _build(tmp_path, samples, channel_count=channels, block_bytes=tiny, name="small")
        assert _all_tiles(tmp_path / "big", big) == _all_tiles(tmp_path / "small", small)
        assert big.levels == small.levels
        assert big.available_tiles == small.available_tiles

    def test_block_bytes_rounded_to_frame_boundary(self, tmp_path: Path) -> None:
        channels = 3
        samples = _sine_pgm(64 * 50, channels)
        # block_bytes not a multiple of frame_bytes (12) must still work.
        manifest = _build(
            tmp_path, samples, channel_count=channels, block_bytes=1000, name="odd"
        )
        assert manifest.final is True


class TestChannelCounts:
    @pytest.mark.parametrize("channels", [1, 2, 3, 8])
    def test_odd_and_wide_channel_counts(self, tmp_path: Path, channels: int) -> None:
        frames = 64 * 30 + 13
        rng = np.random.default_rng(channels)
        samples = (rng.random((frames, channels), dtype="<f8") - 0.5).astype("<f4").ravel()
        manifest = _build(tmp_path, samples, channel_count=channels, name=f"ch{channels}")
        assert manifest.channel_count == channels
        for index, level in enumerate(manifest.levels):
            for tile_index in range(level.tile_count):
                buckets = (
                    TILE_BUCKETS if tile_index < level.tile_count - 1 else level.final_tile_buckets
                )
                data = (
                    tmp_path / f"ch{channels}" / f"level_{index}" / f"tile_{tile_index:06d}.bin"
                ).read_bytes()
                assert len(data) == tile_byte_count(buckets, channels)
                validate_tile_bytes(data, len(data), channels)


class TestLongFile:
    def test_multi_tile_pyramid(self, tmp_path: Path) -> None:
        frames, channels = 1_200_000, 2
        rng = np.random.default_rng(42)
        samples = (rng.random((frames, channels), dtype="<f8") - 0.5).astype("<f4").ravel()
        manifest = _build(tmp_path, samples, channel_count=channels, name="long")
        assert manifest.final is True
        assert [lv.tile_count for lv in manifest.levels] == [5, 2, 1]
        # Availability is complete and monotonic.
        assert manifest.available_tiles["0"] == [[0, 4]]
        assert manifest.available_tiles["1"] == [[0, 1]]
        assert manifest.available_tiles["2"] == [[0, 0]]
        # Every tile validates.
        for index, level in enumerate(manifest.levels):
            for tile_index in range(level.tile_count):
                buckets = (
                    TILE_BUCKETS if tile_index < level.tile_count - 1 else level.final_tile_buckets
                )
                data = (
                    tmp_path / "long" / f"level_{index}" / f"tile_{tile_index:06d}.bin"
                ).read_bytes()
                assert len(data) == tile_byte_count(buckets, channels)
                validate_tile_bytes(data, len(data), channels)

    def test_progress_reaches_one(self, tmp_path: Path) -> None:
        samples = _sine_pgm(64 * 50, 2)
        seen: list[float] = []
        _build(tmp_path, samples, channel_count=2, on_progress=seen.append, name="prog")
        assert seen[-1] == 1.0
        assert seen == sorted(seen)


class TestDeterminism:
    def test_two_runs_byte_identical(self, tmp_path: Path) -> None:
        samples = _sine_pgm(64 * 40 + 21, 2)
        a = _build(tmp_path, samples, channel_count=2, name="a")
        b = _build(tmp_path, samples, channel_count=2, name="b")
        assert _all_tiles(tmp_path / "a", a) == _all_tiles(tmp_path / "b", b)


class TestFailureModes:
    def test_hash_mismatch_removes_cache(self, tmp_path: Path) -> None:
        samples = _sine_pgm(64 * 10, 2)
        with pytest.raises(WaveformFailedError, match="hash mismatch"):
            _build(
                tmp_path,
                samples,
                channel_count=2,
                source_hash="0" * 64,
                name="badhash",
            )
        assert not (tmp_path / "badhash").exists()

    def test_missing_source_fails(self, tmp_path: Path) -> None:
        with pytest.raises(WaveformFailedError):
            build_waveform_cache(
                tmp_path / "nope.pcm",
                tmp_path / "cache",
                source_hash="0" * 64,
                sample_rate=44100,
                frame_count=64,
                channel_count=2,
            )
        assert not (tmp_path / "cache").exists()

    def test_cancel_mid_build_removes_cache(self, tmp_path: Path) -> None:
        frames, channels = 1_000_000, 2
        rng = np.random.default_rng(5)
        samples = (rng.random((frames, channels), dtype="<f8") - 0.5).astype("<f4").ravel()
        event = threading.Event()

        def cancel_soon(fraction: float) -> None:
            if fraction >= 0.3:
                event.set()

        with pytest.raises(WaveformCancelledError):
            _build(
                tmp_path,
                samples,
                channel_count=channels,
                cancel_event=event,
                on_progress=cancel_soon,
                name="cancelled",
            )
        assert not (tmp_path / "cancelled").exists()

    def test_frame_count_mismatch_fails(self, tmp_path: Path) -> None:
        samples = _sine_pgm(64 * 10, 2)
        src = tmp_path / "src.pcm"
        src.write_bytes(samples.tobytes())
        digest = hashlib.sha256(samples.tobytes()).hexdigest()
        with pytest.raises(WaveformFailedError, match="frames, expected"):
            build_waveform_cache(
                src,
                tmp_path / "cache",
                source_hash=digest,
                sample_rate=44100,
                frame_count=64 * 11,  # wrong
                channel_count=2,
            )
        assert not (tmp_path / "cache").exists()


class TestValidation:
    def _good_tile(self) -> bytes:
        values = np.array([[[-0.5, 0.5], [-0.25, 0.25]], [[-1.0, 1.0], [0.0, 0.5]]], dtype="<f4")
        return values.tobytes()

    def test_valid_tile_passes(self) -> None:
        data = self._good_tile()
        validate_tile_bytes(data, len(data), 2)

    def test_wrong_length_rejected(self) -> None:
        with pytest.raises(ValueError, match="length"):
            validate_tile_bytes(self._good_tile()[:7], 8, 2)

    def test_non_finite_rejected(self) -> None:
        values = np.array([[[-0.5, 0.5], [-0.25, 0.25]]], dtype="<f4")
        values[0, 0, 1] = np.inf
        with pytest.raises(ValueError, match="non-finite"):
            validate_tile_bytes(values.tobytes(), values.nbytes, 2)

    def test_min_gt_max_rejected(self) -> None:
        values = np.array([[[-0.5, 0.5], [-0.25, 0.25]]], dtype="<f4")
        values[0, 1, 0] = 0.9  # min > max
        with pytest.raises(ValueError, match="minimum > maximum"):
            validate_tile_bytes(values.tobytes(), values.nbytes, 2)

    def _manifest(self, **overrides: object) -> WaveformManifest:
        base = {
            "cache_version": WAVEFORM_CACHE_VERSION,
            "source_hash": "ab" * 32,
            "sample_rate": 44100,
            "frame_count": 64 * 10,
            "channel_count": 2,
            "levels": expected_levels(64 * 10),
            "available_tiles": {"0": [[0, 0]]},
            "final": True,
        }
        base.update(overrides)
        return WaveformManifest(**base)

    def test_good_manifest_passes(self) -> None:
        validate_manifest(self._manifest(), source_hash="ab" * 32)

    def test_hash_mismatch(self) -> None:
        with pytest.raises(ValueError, match="hash"):
            validate_manifest(self._manifest(), source_hash="cd" * 32)

    def test_version_mismatch(self) -> None:
        with pytest.raises(ValueError, match="version"):
            validate_manifest(
                self._manifest(cache_version=99), source_hash="ab" * 32
            )

    def test_geometry_mismatch(self) -> None:
        with pytest.raises(ValueError, match="geometry"):
            validate_manifest(
                self._manifest(frame_count=64 * 11), source_hash="ab" * 32
            )

    def test_range_out_of_bounds(self) -> None:
        with pytest.raises(ValueError, match="availability"):
            validate_manifest(
                self._manifest(available_tiles={"0": [[0, 5]]}), source_hash="ab" * 32
            )

    def test_overlapping_ranges(self) -> None:
        with pytest.raises(ValueError, match="availability"):
            validate_manifest(
                self._manifest(available_tiles={"0": [[0, 2], [1, 3]]}),
                source_hash="ab" * 32,
            )

    def test_final_missing_tiles(self) -> None:
        frame_count = 64 * 2 * TILE_BUCKETS  # two level-0 tiles, one level-1 tile
        with pytest.raises(ValueError, match="missing tiles"):
            validate_manifest(
                self._manifest(
                    frame_count=frame_count,
                    levels=expected_levels(frame_count),
                    available_tiles={"0": [[0, 0]], "1": [[0, 0]]},
                    final=True,
                ),
                source_hash="ab" * 32,
            )
