"""Integration tests against the preserved Piper server and Vamp plugin pack.

These tests use the real offline assets: 122 plugins listed by display name,
Chordino for chords, Key Detector for the key and Bar and Beat Tracker for the
grid. They are marked ``integration`` because they start a child process.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from basseparate import features
from basseparate.features import analyze_file
from basseparate.piper import (
    AnalysisCancelled,
    PiperPaths,
    PiperUnavailable,
)

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[3]
AUDIO = ROOT / "tests" / "fixtures" / "audio"
CHORDS = AUDIO / "chords_c_am_f_g.wav"
CLICK = AUDIO / "click_120bpm.wav"


@pytest.fixture(scope="module")
def project_paths() -> PiperPaths:
    paths = PiperPaths.for_project(ROOT)
    paths.validate()
    return paths


def _labels(result: features.AnalysisResult) -> list[str]:
    return [chord.label for chord in result.chords if chord.label != "N"]


def test_chords_key_and_grid_on_the_c_am_f_g_fixture(
    tmp_path: Path, project_paths: PiperPaths
) -> None:
    result = analyze_file(CHORDS, cache_dir=tmp_path / "cache", piper_paths=project_paths)
    assert result.cached is False
    # The four triads, in order. "N" is Chordino's raw no-chord marker and is
    # intentionally kept in the file for the UI to decide about.
    assert _labels(result) == ["C", "Am", "F", "G"]
    assert result.chord_labels[0] == "N"
    assert all(":" not in label for label in _labels(result))
    assert result.key_label == "C major"
    assert result.key.tonic == 1
    assert result.key.mode == 0
    assert result.bpm is not None
    assert result.grid.first_beat is not None
    assert 0.0 <= result.grid.first_beat < 0.5
    assert result.grid.bar_count >= 4
    assert result.meta.sample_rate == 44_100
    assert [plugin.display_name for plugin in result.meta.plugins] == [
        "Chordino",
        "Key Detector",
        "Bar and Beat Tracker",
    ]
    # The pack is resolved by display name; the embed key is recorded, not used
    # as the lookup key.
    assert all(plugin.key.startswith("embed-") for plugin in result.meta.plugins)
    assert result.meta.bpb == 4


def test_click_fixture_recovers_120_bpm_and_the_downbeat(
    tmp_path: Path, project_paths: PiperPaths
) -> None:
    result = analyze_file(
        CLICK,
        cache_dir=tmp_path / "cache",
        piper_paths=project_paths,
        lead_in_seconds=features.WARM_UP_SECONDS,
    )
    assert result.bpm is not None
    assert abs(result.bpm - 120.0) <= 0.5
    assert result.grid.bar_count == 2
    assert result.grid.first_beat == 0.0
    assert len(result.grid.beats) == 8
    assert result.meta.lead_in_seconds > 0.0


def test_second_run_reuses_cache_and_starts_no_server(
    tmp_path: Path,
    project_paths: PiperPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "cache"
    first = analyze_file(CHORDS, cache_dir=cache, piper_paths=project_paths)
    assert first.cached is False

    class ExplodingSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("the cached run must not start a Piper server")

    def exploding_decode(*args: object, **kwargs: object) -> object:
        raise AssertionError("the cached run must not decode the recording again")

    monkeypatch.setattr(features, "PiperSession", ExplodingSession)
    monkeypatch.setattr(features, "load_audio_mono", exploding_decode)
    second = analyze_file(CHORDS, cache_dir=cache, piper_paths=project_paths)
    assert second.cached is True
    assert second.meta.cache_key == first.meta.cache_key
    assert second.chord_labels == first.chord_labels
    assert second.bpm == first.bpm


def test_cancellation_leaves_no_cache_entry(tmp_path: Path, project_paths: PiperPaths) -> None:
    cache = tmp_path / "cache"
    cancelled = threading.Event()

    def progress(fraction: float, message: str) -> None:
        if fraction > 0.0:
            cancelled.set()

    with pytest.raises(AnalysisCancelled):
        analyze_file(
            CHORDS,
            cache_dir=cache,
            piper_paths=project_paths,
            is_cancelled=cancelled.is_set,
            on_progress=progress,
        )
    assert not cache.exists() or not any(cache.iterdir())


def test_missing_storage_tools_sv_is_actionable(tmp_path: Path) -> None:
    paths = PiperPaths.for_project(tmp_path)
    with pytest.raises(PiperUnavailable) as error:
        paths.validate()
    message = str(error.value)
    assert "Piper server not found" in message
    assert "storage/tools/sv" in message
    assert "make bootstrap" in message


def test_missing_plugin_pack_is_actionable(tmp_path: Path, project_paths: PiperPaths) -> None:
    paths = PiperPaths(
        server=project_paths.server,
        plugin_path=tmp_path / "absent-plugins",
        library_path=project_paths.library_path,
    )
    with pytest.raises(PiperUnavailable) as error:
        paths.validate()
    assert "Vamp plugin pack not found" in str(error.value)
    assert str(paths.plugin_path) in str(error.value)


def test_missing_plugin_in_the_pack_is_actionable(
    tmp_path: Path, project_paths: PiperPaths
) -> None:
    pack = tmp_path / "beatroot-only"
    pack.mkdir()
    (pack / "beatroot-vamp.so").symlink_to(
        ROOT / "storage" / "tools" / "vamp-plugins" / "beatroot-vamp.so"
    )
    paths = PiperPaths(
        server=project_paths.server,
        plugin_path=pack,
        library_path=project_paths.library_path,
    )
    with pytest.raises(PiperUnavailable) as error:
        analyze_file(CHORDS, piper_paths=paths)
    message = str(error.value)
    assert "Chordino" in message
    assert "display name" in message
