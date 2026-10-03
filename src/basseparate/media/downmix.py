"""Monitoring downmix matrices (M1.7, milestone1.md §9.3).

The monitoring transform converts a multichannel canonical source to a
stereo monitoring representation. It is a documented, row-normalized
transform: it never modifies the canonical source.

Standard layouts (spec §9.3):

- Front left contributes to left.
- Front right contributes to right.
- Center contributes to both at 0.7071.
- Left surround/rear contributes to left at 0.7071.
- Right surround/rear contributes to right at 0.7071.
- LFE contributes to both at 0.5.

Each matrix row is normalized by the sum of its absolute coefficients, so
full-scale aligned input channels do not exceed full scale solely due to
summation.

Unknown layouts: the canonical channels are preserved and the user selects
the left/right source channels for monitoring. Speaker identities are never
guessed from the channel count alone.

FFmpeg's ``pan`` filter implements the matrices. Its channel expressions
accept only ``coef*channel`` terms joined by ``+``/``-`` (no parentheses,
no division), so the coefficients are precomputed here and emitted as
literal terms. The ``|`` separators are part of the pan filter's own
argument syntax and are passed verbatim as the ``-af`` value (no shell is
involved, so no escaping is needed).
"""

from __future__ import annotations

from collections.abc import Sequence

#: Version of the downmix matrix tables (recorded in the transform key).
MATRIX_VERSION = 1

DownmixMode = str  # "standard_5_1" | "manual"

#: One (source channel index, coefficient) pair.
Term = tuple[int, float]
#: One output-channel row: the terms summed to produce it.
DownmixRow = tuple[Term, ...]

#: Layouts the spec's standard matrix applies to (probed layout name).
STANDARD_51_LAYOUTS: frozenset[str] = frozenset({"5.1"})

CENTER_COEF = 0.7071
SURROUND_COEF = 0.7071
LFE_COEF = 0.5


class MonitorSelectionError(Exception):
    """An unknown layout has no user L/R monitoring selection."""


def normalize_row(row: Sequence[Term]) -> DownmixRow:
    """Scale a row so the sum of absolute coefficients is 1.

    An empty row or a row whose coefficients sum to zero is invalid for a
    monitoring output channel.
    """
    total = sum(abs(coef) for _, coef in row)
    if total <= 0.0:
        raise ValueError("a downmix row must have a nonzero sum of absolute coefficients")
    return tuple((ch, coef / total) for ch, coef in row)


def standard_51_matrix() -> tuple[DownmixRow, DownmixRow]:
    """Row-normalized 5.1 → stereo matrix.

    Channel order (FFmpeg 5.1): 0 FL, 1 FR, 2 C, 3 Ls, 4 Rs, 5 LFE.
    Returns ``(left_row, right_row)``.
    """
    left = normalize_row([(0, 1.0), (2, CENTER_COEF), (3, SURROUND_COEF), (5, LFE_COEF)])
    right = normalize_row([(1, 1.0), (2, CENTER_COEF), (4, SURROUND_COEF), (5, LFE_COEF)])
    return left, right


def manual_matrix(left_channel: int, right_channel: int) -> tuple[DownmixRow, DownmixRow]:
    """Two-channel extraction matrix for unknown layouts (coefficient 1.0)."""
    return normalize_row([(left_channel, 1.0)]), normalize_row([(right_channel, 1.0)])


def resolve_downmix(
    channel_count: int,
    channel_layout: str | None,
    left_channel: int | None,
    right_channel: int | None,
) -> tuple[DownmixMode, DownmixRow, DownmixRow] | None:
    """Resolve the monitoring transform for a source.

    Returns ``None`` when no downmix is needed (mono/stereo: the canonical
    asset is the monitoring representation, spec §9.1). Otherwise returns
    ``(mode, left_row, right_row)``.

    Raises ``MonitorSelectionError`` for an unknown multichannel layout
    without a user L/R selection.
    """
    if channel_count <= 2:
        return None
    if channel_count == 6 and channel_layout in STANDARD_51_LAYOUTS:
        left, right = standard_51_matrix()
        return "standard_5_1", left, right
    if left_channel is None or right_channel is None:
        raise MonitorSelectionError(
            "this source has no standard monitoring layout; select the left and "
            "right source channels for monitoring"
        )
    if not 0 <= left_channel < channel_count or not 0 <= right_channel < channel_count:
        raise MonitorSelectionError(
            f"monitoring channels {left_channel}/{right_channel} are outside the "
            f"source's {channel_count} channels"
        )
    left, right = manual_matrix(left_channel, right_channel)
    return "manual", left, right


def _format_coef(value: float) -> str:
    """Format a coefficient for a pan expression (6 decimals, trimmed)."""
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    if text in ("", "-0"):
        text = "0"
    return text


def _row_terms(row: DownmixRow) -> str:
    """Render one output row as ``coef*channel`` terms joined by +/-.

    A single term keeps no operator; the pan filter treats a bare
    ``coef*channel`` as the whole expression.
    """
    parts: list[str] = []
    for ch, coef in row:
        term = f"{_format_coef(coef)}*c{ch}"
        if not parts:
            parts.append(term)
        else:
            parts.append(f"+{term}" if coef >= 0 else f"-{term.lstrip('-')}")
    return "".join(parts)


def pan_expression(left_row: DownmixRow, right_row: DownmixRow) -> str:
    """Build the full FFmpeg ``pan`` filter for a stereo matrix.

    The result is the value of ``-af``: ``pan=stereo|c0=...|c1=...``.
    The ``|`` separators belong to the pan filter's argument syntax; the
    command is launched without a shell, so they are passed verbatim.
    """
    return f"pan=stereo|c0={_row_terms(left_row)}|c1={_row_terms(right_row)}"


def channel_labels(channel_count: int, channel_layout: str | None) -> list[str]:
    """Display labels for the source channels (spec §9.2.2).

    Conventional names only for layouts whose identity is known; every
    other layout gets positional labels — speaker identities are never
    guessed from the channel count alone.
    """
    if channel_count == 1:
        return ["Mono"]
    if channel_count == 2:
        return ["L", "R"]
    if channel_count == 6 and channel_layout in STANDARD_51_LAYOUTS:
        return ["FL", "FR", "C", "Ls", "Rs", "LFE"]
    return [f"Ch {i}" for i in range(channel_count)]
