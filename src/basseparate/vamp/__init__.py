"""Vamp-based rhythm analysis (personal local build).

This package is not a general Vamp SDK. It runs a configured Piper host and
converts the QM bar/beat features into the application's rhythm branch model.
"""

from basseparate.vamp.features import VampAnalysis, VampEvent, VampFeatureError
from basseparate.vamp.grid import VampGridError, build_branch_from_vamp

__all__ = [
    "VampAnalysis",
    "VampEvent",
    "VampFeatureError",
    "VampGridError",
    "build_branch_from_vamp",
]
