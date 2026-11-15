"""Backend protocol, Piper routing and backend-aware cache separation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from basseparate import analysis_backend, features
from basseparate.analysis_backend import (
    AnalysisBackendUnavailable,
    BackendPlugin,
    BackendResult,
    PiperBackend,
    default_backend,
    resolve_backend,
)
from basseparate.piper import LoadedPlugin, PiperPaths


def ts(seconds: float) -> dict[str, object]:
    return {"s": int(seconds), "n": int((seconds % 1) * 1_000_000_000)}


def fake_features(label: str = "C major") -> dict[str, dict[str, list[dict[str, object]]]]:
    return {
        features.CHORD_PLUGIN: {
            features.CHORD_OUTPUT: [{"timestamp": ts(0), "label": "C", "featureValues": []}]
        },
        features.KEY_PLUGIN: {
            features.KEY_OUTPUT: [{"timestamp": ts(0), "label": label, "featureValues": [1]}]
        },
        features.BEAT_PLUGIN: {
            features.BEATS_OUTPUT: [
                {"timestamp": ts(0.0), "label": "1", "featureValues": []},
                {"timestamp": ts(0.5), "label": "2", "featureValues": []},
            ],
            features.BARS_OUTPUT: [{"timestamp": ts(0.0), "label": "1", "featureValues": []}],
        },
    }


@dataclass
class FakeBackend:
    id: str = "sonic"
    version: str = "1"
    label: str = "C major"
    calls: list[dict[str, object]] | None = None

    def analyze(
        self,
        signal,
        *,
        sample_rate,
        bpb,
        lead_in_seconds,
        specs,
        is_cancelled=None,
        on_progress=None,
    ) -> BackendResult:
        if self.calls is None:
            self.calls = []
        self.calls.append(
            {
                "sample_rate": sample_rate,
                "bpb": bpb,
                "lead": lead_in_seconds,
                "specs": tuple(specs),
                "frames": int(signal.shape[0]),
            }
        )
        if on_progress is not None:
            on_progress(0.5, "fake")
        return BackendResult(
            features=fake_features(self.label),
            plugins=tuple(
                BackendPlugin(
                    role=name,
                    display_name=name,
                    key=f"fake:{name}",
                    version=self.version,
                    parameters=dict(parameters),
                    block_size=1024,
                    step_size=512,
                )
                for name, parameters in specs
            ),
            elapsed_seconds=0.01,
        )


def test_default_backend_is_piper_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(default_backend(), PiperBackend)
    monkeypatch.setattr(analysis_backend, "sys", SimpleNamespace(platform="win32"))
    with pytest.raises(AnalysisBackendUnavailable, match="no analysis backend"):
        default_backend()


def test_resolve_backend_prefers_explicit_and_preserves_piper_paths(tmp_path: Path) -> None:
    fake = FakeBackend()
    paths = PiperPaths(
        server=tmp_path / "piper",
        plugin_path=tmp_path / "plugins",
        library_path=tmp_path / "lib",
    )
    assert resolve_backend(fake, piper_paths=paths) is fake
    resolved = resolve_backend(None, piper_paths=paths)
    assert isinstance(resolved, PiperBackend)
    assert resolved.paths == paths
    assert resolved.cache_identity == "piper:1"


def test_analyze_signal_uses_injected_backend_and_same_parsed_model(tmp_path: Path) -> None:
    fake = FakeBackend(label="D minor")
    result = features.analyze_signal(
        np.zeros(16, dtype=np.float32),
        sample_rate=8,
        source_sha256="a" * 64,
        cache_dir=tmp_path / "cache",
        backend=fake,
    )
    assert result.cached is False
    assert result.key.label == "D minor"
    assert result.chord_labels == ("C",)
    assert result.bpm == 120.0
    assert [plugin.display_name for plugin in result.meta.plugins] == [
        features.CHORD_PLUGIN,
        features.KEY_PLUGIN,
        features.BEAT_PLUGIN,
    ]
    assert fake.calls is not None
    assert fake.calls[0]["sample_rate"] == 8
    assert fake.calls[0]["frames"] == 16


def test_backend_identity_participates_in_the_cache_key() -> None:
    base = {
        "sample_rate": 8,
        "bpb": 4,
        "lead_in_seconds": 0.0,
        "specs": features.plugin_specs(4),
    }
    piper = features.analysis_cache_key("a" * 64, backend_id="piper", backend_version="1", **base)
    sonic = features.analysis_cache_key("a" * 64, backend_id="sonic", backend_version="1", **base)
    other_version = features.analysis_cache_key(
        "a" * 64, backend_id="sonic", backend_version="2", **base
    )
    assert piper != sonic
    assert sonic != other_version


def test_cache_entries_from_different_backends_do_not_collide(tmp_path: Path) -> None:
    signal = np.zeros(16, dtype=np.float32)
    cache = tmp_path / "cache"
    first_backend = FakeBackend(id="sonic", version="1", label="C major")
    second_backend = FakeBackend(id="piper", version="1", label="C major")
    first = features.analyze_signal(
        signal, sample_rate=8, source_sha256="b" * 64, cache_dir=cache, backend=first_backend
    )
    second = features.analyze_signal(
        signal, sample_rate=8, source_sha256="b" * 64, cache_dir=cache, backend=second_backend
    )
    assert first.cached is False
    assert second.cached is False
    assert first.meta.cache_key != second.meta.cache_key
    assert len([path for path in cache.iterdir() if path.is_dir()]) == 2
    again = features.analyze_signal(
        signal, sample_rate=8, source_sha256="b" * 64, cache_dir=cache, backend=second_backend
    )
    assert again.cached is True
    assert again.meta.cache_key == second.meta.cache_key


class FakeSession:
    paths_seen: list[PiperPaths] = []
    signals: dict[str, int] = {}

    def __init__(self, paths: PiperPaths, *, timeout_seconds: float, is_cancelled, on_progress):
        self.paths = paths
        self.timeout_seconds = timeout_seconds
        self.is_cancelled = is_cancelled
        self.on_progress = on_progress
        FakeSession.paths_seen.append(paths)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def analyze(self, name, signal, *, sample_rate, parameters):
        FakeSession.signals[name] = int(signal.shape[0])
        plugin = LoadedPlugin(
            display_name=name,
            key=f"fake:{name}",
            version="1",
            handle=1,
            block_size=1024,
            step_size=512,
            parameters=dict(parameters),
        )
        return plugin, {
            features.CHORD_OUTPUT: []
        } if name == features.CHORD_PLUGIN else fake_features()


def test_piper_backend_routes_through_piper_session_and_pads_beats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSession.paths_seen.clear()
    FakeSession.signals.clear()
    monkeypatch.setattr(analysis_backend, "PiperSession", FakeSession)
    paths = PiperPaths(Path("/piper"), Path("/plugins"), Path("/lib"))
    backend = PiperBackend(paths=paths, timeout_seconds=12)
    result = backend.analyze(
        np.zeros(100, dtype=np.float32),
        sample_rate=10,
        bpb=4,
        lead_in_seconds=0.5,
        specs=features.plugin_specs(4),
    )
    assert len(FakeSession.paths_seen) == 3
    assert all(item == paths for item in FakeSession.paths_seen)
    assert FakeSession.signals[features.CHORD_PLUGIN] == 100
    assert FakeSession.signals[features.KEY_PLUGIN] == 100
    assert FakeSession.signals[features.BEAT_PLUGIN] == 100 + 5 + 20
    assert set(result.features) == {
        features.CHORD_PLUGIN,
        features.KEY_PLUGIN,
        features.BEAT_PLUGIN,
    }
    assert [plugin.role for plugin in result.plugins] == [
        features.CHORD_PLUGIN,
        features.KEY_PLUGIN,
        features.BEAT_PLUGIN,
    ]


def test_non_linux_default_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis_backend, "sys", SimpleNamespace(platform="darwin"))
    with pytest.raises(AnalysisBackendUnavailable, match="Piper backend is available on Linux"):
        features.analyze_signal(
            np.zeros(8, dtype=np.float32), sample_rate=8, source_sha256="c" * 64
        )
