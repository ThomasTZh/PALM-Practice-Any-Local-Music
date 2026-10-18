"""Portable project open error family (M2.16, spec §18).

``code`` values are stable API identifiers; the route layer maps each
code to its HTTP status. The pipeline (``portable.open``) and the
bounded archive transfer routes raise these classes; the repository
import raises them too, so a failed open has one error surface.

The module deliberately has no imports from other application modules:
it is shared by the storage layer and the API layer without cycles.
"""

from __future__ import annotations

from typing import Any


class PortableOpenError(Exception):
    """A portable open failed; ``code`` is stable for API mapping."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class PortableOpenNotZip(PortableOpenError):
    """The upload is not a readable ZIP archive."""

    def __init__(self, reason: str) -> None:
        super().__init__("ARCHIVE_NOT_ZIP", f"not a readable ZIP archive: {reason}")


class PortableOpenMemberLimit(PortableOpenError):
    """The archive has more members than the configured limit."""

    def __init__(self, count: int, limit: int) -> None:
        super().__init__(
            "ARCHIVE_MEMBER_LIMIT",
            f"archive has {count} members, limit is {limit}",
            {"count": count, "limit": limit},
        )


class PortableOpenUncompressedLimit(PortableOpenError):
    """The archive's total uncompressed size exceeds the configured limit."""

    def __init__(self, total: int, limit: int) -> None:
        super().__init__(
            "ARCHIVE_UNCOMPRESSED_LIMIT",
            f"archive uncompressed size {total} exceeds limit {limit}",
            {"total": total, "limit": limit},
        )


class PortableOpenManifestInvalid(PortableOpenError):
    """The manifest is missing, oversized, or fails validation."""

    def __init__(self, reason: str) -> None:
        super().__init__("ARCHIVE_MANIFEST_INVALID", f"invalid manifest: {reason}")


class PortableOpenVersionUnsupported(PortableOpenError):
    """The archive's format/container/project-schema version is unsupported."""

    def __init__(self, reason: str) -> None:
        super().__init__("ARCHIVE_VERSION_UNSUPPORTED", f"unsupported version: {reason}")


class PortableOpenMemberUnsafe(PortableOpenError):
    """A member name or type is unsafe (traversal, symlink, encrypted, ...)."""

    def __init__(self, member: str, reason: str) -> None:
        super().__init__(
            "ARCHIVE_MEMBER_UNSAFE",
            f"unsafe archive member {member!r}: {reason}",
            {"member": member, "reason": reason},
        )


class PortableOpenMemberMissing(PortableOpenError):
    """One or more essential members are absent from the archive."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = list(missing)
        super().__init__(
            "ARCHIVE_MEMBER_MISSING",
            "essential archive member(s) are missing",
            {"missing": self.missing},
        )


class PortableOpenMemberCorrupt(PortableOpenError):
    """An essential member's size or SHA-256 does not match the manifest."""

    def __init__(self, member: str, reason: str) -> None:
        super().__init__(
            "ARCHIVE_MEMBER_CORRUPT",
            f"archive member {member!r} is corrupt: {reason}",
            {"member": member, "reason": reason},
        )


class PortableOpenSchemaMismatch(PortableOpenError):
    """The embedded database's schema version does not match this build."""

    def __init__(self, version: int, expected: int) -> None:
        super().__init__(
            "ARCHIVE_SCHEMA_MISMATCH",
            f"embedded database schema version {version} does not match "
            f"supported version {expected}",
            {"version": version, "expected": expected},
        )


class PortableOpenDbInvalid(PortableOpenError):
    """The embedded database fails structural or isolation validation."""

    def __init__(self, reason: str) -> None:
        super().__init__("ARCHIVE_DB_INVALID", f"invalid embedded database: {reason}")


class PortableOpenNoSpace(PortableOpenError):
    """Not enough free disk space for extraction and asset restoration."""

    def __init__(self, needed_bytes: int, free_bytes: int) -> None:
        super().__init__(
            "OPEN_NO_SPACE",
            "not enough free disk space to open this project",
            {"needed_bytes": needed_bytes, "free_bytes": free_bytes},
        )


class PortableOpenIdConflict(PortableOpenError):
    """The archived project ID already exists (as-archived mode)."""

    def __init__(self, project_id: str) -> None:
        super().__init__(
            "OPEN_ID_CONFLICT",
            f"project {project_id} already exists; open as a new working copy instead",
            {"project_id": project_id},
        )
