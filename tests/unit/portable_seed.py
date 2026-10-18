"""Two-project database seed for the portable format tests (M2.14).

Project A is a fully populated project (source, canonical PCM,
monitoring downmix, a completed four-stem separation with the bass
residual, a playback-rate representation, a waveform cache, an import).
Project B is an unrelated project with its own assets. ``UNREFERENCED``
is an asset row that no project references.
"""

from __future__ import annotations

import hashlib
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


def _hash_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# Asset content for project A. Asset rows are content-addressed: the
# ``content_hash`` is the SHA-256 of the file bytes, so the fixtures are
# internally consistent and M2.15 archives built from them pass the
# M2.16 validation (manifest member hash == asset content hash).
SRC_CONTENT_A = b"WAVF" * 1024
CAN_CONTENT_A = b"\x00\x01" * 20000
DMX_CONTENT_A = b"\x02" * 30000
STEM1_CONTENT_A = b"\x03" * 40000
STEM2_CONTENT_A = b"\x04" * 50000
RES_CONTENT_A = b"\x05" * 60000
PB_CONTENT_A = b"\x06" * 70000
# Project B has database rows only (no files in the fixture store).
SRC_CONTENT_B = b"B-SRC" * 100
CAN_CONTENT_B = b"B-CAN" * 100
STEM_CONTENT_B = b"B-STEM" * 100
UNREF_CONTENT = b"unreferenced-asset"

