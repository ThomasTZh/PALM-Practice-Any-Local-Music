"""Unit tests for the outer-window math (M2.5, milestone2.md §7.2).

Covers:
- window_schedule: coverage, no gaps, no empty windows, exact multiples,
  short tracks, truncated last window, argument validation.
- outer_window_weight: complementary raised-cosine pairs (sum exactly 1,
  never 0 at shared samples), first/last window edges, truncated last
  window phase, single-window case, argument validation.
- pre_scale / restore_scale: linear round-trip in float32.
- accumulate_overlap / finalize_region: weighted overlap-add invariants,
  two-window blend of identical content reproduces the content, zero
  weight guard, shape validation.
"""

from __future__ import annotations

import numpy as np
import pytest

from basseparate.media.windowing import (
    WINDOW_POLICY_VERSION,
    accumulate_overlap,
    finalize_region,
    outer_window_weight,
    pre_scale,
    restore_scale,
    window_schedule,
)

RATE = 44100
WINDOW = 120 * RATE
OVERLAP = 8 * RATE


class TestWindowSchedule:
    def test_short_track_single_window(self) -> None:
        assert window_schedule(100, WINDOW, OVERLAP) == [(0, 100)]

    def test_exact_single_window(self) -> None:
        assert window_schedule(WINDOW, WINDOW, OVERLAP) == [(0, WINDOW)]

    def test_two_windows_with_truncated_last(self) -> None:
        windows = window_schedule(WINDOW + 1, WINDOW, OVERLAP)
        assert windows == [(0, WINDOW), (WINDOW - OVERLAP, OVERLAP + 1)]

    def test_coverage_and_order(self) -> None:
        total = 3 * WINDOW + 37
        windows = window_schedule(total, WINDOW, OVERLAP)
        assert windows[0][0] == 0
        assert windows[-1][0] + windows[-1][1] == total
        for (off_a, len_a), (off_b, _) in zip(windows, windows[1:], strict=False):
            assert off_b > off_a
            assert off_b <= off_a + len_a  # no gap
            assert off_b - off_a == WINDOW - OVERLAP  # constant stride
        for _, length in windows:
            assert 0 < length <= WINDOW

    def test_no_empty_windows(self) -> None:
        total = 5 * (WINDOW - OVERLAP)
        windows = window_schedule(total, WINDOW, OVERLAP)
        assert all(length > 0 for _, length in windows)
        assert windows[-1][0] + windows[-1][1] == total

    def test_invalid_arguments(self) -> None:
        with pytest.raises(ValueError):
            window_schedule(0, WINDOW, OVERLAP)
        with pytest.raises(ValueError):
            window_schedule(WINDOW, 0, OVERLAP)
        with pytest.raises(ValueError):
            window_schedule(WINDOW, WINDOW, WINDOW)
        with pytest.raises(ValueError):
            window_schedule(WINDOW, WINDOW, -1)


