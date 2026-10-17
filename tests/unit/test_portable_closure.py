"""Dependency closure for the portable project format (M2.14, spec §16)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.portable.closure import (
    PortableFormatError,
    compute_portable_plan,
    model_manifests_payload,
    separation_runs_payload,
)
from tests.unit.portable_seed import (
    CAN_HASH_A,
    DMX_HASH_A,
    PB_HASH_A,
    RES_HASH_A,
    SRC_HASH_A,
    STEM1_HASH_A,
    STEM2_HASH_A,
    WF_HASH_A,
    seed_two_projects,
)


@pytest.fixture()
def seed(tmp_path: Path):
    return seed_two_projects(tmp_path)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


class TestClosure:
    def test_includes_full_dependency_set(self, seed) -> None:
        conn = _connect(seed.db_path)
        try:
            plan = compute_portable_plan(conn, seed.project_a)
        finally:
            conn.close()
        members = {asset.member for asset in plan.assets}
        by_hash = {asset.content_hash: asset for asset in plan.assets}
        expected_hashes = {
            SRC_HASH_A,
            CAN_HASH_A,
            DMX_HASH_A,
            STEM1_HASH_A,
            STEM2_HASH_A,
            RES_HASH_A,
            PB_HASH_A,
        }
        assert set(by_hash) == expected_hashes
        # Member naming: original keeps its upload extension, PCM gets .pcm.
        assert f"assets/sha256/{SRC_HASH_A}.wav" in members
        assert f"assets/sha256/{CAN_HASH_A}.pcm" in members
        assert plan.project_id == seed.project_a
        assert plan.project_row["name"] == "Song A"
        assert plan.project_row["revision"] == 5

    def test_excludes_unrelated_projects_and_unreferenced_assets(self, seed) -> None:
        conn = _connect(seed.db_path)
        try:
            plan = compute_portable_plan(conn, seed.project_a)
        finally:
            conn.close()
        assert plan.asset_ids == frozenset(
            {seed.src_a, seed.can_a, seed.dmx_a, seed.stem1_a, seed.stem2_a,
             seed.res_a, seed.pb_a}
        )
        # Project B's assets and the unreferenced asset stay out.
        assert {seed.src_b, seed.can_b, seed.stem_b, seed.unref}.isdisjoint(plan.asset_ids)
        assert seed.run_b not in plan.run_ids
        assert seed.rs_b not in plan.result_set_ids

    def test_essential_classification(self, seed) -> None:
        conn = _connect(seed.db_path)
        try:
            plan = compute_portable_plan(conn, seed.project_a)
        finally:
            conn.close()
        essential = {asset.content_hash for asset in plan.assets if asset.essential}
        optional = {asset.content_hash for asset in plan.assets if not asset.essential}
        assert essential == {
            SRC_HASH_A,
            CAN_HASH_A,
            DMX_HASH_A,
            STEM1_HASH_A,
            STEM2_HASH_A,
            RES_HASH_A,
        }
        # The playback-rate cache is the only optional asset.
        assert optional == {PB_HASH_A}

    def test_waveform_caches_of_closure_assets(self, seed) -> None:
        conn = _connect(seed.db_path)
        try:
            plan = compute_portable_plan(conn, seed.project_a)
        finally:
            conn.close()
        assert len(plan.waveform_caches) == 1
        cache = plan.waveform_caches[0]
        assert cache.asset_id == seed.can_a
        assert cache.source_hash == WF_HASH_A
        assert cache.member_prefix == f"caches/waveforms/{WF_HASH_A}/"

    def test_representation_parent_fixpoint(self, tmp_path: Path) -> None:
        """A representation parent enters the closure even if only
        reachable through the representations table."""
        seed = seed_two_projects(tmp_path)
        conn = _connect(seed.db_path)
        try:
            # Point project B's canonical at project A's downmix parent
            # chain: B's canonical representation parent = B's canonical.
            # Instead craft a direct case: a new asset X with a
            # representation whose parent is Y (not referenced elsewhere).
            x, y = str(uuid.uuid4()), str(uuid.uuid4())
            conn.execute(
                "INSERT INTO assets (id, content_hash, role, relative_path, "
                "media_type, byte_count, created_at) VALUES (?, ?, 'derived_pcm', "
                "? , 'audio/pcm', 1, ?)",
                (x, "f0" * 32, f"data/assets/f0f0{'0' * 60}.pcm",
                 datetime.now(UTC).isoformat().replace("+00:00", "Z")),
            )
            conn.execute(
                "INSERT INTO assets (id, content_hash, role, relative_path, "
                "media_type, byte_count, created_at) VALUES (?, ?, 'source_pcm', "
                "?, 'audio/pcm', 1, ?)",
                (y, "f1" * 32, f"data/assets/f1f1{'1' * 60}.pcm",
                 datetime.now(UTC).isoformat().replace("+00:00", "Z")),
            )
            conn.execute(
                "INSERT INTO representations (asset_id, parent_asset_id, role, "
                "sample_rate, channel_count, frame_count, transform_key, "
                "project_rate, representation_rate, tool, tool_version, "
                "profile_version, created_at) VALUES (?, ?, 'monitoring_downmix', "
                "48000, 2, 100, 'k', 48000, 48000, 't', '1', 1, ?)",
                (x, y, datetime.now(UTC).isoformat().replace("+00:00", "Z")),
            )
            conn.execute(
                "UPDATE projects SET monitoring_asset_id = ? WHERE id = ?",
                (x, seed.project_b),
            )
            plan = compute_portable_plan(conn, seed.project_b)
        finally:
            conn.close()
        assert x in plan.asset_ids
        assert y in plan.asset_ids  # reached only via the representation parent

    def test_separation_provenance(self, seed) -> None:
        conn = _connect(seed.db_path)
        try:
            plan = compute_portable_plan(conn, seed.project_a)
        finally:
            conn.close()
        assert plan.run_ids == frozenset({seed.run_a})
        assert plan.result_set_ids == frozenset({seed.rs_a})
        payload = separation_runs_payload(plan.separation_runs)
        assert payload["version"] == 1
        assert [run["id"] for run in payload["runs"]] == [seed.run_a]
        # The run record is the full provenance (model identity, engine).
        run = payload["runs"][0]
        assert run["model_manifest_hash"]
        assert run["engine_version"] == "demucs-4.1.0"
        assert run["effective_parameters"] is None

    def test_model_manifests_payload(self) -> None:
        payload = model_manifests_payload()
        assert payload["version"] == 1
        models = {model["model_id"] for model in payload["models"]}
        assert "htdemucs_ft" in models
        entry = next(m for m in payload["models"] if m["model_id"] == "htdemucs_ft")
        assert entry["artifacts"]
        assert all(a["sha256"] for a in entry["artifacts"])
        assert "license_notice" in entry

    def test_missing_project_raises(self, seed) -> None:
        conn = _connect(seed.db_path)
        try:
            with pytest.raises(PortableFormatError, match="no such project"):
                compute_portable_plan(conn, str(uuid.uuid4()))
        finally:
            conn.close()

    def test_dangling_asset_reference_raises(self, seed) -> None:
        conn = _connect(seed.db_path)
        try:
            conn.execute(
                "UPDATE projects SET source_asset_id = ? WHERE id = ?",
                (str(uuid.uuid4()), seed.project_b),
            )
            conn.commit()
            with pytest.raises(PortableFormatError, match="dangling asset"):
                compute_portable_plan(conn, seed.project_b)
        finally:
            conn.close()

    def test_malformed_result_set_record_raises(self, seed) -> None:
        conn = _connect(seed.db_path)
        try:
            conn.execute(
                "UPDATE separation_result_sets SET record_json = 'not json' "
                "WHERE id = ?",
                (seed.rs_a,),
            )
            with pytest.raises(PortableFormatError, match="malformed"):
                compute_portable_plan(conn, seed.project_a)
        finally:
            conn.close()

    def test_preserves_row_factory(self, seed) -> None:
        conn = _connect(seed.db_path)
        try:
            assert conn.row_factory is sqlite3.Row
            compute_portable_plan(conn, seed.project_a)
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()
