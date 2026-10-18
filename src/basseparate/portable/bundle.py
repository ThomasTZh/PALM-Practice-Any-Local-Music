"""Validated import bundle for a portable project open (M2.16, spec §18).

The open pipeline validates the untrusted archive, reads its embedded
database through the application domain models, and remaps every row ID
(§18.5). The result is this bundle: plain validated domain records plus
the ``project_history`` rows, ready for a single-transaction insert by
``ProjectRepository.import_portable_bundle``.

Keeping the bundle in its own module avoids a cycle: the storage layer
consumes it, while ``portable.open`` builds it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from basseparate.domain.asset import AssetRecord
from basseparate.domain.import_record import ImportRecord
from basseparate.domain.marker import MarkerRecord
from basseparate.domain.media_job import MediaJob
from basseparate.domain.project import ProjectRecord
from basseparate.domain.representation import AudioRepresentation
from basseparate.domain.separation import SeparationResultSet, SeparationRun, StemRecord
from basseparate.domain.waveform import WaveformCacheRecord


@dataclass(frozen=True)
class HistoryRow:
    """One ``project_history`` row (undo/redo snapshot, spec §17.4)."""

    id: str
    project_id: str
    seq: int
    kind: str
    before_json: str
    after_json: str
    created_at: str


#: (project_id, asset_id, role) — one ``project_assets`` link.
AssetLink = tuple[str, str, str]


@dataclass(frozen=True)
class PortableImportBundle:
    """All rows of one opened working copy, ID-remapped and validated.

    Insert order is fixed by ``ProjectRepository.import_portable_bundle``:
    assets before the project row (FK targets), the project row last
    inside the transaction (§18.4.8).
    """

    project: ProjectRecord
    #: ``projects.history_seq`` undo/redo pointer (§17.4).
    history_seq: int
    #: Assets referenced by the working copy, with their final IDs.
    #: Content-addressed rows already present in the store are reused
    #: (``assets.content_hash`` is globally unique); the rest are new.
    assets: tuple[AssetRecord, ...]
    #: Asset IDs that the import must insert (new rows only).
    insert_asset_ids: frozenset[str]
    #: Final asset ID -> archive member holding its file (§18.4).
    asset_members: dict[str, str]
    asset_links: tuple[AssetLink, ...]
    imports: tuple[ImportRecord, ...]
    representations: tuple[AudioRepresentation, ...]
    waveform_caches: tuple[WaveformCacheRecord, ...]
    markers: tuple[MarkerRecord, ...]
    history: tuple[HistoryRow, ...]
    runs: tuple[SeparationRun, ...]
    result_sets: tuple[SeparationResultSet, ...]
    stems: tuple[StemRecord, ...]
    jobs: tuple[MediaJob, ...]
    #: §18.5 provenance (archived identity); ``None`` only for tests.
    portable_provenance: dict[str, Any] | None