SRC_HASH_A = _hash_of(SRC_CONTENT_A)
CAN_HASH_A = _hash_of(CAN_CONTENT_A)
DMX_HASH_A = _hash_of(DMX_CONTENT_A)
STEM1_HASH_A = _hash_of(STEM1_CONTENT_A)
STEM2_HASH_A = _hash_of(STEM2_CONTENT_A)
RES_HASH_A = _hash_of(RES_CONTENT_A)
PB_HASH_A = _hash_of(PB_CONTENT_A)
SRC_HASH_B = _hash_of(SRC_CONTENT_B)
CAN_HASH_B = _hash_of(CAN_CONTENT_B)
STEM_HASH_B = _hash_of(STEM_CONTENT_B)
UNREF_HASH = _hash_of(UNREF_CONTENT)
#: Waveform caches are keyed by their source content hash.
WF_HASH_A = CAN_HASH_A
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
    # The import id is the source original's upload file name.
    imp_a = uuid.uuid4()

    conn = sqlite3.connect(db_path)
    try:
        _insert_project(conn, a, "Song A", src_a, can_a, dmx_a)
        _insert_project(conn, b, "Song B", src_b, can_b, None)
        _insert_assets(
            conn,
            (
                (
                    src_a, SRC_HASH_A, "source_original",
                    f"runtime/uploads/{imp_a}.part", "audio/wav", len(SRC_CONTENT_A),
                ),
                (
                    can_a, CAN_HASH_A, "source_pcm",
                    f"data/assets/{CAN_HASH_A}.pcm", "audio/pcm", len(CAN_CONTENT_A),
                ),
                (
                    dmx_a, DMX_HASH_A, "derived_pcm",
                    f"data/assets/{DMX_HASH_A}.pcm", "audio/pcm", len(DMX_CONTENT_A),
                ),
                (
                    stem1_a, STEM1_HASH_A, "stem",
                    f"data/assets/{STEM1_HASH_A}.pcm", "audio/pcm", len(STEM1_CONTENT_A),
                ),
                (
                    stem2_a, STEM2_HASH_A, "stem",
                    f"data/assets/{STEM2_HASH_A}.pcm", "audio/pcm", len(STEM2_CONTENT_A),
                ),
                (
                    res_a, RES_HASH_A, "stem",
                    f"data/assets/{RES_HASH_A}.pcm", "audio/pcm", len(RES_CONTENT_A),
                ),
                (
                    pb_a, PB_HASH_A, "derived_pcm",
                    f"data/assets/{PB_HASH_A}.pcm", "audio/pcm", len(PB_CONTENT_A),
                ),
                (
                    src_b, SRC_HASH_B, "source_original",
                    "runtime/uploads/impB.part", "audio/wav", len(SRC_CONTENT_B),
                ),
                (
                    can_b, CAN_HASH_B, "source_pcm",
                    f"data/assets/{CAN_HASH_B}.pcm", "audio/pcm", len(CAN_CONTENT_B),
                ),
                (
                    stem_b, STEM_HASH_B, "stem",
                    f"data/assets/{STEM_HASH_B}.pcm", "audio/pcm", len(STEM_CONTENT_B),
                ),
                (
                    unref, UNREF_HASH, "source_pcm",
                    f"data/assets/{UNREF_HASH}.pcm", "audio/pcm", len(UNREF_CONTENT),
                ),
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
            "received_byte_count, source_sha256, transfer_state, created_at, updated_at) "
            "VALUES (?, ?, 'song.wav', ?, ?, ?, 'complete', ?, ?)",
            (
                str(imp_a),
                str(a),
                len(SRC_CONTENT_A),
                len(SRC_CONTENT_A),
                SRC_HASH_A,
                _now_z(),
                _now_z(),
            ),
        )
        _insert_representation(
            conn, dmx_a, can_a, "monitoring_downmix", 48000, 2, 441000
        )
        _insert_representation(conn, pb_a, can_a, "playback_rate", 44100, 2, 441000)
        conn.execute(
            "INSERT INTO waveform_caches (id, asset_id, cache_version, source_hash, "
            "sample_rate, frame_count, channel_count, levels_json, manifest_path, created_at) "
            "VALUES (?, ?, 1, ?, 48000, 441000, 2, '[{\"bucket_frame_count\": 64, "
            "\"bucket_count\": 6913, \"tile_count\": 2, \"final_tile_buckets\": 2881}]', "
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
        "duration_frames, status, source_stream_index, source_channel_count, "
        "source_channel_layout, decode_profile_version, source_metadata) "
        "VALUES (?, ?, ?, ?, 5, ?, ?, ?, 48000, 441000, 'ready', 0, 2, "
        "'stereo', 1, ?)",
        (str(project_id), name, _now_z(), _now_z(), str(source_asset), str(canonical),
         str(monitoring) if monitoring else None, '{"format": "wav"}'),
    )


def _insert_assets(
    conn: sqlite3.Connection,
    rows: tuple[tuple[uuid.UUID, str, str, str, str, int], ...],
) -> None:
    for asset_id, content_hash, role, relative_path, media_type, byte_count in rows:
        # PCM assets carry audio metadata (the separation planner and the
        # publication pipeline read it); the source original is an opaque
        # upload file and stays without audio facts.
        pcm = media_type == "audio/pcm"
        conn.execute(
            "INSERT INTO assets (id, content_hash, role, relative_path, media_type, "
            "byte_count, created_at, audio_sample_rate, audio_channel_count, "
            "audio_frame_count, audio_sample_format) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(asset_id),
                content_hash,
                role,
                relative_path,
                media_type,
                byte_count,
                _now_z(),
                48_000 if pcm else None,
                2 if pcm else None,
                byte_count // (4 * 2) if pcm else None,
                "f32le" if pcm else None,
            ),
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
        "VALUES (?, ?, ?, ?, ?, ?, ?, 48000, ?, 'ffprobe', '8.1.2', 1, ?)",
        (
            str(asset_id),
            str(parent),
            role,
            rate,
            channels,
            frames,
            "f" * 64,
            rate,
            _now_z(),
        ),
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


def create_seed_files(root: Path, seed: Seed) -> dict[str, Path]:
    """Write the on-disk files for project A's closure assets.

    Returns a map of relative path → absolute file path so tests can
    delete one file to exercise the missing-asset paths.
    """
    conn = sqlite3.connect(f"file:{seed.db_path}?mode=ro", uri=True)
    try:
        source_rel = conn.execute(
            "SELECT relative_path FROM assets WHERE id = ?", (seed.src_a,)
        ).fetchone()[0]
    finally:
        conn.close()
    files: dict[str, bytes] = {
        source_rel: SRC_CONTENT_A,
        f"data/assets/{CAN_HASH_A}.pcm": CAN_CONTENT_A,
        f"data/assets/{DMX_HASH_A}.pcm": DMX_CONTENT_A,
        f"data/assets/{STEM1_HASH_A}.pcm": STEM1_CONTENT_A,
        f"data/assets/{STEM2_HASH_A}.pcm": STEM2_CONTENT_A,
        f"data/assets/{RES_HASH_A}.pcm": RES_CONTENT_A,
        f"data/assets/{PB_HASH_A}.pcm": PB_CONTENT_A,
    }
    created: dict[str, Path] = {}
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        created[rel] = path
    # Waveform cache tree for the canonical PCM (optional, reproducible).
    wf_dir = root / "cache" / "waveforms" / WF_HASH_A
    wf_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = wf_dir / "manifest.json"
    manifest_path.write_text('{"ok": true}')
    created[f"cache/waveforms/{WF_HASH_A}/manifest.json"] = manifest_path
    tile_path = wf_dir / "tile0.bin"
    tile_path.write_bytes(b"\x07" * 5000)
    created[f"cache/waveforms/{WF_HASH_A}/tile0.bin"] = tile_path
    return created
