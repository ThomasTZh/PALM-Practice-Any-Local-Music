"""Project-only database builder for the portable project format.

M2.14 (spec §16.5): the portable archive carries a *project-only*
database, not a copy of the shared store. This module extracts one
project and its dependency closure into a fresh database:

1. A consistent snapshot of the source is taken with the SQLite
   ``backup`` API (WAL-safe; the live file bytes are never copied).
2. The snapshot's schema DDL is replayed into a fresh database
   (exact current schema, no data).
3. The closure rows are copied with streaming ``INSERT ... SELECT``
   statements, preserving internal IDs so restored references stay
   valid.
4. ``PRAGMA foreign_key_check`` and an isolation proof (exactly one
   project; no row referencing any other project) must pass.

The destination is built in a temporary file in the target directory
and moved into place atomically; on failure no destination file is
left behind. The portable database is self-contained: default
(delete) journal mode, no ``-wal``/``-shm`` sidecar dependency.
"""

from __future__ import annotations

import contextlib
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import quote

from basseparate.portable.closure import PortableFormatError, compute_portable_plan

#: Tables and their project-scope predicate, in copy order. Tables with
#: ``"assets"`` select on the closure asset ids; ``"stems"`` selects on
#: the closure result-set ids. ``export_artifacts`` is intentionally
#: absent: export deliverables are reproducible and excluded from the
#: portable format (M2.13).
_TABLE_PREDICATES: tuple[tuple[str, str, str], ...] = (
    ("projects", "id", "project"),
    ("assets", "id", "assets"),
    ("project_assets", "project_id", "project"),
    ("imports", "project_id", "project"),
    ("representations", "asset_id", "assets"),
    ("waveform_caches", "asset_id", "assets"),
    ("markers", "project_id", "project"),
    ("project_history", "project_id", "project"),
    ("separation_runs", "project_id", "project"),
    ("separation_result_sets", "project_id", "project"),
    ("stems", "result_set_id", "result_sets"),
    ("media_jobs", "project_id", "project"),
)

#: Tables with a ``project_id`` column checked by the isolation proof.
_PROJECT_SCOPED_TABLES: tuple[str, ...] = (
    "project_assets",
    "imports",
    "markers",
    "project_history",
    "separation_runs",
    "separation_result_sets",
    "media_jobs",
    "export_artifacts",
)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    """Open a database read-only (no WAL sidecar creation)."""
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _snapshot(source_db: Path, snapshot: Path) -> None:
    """Consistent snapshot of the source via the backup API (WAL-safe)."""
    source = _connect_read_only(source_db)
    try:
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _ddl_statements(snapshot: Path) -> tuple[list[str], int]:
    """The schema DDL of the snapshot (tables, indexes) and user_version.

    ``iterdump`` does not emit the schema version pragma in Python
    3.11, so it is read explicitly.
    """
    conn = _connect_read_only(snapshot)
    try:
        statements: list[str] = []
        for line in conn.iterdump():
            if line.startswith("CREATE TABLE") or line.startswith("CREATE INDEX"):
                statements.append(line)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        return statements, version
    finally:
        conn.close()


def _in_predicate(column: str, values: frozenset[str]) -> str:
    return f"{column} IN ({','.join('?' for _ in values)})"


def _copy_rows(
    new: sqlite3.Connection,
    project_id: str,
    asset_ids: frozenset[str],
    result_set_ids: frozenset[str],
) -> None:
    for table, column, scope in _TABLE_PREDICATES:
        if scope == "project":
            new.execute(
                f"INSERT INTO {table} SELECT * FROM snap.{table} WHERE {column} = ?",
                (project_id,),
            )
        elif scope == "assets" and asset_ids:
            new.execute(
                f"INSERT INTO {table} SELECT * FROM snap.{table} "
                f"WHERE {_in_predicate(column, asset_ids)}",
                tuple(sorted(asset_ids)),
            )
        elif scope == "result_sets" and result_set_ids:
            new.execute(
                f"INSERT INTO {table} SELECT * FROM snap.{table} "
                f"WHERE {_in_predicate(column, result_set_ids)}",
                tuple(sorted(result_set_ids)),
            )


def _attach_and_copy(
    new: sqlite3.Connection,
    snapshot: Path,
    project_id: str,
    asset_ids: frozenset[str],
    result_set_ids: frozenset[str],
) -> None:
    """Attach the snapshot, copy the closure rows, verify, and detach.

    The transaction is always closed (commit or rollback) before the
    detach so the attached database is never left locked.
    """
    new.execute("ATTACH DATABASE ? AS snap", (str(snapshot),))
    try:
        try:
            _copy_rows(new, project_id, asset_ids, result_set_ids)
            _verify(new, project_id)
            new.commit()
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                new.rollback()
            raise
    finally:
        new.execute("DETACH DATABASE snap")


def _verify(new: sqlite3.Connection, project_id: str) -> None:
    violations = new.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise PortableFormatError(
            f"foreign key violations in portable database: {violations[:3]}"
        )
    if new.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise PortableFormatError("integrity check failed on portable database")
    projects = new.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    if projects != 1:
        raise PortableFormatError(
            f"portable database must contain exactly one project, found {projects}"
        )
    if new.execute("SELECT id FROM projects").fetchone()[0] != project_id:
        raise PortableFormatError("portable database project id mismatch")
    for table in _PROJECT_SCOPED_TABLES:
        stray = new.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id IS NOT NULL "
            f"AND project_id != ?",
            (project_id,),
        ).fetchone()[0]
        if stray:
            raise PortableFormatError(
                f"portable database contains {stray} {table} row(s) of other projects"
            )


def build_portable_database(source_db: Path, project_id: str, destination: Path) -> None:
    """Build the project-only portable database at ``destination``.

    Raises ``PortableFormatError`` on a missing source/project, a
    dangling reference, an FK violation, or an isolation failure. On
    failure no destination file is left behind.
    """
    source_db = Path(source_db)
    destination = Path(destination)
    if not source_db.is_file():
        raise PortableFormatError(f"source database not found: {source_db}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    with tempfile.TemporaryDirectory(prefix="basseparate-portable-") as tmp_dir:
        snapshot = Path(tmp_dir) / "snapshot.sqlite"
        try:
            _snapshot(source_db, snapshot)
            statements, user_version = _ddl_statements(snapshot)
            if not any(s.startswith("CREATE TABLE projects") for s in statements):
                raise PortableFormatError("snapshot has no projects table")

            new = sqlite3.connect(str(partial))
            try:
                new.execute("PRAGMA foreign_keys = ON")
                for statement in statements:
                    new.execute(statement)
                new.execute(f"PRAGMA user_version = {int(user_version)}")
                # The closure is computed from the consistent snapshot.
                snap = _connect_read_only(snapshot)
                try:
                    plan = compute_portable_plan(snap, project_id)
                finally:
                    snap.close()
                _attach_and_copy(new, snapshot, project_id, plan.asset_ids, plan.result_set_ids)
            finally:
                new.close()
        except BaseException:
            with contextlib.suppress(OSError):
                partial.unlink()
            raise
    partial.replace(destination)
