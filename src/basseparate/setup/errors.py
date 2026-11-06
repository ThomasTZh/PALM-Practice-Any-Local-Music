"""Setup errors shared by the installer modules and HTTP layer."""

from __future__ import annotations


class SetupError(RuntimeError):
    """A setup action failed with a user-facing message."""


class DownloadError(SetupError):
    """A pinned download was refused, interrupted or failed verification."""


class SetupInstallError(SetupError):
    """A model, tool or environment could not be installed."""


class SetupCancelled(SetupError):
    """The setup job was cancelled."""
