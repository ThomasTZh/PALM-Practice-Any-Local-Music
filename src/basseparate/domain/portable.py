"""Portable project artifact domain model (M2.15, milestone2.md §17).

A *portable save* captures the working project at its current revision
into a self-contained ``.basseparate`` archive and publishes it to
managed storage. One :class:`PortableArtifact` row is recorded per
successful save; the published file itself lives in the managed portable
store (``data/portable/<project_id>/<revision>-<sha12>.basseparate``).

Design rules encoded here:

- ``relative_path`` is relative to the data root; the download filename
  is user-friendly and independent of the managed name.
- ``saved_revision`` is the ``projects.revision`` captured at save
  time; the UI compares it with the live revision to show "newer
  unsaved changes" (spec §17.5).
- ``sha256`` is the hash of the published archive file, so a row and a
  file always agree.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from basseparate.domain.common import Sha256Hash, UtcTimestamp, Uuid


class PortableArtifact(BaseModel):
    """One successfully published portable project archive (§17.5)."""

    model_config = ConfigDict(frozen=True)

    id: Uuid
    project_id: Uuid
    saved_revision: int = Field(ge=0)
    sha256: Sha256Hash
    byte_size: int = Field(ge=1)
    relative_path: str
    download_filename: str
    created_at: UtcTimestamp