class TestOuterWindowWeight:
    def test_first_window_flat_start(self) -> None:
        weight = outer_window_weight(WINDOW, OVERLAP, is_first=True, is_last=False)
        assert weight[0] == 1.0
        assert weight[: OVERLAP // 2].min() > 0.99
        assert weight[-1] == pytest.approx(0.0, abs=1e-12)

    def test_last_window_flat_end(self) -> None:
        # The last window has no trailing ramp: it ends flat at 1.0
        # (the track ends there; there is nothing left to blend with).
        weight = outer_window_weight(WINDOW, OVERLAP, is_first=False, is_last=True)
        assert weight[0] == pytest.approx(0.0, abs=1e-12)
        assert weight[-1] == 1.0
        np.testing.assert_array_equal(weight[-OVERLAP // 2 :], 1.0)

    def test_middle_window_shape(self) -> None:
        weight = outer_window_weight(WINDOW, OVERLAP, is_first=False, is_last=False)
        assert weight[0] == pytest.approx(0.0, abs=1e-12)
        assert weight[-1] == pytest.approx(0.0, abs=1e-12)
        assert weight[OVERLAP : WINDOW - OVERLAP].max() == 1.0
        assert weight[OVERLAP : WINDOW - OVERLAP].min() == 1.0

    def test_single_window_all_ones(self) -> None:
        weight = outer_window_weight(1000, 20, is_first=True, is_last=True)
        np.testing.assert_array_equal(weight, np.ones(1000))

    def test_complementarity_full_neighbors(self) -> None:
        prev = outer_window_weight(WINDOW, OVERLAP, is_first=True, is_last=False)
        nxt = outer_window_weight(WINDOW, OVERLAP, is_first=False, is_last=True)
        shared = prev[-OVERLAP:] + nxt[:OVERLAP]
        np.testing.assert_allclose(shared, np.ones(OVERLAP), atol=1e-12)
        assert shared.min() > 0.0

    def test_complementarity_truncated_last_window(self) -> None:
        prev = outer_window_weight(WINDOW, OVERLAP, is_first=True, is_last=False)
        last_len = 3 * RATE  # shorter than the overlap
        last = outer_window_weight(last_len, OVERLAP, is_first=False, is_last=True)
        # The last window starts stride = WINDOW − OVERLAP after the
        # previous one, so the shared region is the first last_len
        # samples of the previous window's full OVERLAP tail.
        shared = prev[WINDOW - OVERLAP : WINDOW - OVERLAP + last_len] + last[:last_len]
        np.testing.assert_allclose(shared, np.ones(last_len), atol=1e-12)
        assert shared.min() > 0.0

    def test_weight_monotonic_ramps(self) -> None:
        weight = outer_window_weight(WINDOW, OVERLAP, is_first=False, is_last=False)
        leading = weight[:OVERLAP]
        trailing = weight[WINDOW - OVERLAP :]
        assert np.all(np.diff(leading) > 0)
        assert np.all(np.diff(trailing) < 0)

    def test_invalid_arguments(self) -> None:
        with pytest.raises(ValueError):
            outer_window_weight(0, OVERLAP, True, True)
        with pytest.raises(ValueError):
            outer_window_weight(100, 1, True, True)


class TestScaleRoundTrip:
    def test_round_trip(self) -> None:
        rng = np.random.default_rng(7)
        x = (rng.standard_normal((4, 2, 10_000)) * 0.3).astype(np.float32)
        restored = restore_scale(pre_scale(x, mean=0.05, scale=3.7), mean=0.05, scale=3.7)
        np.testing.assert_allclose(restored, x, rtol=1e-6, atol=1e-7)

    def test_shift_and_gain(self) -> None:
        x = np.linspace(-1, 1, 1000, dtype=np.float32)
        scaled = pre_scale(x, mean=0.2, scale=2.5)
        np.testing.assert_allclose(scaled, (x - 0.2) * 2.5, rtol=1e-6)

    def test_non_positive_scale_rejected(self) -> None:
        x = np.zeros(4, dtype=np.float32)
        with pytest.raises(ValueError):
            pre_scale(x, 0.0, 0.0)
        with pytest.raises(ValueError):
            restore_scale(x, 0.0, -1.0)


class TestAccumulateAndFinalize:
    def test_first_window_no_pending(self) -> None:
        stems = np.ones((4, 2, 100), dtype=np.float32)
        weight = np.full(100, 0.5)
        out, acc = accumulate_overlap(
            np.zeros((4, 2, 0), dtype=np.float64), np.zeros(0), stems, weight
        )
        np.testing.assert_allclose(out, 0.5)
        np.testing.assert_allclose(acc, 0.5)

    def test_overlap_region_sums_both_windows(self) -> None:
        pending_frames = 30
        pending_sum = np.full((2, 1, pending_frames), 1.0)
        pending_weight = np.ones(pending_frames)
        stems = np.full((2, 1, 50), 3.0, dtype=np.float32)
        weight = np.full(50, 0.5)
        out, acc = accumulate_overlap(pending_sum, pending_weight, stems, weight)
        # Overlap: 1.0×1.0 + 3.0×0.5 = 2.5; outside: 3.0×0.5 = 1.5.
        np.testing.assert_allclose(out[:, :, :pending_frames], 2.5)
        np.testing.assert_allclose(out[:, :, pending_frames:], 1.5)
        # Overlap: 1.0 + 0.5; outside: 0.5.
        np.testing.assert_allclose(acc[:pending_frames], 1.5)
        np.testing.assert_allclose(acc[pending_frames:], 0.5)

    def test_two_window_blend_of_identical_content(self) -> None:
        # A constant signal through two adjacent windows must come out
        # unchanged: the complementary weights average identically.
        value = 0.7
        first = outer_window_weight(100, 20, is_first=True, is_last=False)
        second = outer_window_weight(100, 20, is_first=False, is_last=True)
        stems = np.full((1, 1, 100), value, dtype=np.float32)

        out, acc = accumulate_overlap(
            np.zeros((1, 1, 0)), np.zeros(0), stems, first
        )
        finalized, tail_sum, tail_w = finalize_region(out, acc, prefix_frames=80)
        np.testing.assert_allclose(finalized, value, rtol=1e-6)  # float32 stems

        out2, acc2 = accumulate_overlap(tail_sum, tail_w, stems, second)
        finalized2, tail2_sum, tail2_w = finalize_region(out2, acc2, prefix_frames=100)
        np.testing.assert_allclose(finalized2, value, rtol=1e-6)
        assert tail2_sum.size == 0
        assert tail2_w.size == 0

    def test_zero_weight_guard(self) -> None:
        region_sum = np.zeros((1, 1, 10))
        region_weight = np.ones(10)
        region_weight[3] = 0.0
        with pytest.raises(ValueError, match="positive"):
            finalize_region(region_sum, region_weight, prefix_frames=10)

    def test_prefix_bounds(self) -> None:
        region_sum = np.zeros((1, 1, 10))
        region_weight = np.ones(10)
        with pytest.raises(ValueError):
            finalize_region(region_sum, region_weight, prefix_frames=-1)
        with pytest.raises(ValueError):
            finalize_region(region_sum, region_weight, prefix_frames=11)
        empty, tail_sum, tail_w = finalize_region(region_sum, region_weight, 0)
        assert empty.size == 0
        assert tail_sum.size == 10

    def test_shape_validation(self) -> None:
        stems = np.zeros((4, 2, 10), dtype=np.float32)
        with pytest.raises(ValueError, match="sources, channels"):
            accumulate_overlap(np.zeros((4, 2, 0)), np.zeros(0), stems[:, 0, :], np.ones(10))
        with pytest.raises(ValueError, match="weight must cover"):
            accumulate_overlap(np.zeros((4, 2, 0)), np.zeros(0), stems, np.ones(9))
        with pytest.raises(ValueError, match="exceed the window"):
            accumulate_overlap(
                np.zeros((4, 2, 11)), np.ones(11), stems, np.ones(10)
            )


class TestPolicyVersion:
    def test_version_string(self) -> None:
        assert WINDOW_POLICY_VERSION == "outer-window-v1"
