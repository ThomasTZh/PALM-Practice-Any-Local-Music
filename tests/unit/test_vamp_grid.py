"""Unit tests for converting Vamp features into a rhythm branch."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from basseparate.domain.project import ProjectRecord, ProjectStatus
from basseparate.domain.rhythm import GridValidity, PulseRole
from basseparate.vamp.features import VampAnalysis, VampEvent
from basseparate.vamp.grid import VampGridError, build_branch_from_vamp

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def _project() -> ProjectRecord:
    return ProjectRecord(
        id=uuid4(),
        name="Vamp",
        created_at=NOW,
        updated_at=NOW,
        status=ProjectStatus.READY,
        source_asset_id=uuid4(),
        canonical_asset_id=uuid4(),
        source_stream_index=0,
        sample_rate=48_000,
        duration_frames=480_000,
        source_channel_count=2,
        source_channel_layout="stereo",
        decode_profile_version=1,
    )


def _analysis(*, bars: list[float], beats: list[float], bpb: int = 4) -> VampAnalysis:
    return VampAnalysis(
        plugin_key="qm-vamp-plugins:qm-barbeattracker",
        plugin_version="1.0",
        sample_rate=48_000,
        bpb=bpb,
        features={
            "bars": tuple(VampEvent(time_seconds=value) for value in bars),
            "beats": tuple(VampEvent(time_seconds=value) for value in beats),
        },
    )


def test_builds_beats_bars_and_meter() -> None:
    analysis = _analysis(bars=[0.5, 2.5], beats=[0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
    branch = build_branch_from_vamp(_project(), analysis, now=NOW)
    assert branch.grid_validity is GridValidity.VALID
    assert [pulse.source_frame for pulse in branch.pulses] == [
        24_000,
        48_000,
        72_000,
        96_000,
        120_000,
        144_000,
    ]
    assert [pulse.role for pulse in branch.pulses] == [
        PulseRole.DOWNBEAT,
        PulseRole.BEAT,
        PulseRole.BEAT,
        PulseRole.BEAT,
        PulseRole.DOWNBEAT,
        PulseRole.BEAT,
    ]
    assert [anchor.musical_position.numerator for anchor in branch.tempo_anchors] == [
        0,
        1,
        2,
        3,
        4,
        5,
    ]
    assert branch.meter_regions[0].numerator == 4
    assert branch.meter_regions[0].denominator == 4
    assert branch.meter_regions[0].grouping == [1, 1, 1, 1]
    assert branch.bar_origin.first_numbered_bar_position.numerator == 0


def test_drops_beats_before_the_first_bar() -> None:
    analysis = _analysis(bars=[2.0], beats=[0.5, 1.0, 2.0, 2.5, 3.0])
    branch = build_branch_from_vamp(_project(), analysis, now=NOW)
    assert [anchor.source_frame for anchor in branch.tempo_anchors] == [96_000, 120_000, 144_000]


def test_falls_back_to_first_beat_without_bars() -> None:
    analysis = _analysis(bars=[], beats=[1.0, 1.5], bpb=3)
    branch = build_branch_from_vamp(_project(), analysis, now=NOW)
    assert len(branch.pulses) == 2
    assert branch.meter_regions[0].numerator == 3
    assert branch.meter_regions[0].grouping == [1, 1, 1]


def test_rejects_unsupported_bpb_and_empty_material() -> None:
    with pytest.raises(VampGridError, match="bpb"):
        build_branch_from_vamp(_project(), _analysis(bars=[], beats=[1.0], bpb=5), now=NOW)
    with pytest.raises(VampGridError, match="beat"):
        build_branch_from_vamp(_project(), _analysis(bars=[], beats=[]), now=NOW)
