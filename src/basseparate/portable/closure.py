"""Dependency closure for the portable project format (M2.14, spec §16).

Computes, for one project, exactly which database rows and which files
belong to it: the asset closure (original file, canonical PCM,
monitoring downmix, every retained stem, the bass residual,
representations, waveform caches) and the analysis provenance
(separation run records + checked-in model registry metadata).

The closure is a pure reader: it opens nothing for writing and never
mutates the source store. M2.15 writes the archive from the
``PortablePlan``; the database builder (``database.py``) selects the
same rows for the project-only database.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from basseparate.domain.separation import SeparationResultSet, StemRecord
from basseparate.models.registry import REGISTRY
from basseparate.portable.format import asset_member_path, waveform_cache_member_prefix

#: Roles whose assets are essential to the project (§16.2).
#: ``derived_pcm`` assets are essential unless they are pure
#: playback-rate caches (classified per representation below).
_ALWAYS_ESSENTIAL_ROLES = frozenset({"source_original", "source_pcm", "stem"})

#: Provenance payload document versions.
PROVENANCE_PAYLOAD_VERSION = 1


class PortableFormatError(ValueError):
    """Raised when the source store cannot form a portable plan."""


@dataclass(frozen=True, slots=True)
class PortableAsset:
    """One asset file included in the archive."""

    asset_id: str
    content_hash: str
    role: str
    relative_path: str
    media_type: str
    byte_count: int
    member: str
    essential: bool


@dataclass(frozen=True, slots=True)
class PortableWaveformCache:
    """One waveform cache directory tree included in the archive.

    Optional: caches are reproducible from the source PCM (§16.2).
    """

    cache_id: str
    asset_id: str
    source_hash: str
    member_prefix: str


@dataclass(frozen=True, slots=True)
class PortablePlan:
    """Everything the archive writer and the database builder need."""

    project_id: str
    #: The ``projects`` row as a dict (column name → value).
    project_row: dict[str, Any]
    assets: tuple[PortableAsset, ...]
    waveform_caches: tuple[PortableWaveformCache, ...]
    #: Full separation run records (parsed ``record_json`` dicts).
    separation_runs: tuple[dict[str, Any], ...]
    #: Derived id sets for the database builder's row selection.
    asset_ids: frozenset[str]
    result_set_ids: frozenset[str]
    run_ids: frozenset[str]
    #: Activation artifact IDs whose files travel with the archive
    #: (optional raw arrays, M3.18 §20.8-§20.9).
    rhythm_artifact_ids: tuple[str, ...] = ()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _original_filename(conn: sqlite3.Connection, project_id: str) -> str | None:
    """The upload file name recorded by the project's import, if any."""
    rows = conn.execute(
        "SELECT filename FROM imports WHERE project_id = ? "
        "ORDER BY updated_at DESC, id",
        (project_id,),
    ).fetchall()
    for row in rows:
        filename: str | None = row["filename"]
        if filename:
            return filename
    return None


