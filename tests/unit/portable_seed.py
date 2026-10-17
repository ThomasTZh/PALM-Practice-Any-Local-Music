"""Two-project database seed for the portable format tests (M2.14).

Project A is a fully populated project (source, canonical PCM,
monitoring downmix, a completed four-stem separation with the bass
residual, a playback-rate representation, a waveform cache, an import).
Project B is an unrelated project with its own assets. ``UNREFERENCED``
is an asset row that no project references.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from basseparate.domain import (
    Confidence,
    ConfidenceKind,
    DeviceType,
    SeparationMode,
    SeparationResultSet,
    SeparationRun,
    SeparationRunStatus,
    SourceIdentity,
    StemRecord,
    StemRole,
    ValidationStatus,
)
from basseparate.domain.separation import ReferenceMixIdentity
from basseparate.storage.db import initialize_database

NOW = datetime.now(UTC).isoformat().replace("+00:00", "Z")
SRC_HASH_A = "a1" * 32
CAN_HASH_A = "a2" * 32
DMX_HASH_A = "a3" * 32
STEM1_HASH_A = "a4" * 32
STEM2_HASH_A = "a5" * 32
RES_HASH_A = "a6" * 32
PB_HASH_A = "a7" * 32
SRC_HASH_B = "b1" * 32
CAN_HASH_B = "b2" * 32
STEM_HASH_B = "b3" * 32
UNREF_HASH = "c1" * 32
WF_HASH_A = "d1" * 32
GENERIC_HASH = "e1" * 32


def _now_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Seed:
    db_path: Path
    project_a: str
    project_b: str
    src_a: str
    can_a: str
    dmx_a: str
    stem1_a: str
    stem2_a: str
    res_a: str
    pb_a: str
    src_b: str
    can_b: str
    stem_b: str
    unref: str
    run_a: str
    rs_a: str
    run_b: str
    rs_b: str


def seed_two_projects(tmp_path: Path) -> Seed:
    db_path = tmp_path / "data" / "basseparate.db"
    initialize_database(db_path)

    a = uuid.uuid4()
    b = uuid.uuid4()
    src_a, can_a, dmx_a = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    stem1_a, stem2_a, res_a, pb_a = (uuid.uuid4() for _ in range(4))
    src_b, can_b, stem_b, unref = (uuid.uuid4() for _ in range(4))
    run_a, rs_a = uuid.uuid4(), uuid.uuid4()
    run_b, rs_b = uuid.uuid4(), uuid.uuid4()

    conn = sqlite3.connect(db_path)
    try:
        _insert_project(conn, a, "Song A", src_a, can_a, dmx_a)
        _insert_project(conn, b, "Song B", src_b, can_b, None)
        _insert_assets(
            conn,
            (
                (src_a, SRC_HASH_A, "source_original", "runtime/uploads/impA.part", "audio/wav"),
                (can_a, CAN_HASH_A, "source_pcm", f"data/assets/{CAN_HASH_A}.pcm", "audio/pcm"),
                (dmx_a, DMX_HASH_A, "derived_pcm", f"data/assets/{DMX_HASH_A}.pcm", "audio/pcm"),
                (stem1_a, STEM1_HASH_A, "stem", f"data/assets/{STEM1_HASH_A}.pcm", "audio/pcm"),
                (stem2_a, STEM2_HASH_A, "stem", f"data/assets/{STEM2_HASH_A}.pcm", "audio/pcm"),
                (res_a, RES_HASH_A, "stem", f"data/assets/{RES_HASH_A}.pcm", "audio/pcm"),
                (pb_a, PB_HASH_A, "derived_pcm", f"data/assets/{PB_HASH_A}.pcm", "audio/pcm"),
                (src_b, SRC_HASH_B, "source_original", "runtime/uploads/impB.part", "audio/wav"),
                (can_b, CAN_HASH_B, "source_pcm", f"data/assets/{CAN_HASH_B}.pcm", "audio/pcm"),
                (stem_b, STEM_HASH_B, "stem", f"data/assets/{STEM_HASH_B}.pcm", "audio/pcm"),
                (unref, UNREF_HASH, "source_pcm", f"data/assets/{UNREF_HASH}.pcm", "audio/pcm"),
            ),
        )
        for asset in (src_a, can_a, dmx_a, stem1_a, stem2_a, res_a, pb_a):
            conn.execute(
                "INSERT INTO project_assets (project_id, asset_id, role) VALUES (?, ?, ?)",
                (str(a), str(asset), "project"),
            )
        for asset in (src_b, can_b, stem_b):
            conn.execute(
                "INSERT INTO project_assets (project_id, asset_id, role) VALUES (?, ?, ?)",
                (str(b), str(asset), "project"),
            )
        conn.execute(
            "INSERT INTO imports (id, project_id, filename, declared_byte_count, "
            "source_sha256, transfer_state, created_at, updated_at) "
            "VALUES (?, ?, 'song.wav', 8820000, ?, 'complete', ?, ?)",
            (str(uuid.uuid4()), str(a), SRC_HASH_A, _now_z(), _now_z()),
        )
        _insert_representation(
            conn, dmx_a, can_a, "monitoring_downmix", 48000, 2, 441000
        )
        _insert_representation(conn, pb_a, can_a, "playback_rate", 44100, 2, 441000)
        conn.execute(
            "INSERT INTO waveform_caches (id, asset_id, cache_version, source_hash, "
            "sample_rate, frame_count, channel_count, levels_json, manifest_path, created_at) "
            "VALUES (?, ?, 1, ?, 48000, 441000, 2, '[{\"bucket_count\": 6913, "
            "\"tile_count\": 2, \"final_tile_buckets\": 2881}]', "
            "?, ?)",
            (str(uuid.uuid4()), str(can_a), WF_HASH_A,
             f"cache/waveforms/{WF_HASH_A}/manifest.json", _now_z()),
        )
        _insert_separation(
            conn, a, run_a, rs_a, can_a, CAN_HASH_A, dmx_a, res_a, stem1_a, stem2_a
        )
        _insert_separation(
            conn, b, run_b, rs_b, can_b, CAN_HASH_B, None, None, stem_b, None
        )
        conn.commit()
    finally:
        conn.close()

    return Seed(
        db_path=db_path,
        project_a=str(a),
        project_b=str(b),
        src_a=str(src_a),
        can_a=str(can_a),
        dmx_a=str(dmx_a),
        stem1_a=str(stem1_a),
        stem2_a=str(stem2_a),
        res_a=str(res_a),
        pb_a=str(pb_a),
        src_b=str(src_b),
        can_b=str(can_b),
        stem_b=str(stem_b),
        unref=str(unref),
        run_a=str(run_a),
        rs_a=str(rs_a),
        run_b=str(run_b),
        rs_b=str(rs_b),
    )


def _insert_project(
    conn: sqlite3.Connection,
    project_id: uuid.UUID,
    name: str,
    source_asset: uuid.UUID,
    canonical: uuid.UUID,
    monitoring: uuid.UUID | None,
) -> None:
    conn.execute(
        "INSERT INTO projects (id, name, created_at, updated_at, revision, "
        "source_asset_id, canonical_asset_id, monitoring_asset_id, sample_rate, "
        "duration_frames, status) VALUES (?, ?, ?, ?, 5, ?, ?, ?, 48000, 441000, 'ready')",
        (str(project_id), name, _now_z(), _now_z(), str(source_asset), str(canonical),
         str(monitoring) if monitoring else None),
    )


def _insert_assets(
    conn: sqlite3.Connection, rows: tuple[tuple[uuid.UUID, str, str, str, str], ...]
) -> None:
    for asset_id, content_hash, role, relative_path, media_type in rows:
        conn.execute(
            "INSERT INTO assets (id, content_hash, role, relative_path, media_type, "
            "byte_count, created_at) VALUES (?, ?, ?, ?, ?, 8820000, ?)",
            (str(asset_id), content_hash, role, relative_path, media_type, _now_z()),
        )


def _insert_representation(
    conn: sqlite3.Connection,
    asset_id: uuid.UUID,
    parent: uuid.UUID,
    role: str,
    rate: int,
    channels: int,
    frames: int,
) -> None:
    conn.execute(
        "INSERT INTO representations (asset_id, parent_asset_id, role, sample_rate, "
        "channel_count, frame_count, transform_key, project_rate, representation_rate, "
        "tool, tool_version, profile_version, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'key', 48000, ?, 'ffprobe', '8.1.2', 1, ?)",
        (str(asset_id), str(parent), role, rate, channels, frames, rate, _now_z()),
    )


def _insert_separation(
    conn: sqlite3.Connection,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    rs_id: uuid.UUID,
    source: uuid.UUID,
    source_hash: str,
    reference: uuid.UUID | None,
    residual: uuid.UUID | None,
    stem1: uuid.UUID,
    stem2: uuid.UUID | None,
) -> None:
    stems: list[StemRecord] = [
        StemRecord(
            id=uuid.uuid4(),
            result_set_id=rs_id,
            role=StemRole.BASS,
            display_name="Bass",
            audio_asset_id=stem1,
            sample_rate=48_000,
            channel_count=2,
            frame_count=441_000,
            confidence=Confidence(kind=ConfidenceKind.UNAVAILABLE),
        )
    ]
    if stem2 is not None:
        stems.append(
            StemRecord(
                id=uuid.uuid4(),
                result_set_id=rs_id,
                role=StemRole.OTHERS,
                display_name="Others",
                audio_asset_id=stem2,
                sample_rate=48_000,
                channel_count=2,
                frame_count=441_000,
                confidence=Confidence(kind=ConfidenceKind.UNAVAILABLE),
            )
        )
    run = SeparationRun(
        id=run_id,
        project_id=project_id,
        input_asset_id=source,
        input_transform_hash=GENERIC_HASH,
        requested_mode=SeparationMode.FOUR_STEMS,
        model_manifest_id=uuid.uuid4(),
        model_manifest_hash=GENERIC_HASH,
        engine_version="demucs-4.1.0",
        adapter_version="adapter-1",
        device_type=DeviceType.CPU,
        status=SeparationRunStatus.COMPLETED,
        result_set_id=rs_id,
    )
    result_set = SeparationResultSet(
        id=rs_id,
        run_id=run_id,
        project_id=project_id,
        source=SourceIdentity(
            asset_id=source,
            source_hash=source_hash,
            sample_rate=48_000,
            duration_frames=441_000,
        ),
        output_sample_rate=48_000,
        output_channel_count=2,
        output_frame_count=441_000,
        available_stem_roles=[s.role for s in stems],
        stem_ids=[s.id for s in stems],
        bass_residual_asset_id=residual,
        reference_mix=ReferenceMixIdentity(
            asset_id=reference if reference else source,
            hash=GENERIC_HASH,
            transformation_hash=GENERIC_HASH,
        ),
        validation_status=ValidationStatus.VALID,
        created_at=datetime.now(UTC),
    )
    conn.execute(
        "INSERT INTO separation_runs (id, project_id, status, requested_mode, "
        "result_set_id, record_json) VALUES (?, ?, 'completed', 'four_stems', ?, ?)",
        (str(run_id), str(project_id), str(rs_id), run.model_dump_json()),
    )
    conn.execute(
        "INSERT INTO separation_result_sets (id, run_id, project_id, validation_status, "
        "created_at, record_json) VALUES (?, ?, ?, 'valid', ?, ?)",
        (str(rs_id), str(run_id), str(project_id), _now_z(), result_set.model_dump_json()),
    )
    for stem in stems:
        conn.execute(
            "INSERT INTO stems (id, result_set_id, role, record_json) VALUES (?, ?, ?, ?)",
            (str(stem.id), str(rs_id), stem.role.value, stem.model_dump_json()),
        )
