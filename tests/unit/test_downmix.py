"""Unit tests for the monitoring downmix matrices (M1.7)."""

from __future__ import annotations

import pytest

from basseparate.media.downmix import (
    MATRIX_VERSION,
    MonitorSelectionError,
    channel_labels,
    manual_matrix,
    normalize_row,
    pan_expression,
    resolve_downmix,
    standard_51_matrix,
)


class TestNormalizeRow:
    def test_scales_to_unit_l1_norm(self) -> None:
        row = normalize_row([(0, 1.0), (2, 0.5)])
        assert sum(abs(c) for _, c in row) == pytest.approx(1.0)
        assert row[0] == (0, pytest.approx(2.0 / 3.0))
        assert row[1] == (2, pytest.approx(1.0 / 3.0))

    def test_preserves_channel_order(self) -> None:
        row = normalize_row([(3, 1.0), (0, 1.0)])
        assert [ch for ch, _ in row] == [3, 0]

    def test_empty_row_rejected(self) -> None:
        with pytest.raises(ValueError):
            normalize_row([])

    def test_zero_coefficients_rejected(self) -> None:
        with pytest.raises(ValueError):
            normalize_row([(0, 0.0), (1, 0.0)])


class TestStandard51Matrix:
    def test_left_row_coefficients(self) -> None:
        left, _ = standard_51_matrix()
        total = 1.0 + 0.7071 + 0.7071 + 0.5
        assert left == (
            (0, pytest.approx(1.0 / total)),
            (2, pytest.approx(0.7071 / total)),
            (3, pytest.approx(0.7071 / total)),
            (5, pytest.approx(0.5 / total)),
        )

    def test_right_row_coefficients(self) -> None:
        _, right = standard_51_matrix()
        total = 1.0 + 0.7071 + 0.7071 + 0.5
        assert right == (
            (1, pytest.approx(1.0 / total)),
            (2, pytest.approx(0.7071 / total)),
            (4, pytest.approx(0.7071 / total)),
            (5, pytest.approx(0.5 / total)),
        )

    def test_rows_are_normalized(self) -> None:
        left, right = standard_51_matrix()
        for row in (left, right):
            assert sum(abs(c) for _, c in row) == pytest.approx(1.0)

    def test_center_feeds_both_sides(self) -> None:
        left, right = standard_51_matrix()
        left_c2 = dict(left)[2]
        right_c2 = dict(right)[2]
        assert left_c2 == pytest.approx(right_c2)
        assert left_c2 == pytest.approx(0.7071 / (1.0 + 0.7071 + 0.7071 + 0.5))


class TestManualMatrix:
    def test_single_terms(self) -> None:
        left, right = manual_matrix(2, 5)
        assert left == ((2, 1.0),)
        assert right == ((5, 1.0),)


class TestResolveDownmix:
    def test_mono_needs_no_downmix(self) -> None:
        assert resolve_downmix(1, None, None, None) is None

    def test_stereo_needs_no_downmix(self) -> None:
        assert resolve_downmix(2, "mono" if False else None, None, None) is None

    def test_51_layout_uses_standard_matrix(self) -> None:
        mode, left, right = resolve_downmix(6, "5.1", None, None)
        assert mode == "standard_5_1"
        assert dict(left)[0] == pytest.approx(1.0 / (1.0 + 0.7071 + 0.7071 + 0.5))

    def test_51_ignores_stored_selection(self) -> None:
        mode, _, _ = resolve_downmix(6, "5.1", 3, 4)
        assert mode == "standard_5_1"

    def test_unknown_layout_requires_selection(self) -> None:
        with pytest.raises(MonitorSelectionError):
            resolve_downmix(6, None, None, None)
        with pytest.raises(MonitorSelectionError):
            resolve_downmix(7, "7.1", None, None)
        with pytest.raises(MonitorSelectionError):
            resolve_downmix(8, None, 0, None)

    def test_unknown_layout_uses_selection(self) -> None:
        mode, left, right = resolve_downmix(4, None, 1, 2)
        assert mode == "manual"
        assert left == ((1, 1.0),)
        assert right == ((2, 1.0),)

    def test_selection_out_of_range_rejected(self) -> None:
        with pytest.raises(MonitorSelectionError):
            resolve_downmix(4, None, 0, 4)
        with pytest.raises(MonitorSelectionError):
            resolve_downmix(4, None, -1, 1)

    def test_same_channel_allowed_for_both_sides(self) -> None:
        mode, left, right = resolve_downmix(3, None, 1, 1)
        assert mode == "manual"
        assert left == right == ((1, 1.0),)


class TestPanExpression:
    def test_standard_51_expression(self) -> None:
        left, right = standard_51_matrix()
        expr = pan_expression(left, right)
        assert (
            expr
            == "pan=stereo|c0=0.343147*c0+0.242639*c2+0.242639*c3+0.171574*c5"
            "|c1=0.343147*c1+0.242639*c2+0.242639*c4+0.171574*c5"
        )

    def test_manual_expression(self) -> None:
        left, right = manual_matrix(2, 3)
        assert pan_expression(left, right) == "pan=stereo|c0=1*c2|c1=1*c3"

    def test_single_term_has_no_leading_operator(self) -> None:
        left, right = manual_matrix(0, 1)
        assert pan_expression(left, right) == "pan=stereo|c0=1*c0|c1=1*c1"

    def test_coefficients_have_at_most_six_decimals(self) -> None:
        left, right = standard_51_matrix()
        expr = pan_expression(left, right)
        for term in expr[len("pan=stereo") :].strip("|").split("|"):
            for part in term.split("+"):
                coef = part.split("*")[0]
                decimals = coef.split(".")[1] if "." in coef else ""
                assert len(decimals) <= 6

    def test_no_parentheses_or_division(self) -> None:
        left, right = standard_51_matrix()
        expr = pan_expression(left, right)
        assert "(" not in expr and ")" not in expr and "/" not in expr


class TestChannelLabels:
    def test_mono(self) -> None:
        assert channel_labels(1, None) == ["Mono"]

    def test_stereo(self) -> None:
        assert channel_labels(2, None) == ["L", "R"]

    def test_51(self) -> None:
        assert channel_labels(6, "5.1") == ["FL", "FR", "C", "Ls", "Rs", "LFE"]

    def test_unknown_layout_gets_positional_labels(self) -> None:
        assert channel_labels(6, None) == [f"Ch {i}" for i in range(6)]
        assert channel_labels(8, "7.1") == [f"Ch {i}" for i in range(8)]
        assert channel_labels(4, "4.0") == [f"Ch {i}" for i in range(4)]


class TestMatrixVersion:
    def test_version_is_recorded(self) -> None:
        assert MATRIX_VERSION == 1
