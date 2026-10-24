"""Musical/source practice-loop resolution and conversion (M3.13)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.domain.meter import (
    ManualMeterRegion,
    MeterTempoUnit,
    build_meter_map,
    manual_candidate,
)
from basseparate.domain.practice import PracticeLoop
from basseparate.domain.rhythm import BarOriginState, LoopAnchorMode, MusicalPosition
from basseparate.domain.tempo import PULSE_UNIT_QUARTER
from basseparate.rhythm.loops import (
    LoopAlignmentError,
    LoopResolutionError,
    convert_loop,
    resolve_loop,
    resolve_loops,
)
from basseparate.rhythm.tempo import build_manual_tempo_map

NOW = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[2] / "frontend/tests/golden/rhythm-grid.json"
BRANCH = uuid.uuid4()
REVISION = 4


def _pos(data: dict) -> MusicalPosition:
    return MusicalPosition(**data)


def _setup():
    fixture = json.loads(FIXTURE.read_text())
    tempo = build_manual_tempo_map(
        [(anchor["sourceFrame"], _pos(anchor["musical"])) for anchor in fixture["tempoAnchors"]],
        project_id=uuid.uuid4(),
        project_sample_rate=fixture["projectSampleRate"],
        source_duration_frames=fixture["sourceDurationFrames"],
        hypothesis=PULSE_UNIT_QUARTER,
        created_at=NOW,
    )
    meter = build_meter_map(
        [
            ManualMeterRegion(
                start=_pos(region["start"]),
                candidate=manual_candidate(
                    region["numerator"],
                    region["denominator"],
                    region["grouping"],
                    MeterTempoUnit(region["displayTempoUnit"]),
                ),
            )
            for region in fixture["meterRegions"]
        ]
    )
    origin = BarOriginState(
        first_numbered_bar_position=_pos(fixture["barOrigin"]["firstNumberedBarPosition"]),
        first_bar_number=fixture["barOrigin"]["firstBarNumber"],
    )
    return tempo, meter, origin


def _loop(
    start: int = 0,
    end: int = 10_001,
    *,
    mode: LoopAnchorMode = LoopAnchorMode.SOURCE,
    start_musical: MusicalPosition | None = None,
    end_musical: MusicalPosition | None = None,
) -> PracticeLoop:
    return PracticeLoop(
        id=uuid.uuid4(),
        name="Loop",
        start_frames=start,
        end_frames=end,
        anchor_mode=mode,
        start_musical=start_musical,
        end_musical=end_musical,
        created_at=NOW,
        updated_at=NOW,
    )


class TestResolution:
    def test_source_loop_is_unchanged(self) -> None:
        tempo, _meter, _origin = _setup()
        loop = _loop()
        assert resolve_loop(loop, tempo, branch_id=BRANCH, branch_revision=REVISION) == loop

    def test_musical_loop_resolves_exact_sources(self) -> None:
        tempo, _meter, _origin = _setup()
        loop = _loop(
            mode=LoopAnchorMode.MUSICAL,
            start_musical=MusicalPosition(numerator=0, denominator=1),
            end_musical=MusicalPosition(numerator=4, denominator=1),
        )
        resolved = resolve_loop(loop, tempo, branch_id=BRANCH, branch_revision=REVISION)
        assert resolved.unresolved is False
        assert resolved.start_frames == 0
        assert resolved.end_frames == 10_001
        assert resolved.resolved_source_start == 0
        assert resolved.grid_branch_id == BRANCH
        assert resolved.grid_branch_revision == REVISION

    def test_variable_tempo_resolution(self) -> None:
        tempo, _meter, _origin = _setup()
        loop = _loop(
            mode=LoopAnchorMode.MUSICAL,
            start_musical=MusicalPosition(numerator=8, denominator=1),
            end_musical=MusicalPosition(numerator=11, denominator=1),
        )
        resolved = resolve_loop(loop, tempo, branch_id=BRANCH, branch_revision=REVISION)
        assert (resolved.start_frames, resolved.end_frames) == (20_003, 26_004)

    def test_unmapped_musical_loop_is_unresolved(self) -> None:
        tempo, _meter, _origin = _setup()
        loop = _loop(
            mode=LoopAnchorMode.MUSICAL,
            start_musical=MusicalPosition(numerator=20, denominator=1),
            end_musical=MusicalPosition(numerator=22, denominator=1),
        )
        resolved = resolve_loop(loop, tempo, branch_id=BRANCH, branch_revision=REVISION)
        assert resolved.unresolved is True
        assert resolved.resolved_source_start is None
        assert resolved.grid_branch_revision == REVISION

    def test_resolve_collection_leaves_source_loops(self) -> None:
        tempo, _meter, _origin = _setup()
        source = _loop()
        musical = _loop(
            mode=LoopAnchorMode.MUSICAL,
            start_musical=MusicalPosition(numerator=0, denominator=1),
            end_musical=MusicalPosition(numerator=2, denominator=1),
        )
        resolved = resolve_loops(
            [source, musical], tempo, branch_id=BRANCH, branch_revision=REVISION
        )
        assert resolved[0] == source
        assert resolved[1].end_frames == 5_001


class TestConversion:
    def test_source_to_musical_on_grid(self) -> None:
        tempo, meter, origin = _setup()
        loop = _loop()
        result = convert_loop(
            loop,
            tempo,
            meter,
            origin,
            target=LoopAnchorMode.MUSICAL,
            branch_id=BRANCH,
            branch_revision=REVISION,
        )
        assert result.loop.anchor_mode is LoopAnchorMode.MUSICAL
        assert result.loop.start_musical == MusicalPosition(numerator=0, denominator=1)
        assert result.loop.end_musical == MusicalPosition(numerator=4, denominator=1)
        assert result.warnings == []

    def test_off_grid_conversion_needs_confirmation(self) -> None:
        tempo, meter, origin = _setup()
        loop = _loop(start=1_000, end=9_000)
        with pytest.raises(LoopAlignmentError):
            convert_loop(
                loop,
                tempo,
                meter,
                origin,
                target=LoopAnchorMode.MUSICAL,
                branch_id=BRANCH,
                branch_revision=REVISION,
            )
        result = convert_loop(
            loop,
            tempo,
            meter,
            origin,
            target=LoopAnchorMode.MUSICAL,
            branch_id=BRANCH,
            branch_revision=REVISION,
            confirm_off_grid=True,
        )
        assert result.loop.anchor_mode is LoopAnchorMode.MUSICAL
        assert result.warnings

    def test_musical_to_source_is_authoritative(self) -> None:
        tempo, meter, origin = _setup()
        loop = _loop(
            mode=LoopAnchorMode.MUSICAL,
            start_musical=MusicalPosition(numerator=8, denominator=1),
            end_musical=MusicalPosition(numerator=11, denominator=1),
        )
        result = convert_loop(
            loop,
            tempo,
            meter,
            origin,
            target=LoopAnchorMode.SOURCE,
            branch_id=BRANCH,
            branch_revision=REVISION,
        )
        assert result.loop.anchor_mode is LoopAnchorMode.SOURCE
        assert (result.loop.start_frames, result.loop.end_frames) == (20_003, 26_004)

    def test_conversion_outside_map_rejected(self) -> None:
        tempo, meter, origin = _setup()
        loop = _loop(
            mode=LoopAnchorMode.MUSICAL,
            start_musical=MusicalPosition(numerator=20, denominator=1),
            end_musical=MusicalPosition(numerator=22, denominator=1),
        )
        with pytest.raises(LoopResolutionError):
            convert_loop(
                loop,
                tempo,
                meter,
                origin,
                target=LoopAnchorMode.SOURCE,
                branch_id=BRANCH,
                branch_revision=REVISION,
            )