def _result_set_records(conn: sqlite3.Connection, project_id: str) -> list[SeparationResultSet]:
    rows = conn.execute(
        "SELECT record_json FROM separation_result_sets WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    records: list[SeparationResultSet] = []
    for row in rows:
        try:
            records.append(SeparationResultSet.model_validate_json(row["record_json"]))
        except ValueError as exc:
            raise PortableFormatError(
                f"malformed separation result set record: {exc}"
            ) from exc
    return records


def _stem_records(conn: sqlite3.Connection, result_set_ids: frozenset[str]) -> list[StemRecord]:
    if not result_set_ids:
        return []
    placeholders = ",".join("?" for _ in result_set_ids)
    rows = conn.execute(
        f"SELECT record_json FROM stems WHERE result_set_id IN ({placeholders})",
        tuple(sorted(result_set_ids)),
    ).fetchall()
    records: list[StemRecord] = []
    for row in rows:
        try:
            records.append(StemRecord.model_validate_json(row["record_json"]))
        except ValueError as exc:
            raise PortableFormatError(f"malformed stem record: {exc}") from exc
    return records


def _representation_roles(
    conn: sqlite3.Connection, asset_ids: frozenset[str]
) -> dict[str, set[str]]:
    """Map asset id → set of representation roles."""
    if not asset_ids:
        return {}
    placeholders = ",".join("?" for _ in asset_ids)
    rows = conn.execute(
        f"SELECT asset_id, role FROM representations WHERE asset_id IN ({placeholders})",
        tuple(sorted(asset_ids)),
    ).fetchall()
    roles: dict[str, set[str]] = {}
    for row in rows:
        roles.setdefault(row["asset_id"], set()).add(row["role"])
    return roles


def _parent_ids(conn: sqlite3.Connection, asset_ids: frozenset[str]) -> set[str]:
    if not asset_ids:
        return set()
    placeholders = ",".join("?" for _ in asset_ids)
    rows = conn.execute(
        "SELECT parent_asset_id FROM representations "
        f"WHERE asset_id IN ({placeholders}) AND parent_asset_id IS NOT NULL",
        tuple(sorted(asset_ids)),
    ).fetchall()
    return {row["parent_asset_id"] for row in rows}


def _is_essential(role: str, representation_roles: set[str]) -> bool:
    """Essential/optional classification for one asset (§16.2, §16.4).

    Essential: the original file, the canonical PCM, the stems, and
    derived PCM that is not a pure playback-rate cache (the monitoring
    downmix). Optional (reproducible): playback-rate caches.
    """
    if role in _ALWAYS_ESSENTIAL_ROLES:
        return True
    if role == "derived_pcm":
        # A derived PCM whose only representations are playback-rate
        # caches is optional; anything else (e.g. the monitoring
        # downmix) is essential. No representation rows is treated as
        # essential (never drop what cannot be proven reproducible).
        return not representation_roles or not representation_roles <= {"playback_rate"}
    return False


def compute_portable_plan(conn: sqlite3.Connection, project_id: str) -> PortablePlan:
    """Compute the portable dependency closure for one project.

    The caller owns the connection; this runs a series of reads in the
    connection's current transaction mode. Raises
    ``PortableFormatError`` for a missing project or a dangling asset
    reference.
    """
    previous_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return _compute_portable_plan(conn, project_id)
    finally:
        conn.row_factory = previous_row_factory


def _compute_portable_plan(conn: sqlite3.Connection, project_id: str) -> PortablePlan:
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None:
        raise PortableFormatError(f"no such project: {project_id}")
    project_row = _row_to_dict(project)

    # Seed the asset closure from the project's own references.
    asset_ids: set[str] = set()
    for column in ("source_asset_id", "canonical_asset_id", "monitoring_asset_id"):
        value = project_row.get(column)
        if value:
            asset_ids.add(value)
    for row in conn.execute(
        "SELECT asset_id FROM project_assets WHERE project_id = ?", (project_id,)
    ):
        asset_ids.add(row["asset_id"])

    # Result sets and stems of the project contribute their asset refs.
    result_sets = _result_set_records(conn, project_id)
    result_set_ids = frozenset(str(rs.id) for rs in result_sets)
    for rs in result_sets:
        asset_ids.add(str(rs.source.asset_id))
        asset_ids.add(str(rs.reference_mix.asset_id))
        if rs.bass_residual_asset_id is not None:
            asset_ids.add(str(rs.bass_residual_asset_id))
    for stem in _stem_records(conn, result_set_ids):
        asset_ids.add(str(stem.audio_asset_id))

    # Fixpoint: representation parents stay resolvable in the portable
    # DB (representations.parent_asset_id is a nullable FK).
    while True:
        parents = _parent_ids(conn, frozenset(asset_ids))
        if parents <= asset_ids:
            break
        asset_ids |= parents
    closed_asset_ids: frozenset[str] = frozenset(asset_ids)

    # Resolve the assets; a missing row is a dangling reference.
    placeholders = ",".join("?" for _ in closed_asset_ids) if closed_asset_ids else "NULL"
    rows = conn.execute(
        f"SELECT * FROM assets WHERE id IN ({placeholders})",
        tuple(sorted(closed_asset_ids)),
    ).fetchall()
    found = {row["id"] for row in rows}
    missing = closed_asset_ids - found
    if missing:
        sample = ", ".join(sorted(missing)[:3])
        suffix = "…" if len(missing) > 3 else ""
        raise PortableFormatError(
            f"dangling asset references in project {project_id}: {sample}{suffix}"
        )

    representation_roles = _representation_roles(conn, closed_asset_ids)
    filename = _original_filename(conn, project_id)
    assets = tuple(
        PortableAsset(
            asset_id=row["id"],
            content_hash=row["content_hash"],
            role=row["role"],
            relative_path=row["relative_path"],
            media_type=row["media_type"],
            byte_count=row["byte_count"],
            member=asset_member_path(row["content_hash"], row["role"], filename),
            essential=_is_essential(row["role"], representation_roles.get(row["id"], set())),
        )
        for row in rows
    )
    assets = tuple(sorted(assets, key=lambda a: a.member))

    # Waveform caches of the closure assets (optional, reproducible).
    cache_rows = conn.execute(
        f"SELECT id, asset_id, source_hash FROM waveform_caches "
        f"WHERE asset_id IN ({placeholders})",
        tuple(sorted(closed_asset_ids)),
    ).fetchall()
    waveform_caches = tuple(
        PortableWaveformCache(
            cache_id=row["id"],
            asset_id=row["asset_id"],
            source_hash=row["source_hash"],
            member_prefix=waveform_cache_member_prefix(row["source_hash"]),
        )
        for row in sorted(cache_rows, key=lambda r: r["source_hash"])
    )

    # Provenance: the project's separation run records.
    run_rows = conn.execute(
        "SELECT record_json FROM separation_runs WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    separation_runs: tuple[dict[str, Any], ...] = tuple(
        _parse_run_record(row["record_json"]) for row in run_rows
    )
    run_ids = frozenset(str(run["id"]) for run in separation_runs)

    rhythm_artifact_ids = tuple(
        row["id"]
        for row in conn.execute(
            "SELECT id FROM rhythm_activation_artifacts WHERE project_id = ? ORDER BY id",
            (project_id,),
        )
    )

    return PortablePlan(
        project_id=project_id,
        project_row=project_row,
        assets=assets,
        waveform_caches=waveform_caches,
        separation_runs=separation_runs,
        asset_ids=closed_asset_ids,
        result_set_ids=result_set_ids,
        run_ids=run_ids,
        rhythm_artifact_ids=rhythm_artifact_ids,
    )


def _parse_run_record(record_json: str) -> dict[str, Any]:
    try:
        record = json.loads(record_json)
    except json.JSONDecodeError as exc:
        raise PortableFormatError(f"malformed separation run record: {exc}") from exc
    if not isinstance(record, dict):
        raise PortableFormatError("separation run record is not an object")
    return record


def separation_runs_payload(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The ``provenance/separation-runs.json`` document (§16.1)."""
    return {"version": PROVENANCE_PAYLOAD_VERSION, "runs": list(runs)}


def model_manifests_payload() -> dict[str, Any]:
    """The ``provenance/model-manifests.json`` document (§16.1).

    Checked-in registry metadata only (names, hashes, sizes,
    licenses). Model weights are never part of the archive (§16.3).
    """
    return {
        "version": PROVENANCE_PAYLOAD_VERSION,
        "models": [asdict(manifest) for model_id, manifest in sorted(REGISTRY.items())],
    }
