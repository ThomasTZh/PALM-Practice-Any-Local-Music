"""Outer-window math for bounded separation (M2.5, milestone2.md §7.2).

This module is deliberately torch-free: the windowed inference adapter
runs in the isolated analysis environment and loads this module by file
path (the same boundary pattern as the M2.3 model registry). All math
is numpy and unit-tested in the main environment.

The adapter processes 120 s outer windows with an 8 s overlap. Each
window's output is blended with a complementary raised-cosine weight
pair, accumulated in float64, divided, and the non-overlap prefix is
finalized to the staged output files incrementally — only the active
window and the overlap tail stay in memory.
"""

from __future__ import annotations

import numpy as np

#: Version of the outer-window policy (window/overlap/blend scheme).
WINDOW_POLICY_VERSION = "outer-window-v1"


def window_schedule(
    total_frames: int, window_frames: int, overlap_frames: int
) -> list[tuple[int, int]]:
    """(offset, length) pairs for every outer window of a track.

    Windows advance by ``window_frames − overlap_frames``; the last
    window is truncated to the track end. There are never empty
    windows, and a track shorter than one window yields a single
    window covering the whole track.
    """
    if total_frames <= 0:
        raise ValueError(f"total_frames must be positive, got {total_frames}")
    if window_frames <= 0:
        raise ValueError(f"window_frames must be positive, got {window_frames}")
    if not 0 <= overlap_frames < window_frames:
        raise ValueError(
            f"overlap_frames must be in [0, window_frames), "
            f"got overlap={overlap_frames} window={window_frames}"
        )
    stride = window_frames - overlap_frames
    windows: list[tuple[int, int]] = []
    offset = 0
    while offset < total_frames:
        length = min(window_frames, total_frames - offset)
        windows.append((offset, length))
        if offset + length >= total_frames:
            break
        offset += stride
    return windows


def outer_window_weight(
    length: int, overlap: int, is_first: bool, is_last: bool
) -> np.ndarray:
    """Complementary raised-cosine weight for one outer window.

    - Leading ramp (skipped for the first window):
      ``0.5 − 0.5·cos(πj/(O−1))`` for ``j = 0..O−1`` (rises 0 → 1).
    - Middle: 1.
    - Trailing ramp (skipped for the last window):
      ``0.5 + 0.5·cos(πj/(O−1))`` (falls 1 → 0), with ``j`` indexed from
      the start of the overlap region.

    Ramps are always computed against the full overlap ``O`` (phase
    ``j/(O−1)``), so a truncated last window shorter than the overlap
    keeps the same phase as its neighbor's trailing ramp: at every
    shared sample of two adjacent windows the weights sum to exactly 1
    and never to 0.
    """
    if length <= 0:
        raise ValueError(f"length must be positive, got {length}")
    if overlap < 2:
        raise ValueError(f"overlap must be at least 2, got {overlap}")
    weight = np.ones(length, dtype=np.float64)
    if not is_first:
        ramp_len = min(overlap, length)
        j = np.arange(ramp_len)
        weight[:ramp_len] = 0.5 - 0.5 * np.cos(np.pi * j / (overlap - 1))
    if not is_last:
        ramp_len = min(overlap, length)
        j = np.arange(ramp_len)
        weight[length - ramp_len :] = 0.5 + 0.5 * np.cos(np.pi * j / (overlap - 1))
    return weight


def pre_scale(x: np.ndarray, mean: float, scale: float) -> np.ndarray:
    """Global-profile pre-scale: ``(x − mean) × scale`` (spec §7.2.3).

    Float32 in, float32 out — the model's domain. The same ``mean`` and
    ``scale`` are applied to every window of the run.
    """
    if scale <= 0:
        raise ValueError(f"scale must be positive, got {scale}")
    arr = np.asarray(x, dtype=np.float32)
    return (arr - np.float32(mean)) * np.float32(scale)


def restore_scale(y: np.ndarray, mean: float, scale: float) -> np.ndarray:
    """Undo the pre-scale before publication: ``y / scale + mean``
    (spec §7.2.6). Exact linear inverse of :func:`pre_scale` in exact
    arithmetic."""
    if scale <= 0:
        raise ValueError(f"scale must be positive, got {scale}")
    arr = np.asarray(y, dtype=np.float32)
    return (arr / np.float32(scale)) + np.float32(mean)


def accumulate_overlap(
    pending_sum: np.ndarray,
    pending_weight: np.ndarray,
    stems: np.ndarray,
    weight: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Merge one window's weighted output into the pending region.

    ``pending_sum`` / ``pending_weight`` cover the overlap tail carried
    from the previous window, starting at this window's offset
    (``P = pending_weight.size`` samples). ``stems`` is the window's
    output of shape ``(sources, channels, L)`` and ``weight`` its outer
    window weight of length ``L`` (with ``L ≥ P``). Returns the weighted
    partial sum and the accumulated weight over the full ``[0, L)``
    region, in float64.
    """
    if stems.ndim != 3:
        raise ValueError(f"stems must be (sources, channels, frames), got {stems.shape}")
    sources, channels, length = stems.shape
    pending_sources, pending_channels, pending_frames = pending_sum.shape
    if (pending_sources, pending_channels) != (sources, channels):
        raise ValueError("pending and window shapes must match on (sources, channels)")
    if pending_weight.size != pending_frames:
        raise ValueError("pending_weight must cover the pending region")
    if weight.size != length:
        raise ValueError("weight must cover the full window")
    if pending_frames > length:
        raise ValueError("the pending tail cannot exceed the window length")

    out = np.zeros((sources, channels, length), dtype=np.float64)
    acc_weight = np.zeros(length, dtype=np.float64)
    if pending_frames > 0:
        out[:, :, :pending_frames] += pending_sum
        acc_weight[:pending_frames] += pending_weight
    out += stems.astype(np.float64) * weight.astype(np.float64)[None, None, :]
    acc_weight += weight.astype(np.float64)
    return out, acc_weight


def finalize_region(
    region_sum: np.ndarray, region_weight: np.ndarray, prefix_frames: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Divide a pending region and split it into finalized prefix and
    the overlap tail to carry into the next window.

    Returns ``(finalized, tail_sum, tail_weight)`` where ``finalized``
    has ``prefix_frames`` frames (float64, ready to write) and the tail
    covers the remaining frames. Raises when the accumulated weight has
    a zero in the finalized prefix (cannot happen with
    :func:`outer_window_weight`, guarded for safety).
    """
    total = region_weight.size
    if not 0 <= prefix_frames <= total:
        raise ValueError(f"prefix_frames must be in [0, {total}], got {prefix_frames}")
    if prefix_frames > 0:
        if np.any(region_weight[:prefix_frames] <= 0):
            raise ValueError("accumulated weight must be positive in the finalized region")
        finalized = region_sum[:, :, :prefix_frames] / region_weight[:prefix_frames][
            None, None, :
        ]
    else:
        finalized = region_sum[:, :, :0]
    return finalized, region_sum[:, :, prefix_frames:], region_weight[prefix_frames:]
