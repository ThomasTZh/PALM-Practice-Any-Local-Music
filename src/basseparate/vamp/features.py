"""Validated Vamp feature boundary.

The Piper host returns JSON-shaped features; this module parses them once,
before any grid logic sees the data. Times are seconds relative to the
analysed source. Source-frame conversion is the grid builder's job.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

SUPPORTED_BPB = frozenset({2, 3, 4, 6, 7})


class VampFeatureError(ValueError):
    """The Vamp host returned malformed or inconsistent features."""


@dataclass(frozen=True, slots=True)
class VampEvent:
    time_seconds: float
    label: str | None = None
    values: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class VampAnalysis:
    plugin_key: str
    plugin_version: str
    sample_rate: int
    bpb: int
    features: dict[str, tuple[VampEvent, ...]] = field(default_factory=dict)

    @property
    def beats(self) -> tuple[VampEvent, ...]:
        return self.features.get("beats", ())

    @property
    def bars(self) -> tuple[VampEvent, ...]:
        return self.features.get("bars", ())

    def to_payload(self) -> dict[str, Any]:
        return {
            "plugin": self.plugin_key,
            "plugin_version": self.plugin_version,
            "sample_rate": self.sample_rate,
            "bpb": self.bpb,
            "features": {
                name: [
                    {
                        "time_seconds": event.time_seconds,
                        "label": event.label,
                        "values": list(event.values),
                    }
                    for event in events
                ]
                for name, events in self.features.items()
            },
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> VampAnalysis:
        plugin_key = payload.get("plugin")
        if not isinstance(plugin_key, str) or not plugin_key:
            raise VampFeatureError("features are missing the plugin key")
        version = payload.get("plugin_version", "")
        if not isinstance(version, str):
            raise VampFeatureError("plugin_version must be a string")
        sample_rate = payload.get("sample_rate")
        if not isinstance(sample_rate, int) or sample_rate <= 0:
            raise VampFeatureError("features have an invalid sample rate")
        bpb = payload.get("bpb")
        if not isinstance(bpb, int) or bpb not in SUPPORTED_BPB:
            raise VampFeatureError(
                "features have an unsupported beats-per-bar value; expected one of "
                + ", ".join(str(value) for value in sorted(SUPPORTED_BPB))
            )
        raw_features = payload.get("features")
        if not isinstance(raw_features, dict):
            raise VampFeatureError("features payload is missing the features object")
        if "beats" not in raw_features:
            raise VampFeatureError("features payload is missing beats")
        if "bars" not in raw_features:
            raise VampFeatureError("features payload is missing bars")

        parsed: dict[str, tuple[VampEvent, ...]] = {}
        for name, rows in raw_features.items():
            if not isinstance(name, str) or not isinstance(rows, list | tuple):
                raise VampFeatureError(f"feature {name!r} must be a list")
            events: list[VampEvent] = []
            previous = -math.inf
            for row in rows:
                if not isinstance(row, dict):
                    raise VampFeatureError(f"feature {name!r} contains a non-object row")
                seconds = row.get("time_seconds")
                if not isinstance(seconds, int | float) or isinstance(seconds, bool):
                    raise VampFeatureError(f"feature {name!r} has a non-numeric timestamp")
                value = float(seconds)
                if not math.isfinite(value):
                    raise VampFeatureError(f"feature {name!r} has a non-finite timestamp")
                if value < 0:
                    raise VampFeatureError(f"feature {name!r} has a negative timestamp")
                if value < previous:
                    raise VampFeatureError(f"feature {name!r} timestamps must be monotonic")
                previous = value
                label = row.get("label")
                if label is not None and not isinstance(label, str):
                    raise VampFeatureError(f"feature {name!r} label must be a string")
                values = row.get("values", ())
                if not isinstance(values, list | tuple):
                    raise VampFeatureError(f"feature {name!r} values must be a list")
                event_values: list[float] = []
                for item in values:
                    if not isinstance(item, int | float) or isinstance(item, bool):
                        raise VampFeatureError(f"feature {name!r} has a non-numeric value")
                    event_values.append(float(item))
                events.append(
                    VampEvent(
                        time_seconds=value,
                        label=label,
                        values=tuple(event_values),
                    )
                )
            parsed[name] = tuple(events)
        if not parsed["beats"]:
            raise VampFeatureError("features payload contains no beats")
        return cls(
            plugin_key=plugin_key,
            plugin_version=version,
            sample_rate=sample_rate,
            bpb=bpb,
            features=parsed,
        )
