"""Plan exclusions for optional assets (M2.15, spec §17.1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from basseparate.portable.closure import compute_portable_plan
from basseparate.portable.save import plan_with_exclusions
from tests.unit.portable_seed import seed_two_projects


@pytest.fixture()
def plan(tmp_path: Path):
    seed = seed_two_projects(tmp_path)
    conn = sqlite3.connect(f"file:{seed.db_path}?mode=ro", uri=True)
    try:
        return seed, compute_portable_plan(conn, seed.project_a)
    finally:
        conn.close()


class TestPlanWithExclusions:
    def test_no_exclusions_is_identity(self, plan) -> None:
        seed, base = plan
        reduced = plan_with_exclusions(base, set())
        assert reduced is base

    def test_excluded_asset_drops_rows_and_ids(self, plan) -> None:
        seed, base = plan
        pb = next(a for a in base.assets if a.asset_id == seed.pb_a)
        assert pb.essential is False  # playback-rate cache
        reduced = plan_with_exclusions(base, {seed.pb_a})
        assert seed.pb_a not in {a.asset_id for a in reduced.assets}
        assert seed.pb_a not in reduced.asset_ids
        # Every other asset survives.
        assert len(reduced.assets) == len(base.assets) - 1
        # Waveform caches of the excluded asset are dropped; others kept.
        assert all(c.asset_id != seed.pb_a for c in reduced.waveform_caches)
        assert len(reduced.waveform_caches) == len(base.waveform_caches) - (
            1
            if any(c.asset_id == seed.pb_a for c in base.waveform_caches)
            else 0
        )
        # Unrelated plan fields are untouched.
        assert reduced.project_id == base.project_id
        assert reduced.result_set_ids == base.result_set_ids
        assert reduced.run_ids == base.run_ids
        assert reduced.separation_runs == base.separation_runs
