"""Storage package for basseparate.

Contains:
- ``paths``: XDG directory layout and initialization (M0.3).
- ``db``: SQLite connection, initialization, migrations (M0.5).
- ``repository``: project/asset repository layer (M0.5).
"""

from basseparate.storage.db import DatabaseError, UnsupportedSchemaVersion, initialize_database
from basseparate.storage.paths import (
    StorageError,
    StoragePaths,
    default_storage_paths,
    initialize_storage_paths,
    resolve_storage_paths,
)
from basseparate.storage.repository import (
    ExportArtifactRepository,
    ImportRepository,
    JobRepository,
    PortableArtifactRepository,
    ProjectRepository,
    RepresentationRepository,
    RhythmBranchStaleRevisionError,
    RhythmRepository,
    SeparationRepository,
    WaveformCacheRepository,
)

__all__ = [
    "DatabaseError",
    "ExportArtifactRepository",
    "ImportRepository",
    "JobRepository",
    "PortableArtifactRepository",
    "ProjectRepository",
    "RepresentationRepository",
    "RhythmBranchStaleRevisionError",
    "RhythmRepository",
    "SeparationRepository",
    "StorageError",
    "StoragePaths",
    "UnsupportedSchemaVersion",
    "WaveformCacheRepository",
    "default_storage_paths",
    "initialize_database",
    "initialize_storage_paths",
    "resolve_storage_paths",
]
