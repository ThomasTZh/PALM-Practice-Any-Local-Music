"""Unit tests for the Vamp feature boundary parser."""

from __future__ import annotations

import pytest

from basseparate.vamp.features import VampAnalysis, VampFeatureError


def _payload() -> dict[str, object]:
    return {
        "plugin": "qm-vamp-plugins:qm-barbeattracker",
        "plugin_version": "1.0",
        "sample_rate": 48000,
        "bpb": 4,
        "features": {
            "beats": [
                {"time_seconds": 0.5, "label": "1"},
                {"time_seconds": 1.0, "label": "2"},
                {"time_seconds": 1.5, "label": "3"},
            ],
            "bars": [{"time_seconds": 0.5, "label": "1"}],
        },
    }


def test_parses_events_and_provenance() -> None:
    analysis = VampAnalysis.from_payload(_payload())
    assert analysis.plugin_key == "qm-vamp-plugins:qm-barbeattracker"
    assert analysis.plugin_version == "1.0"
    assert analysis.sample_rate == 48000
    assert analysis.bpb == 4
    assert [event.time_seconds for event in analysis.beats] == [0.5, 1.0, 1.5]
    assert analysis.beats[0].label == "1"


def test_requires_beat_and_bar_lists() -> None:
    payload = _payload()
    del payload["features"]["beats"]  # type: ignore[index]
    with pytest.raises(VampFeatureError, match="beats"):
        VampAnalysis.from_payload(payload)


def test_rejects_non_monotonic_beats() -> None:
    payload = _payload()
    payload["features"]["beats"] = [
        {"time_seconds": 0.5},
        {"time_seconds": 0.4},
    ]  # type: ignore[index]
    with pytest.raises(VampFeatureError, match="monotonic"):
        VampAnalysis.from_payload(payload)


def test_rejects_non_finite_or_negative_times() -> None:
    payload = _payload()
    payload["features"]["beats"] = [{"time_seconds": -1.0}]  # type: ignore[index]
    with pytest.raises(VampFeatureError, match="negative"):
        VampAnalysis.from_payload(payload)
