"""Real Sonic Annotator 1.7 run against the preserved chord fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from basseparate import features
from basseparate.sonic_annotator import SonicAnnotatorBackend

ROOT = Path(__file__).resolve().parents[3]
CHORDS = ROOT / "tests" / "fixtures" / "audio" / "chords_c_am_f_g.wav"
SONIC = ROOT / "storage" / "tools" / "sonic-annotator-1.7.0" / "squashfs-root" / "AppRun"

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not SONIC.is_file(), reason="preserved Sonic Annotator 1.7 is absent")
def test_sonic_backend_returns_chords_key_beats_and_bars() -> None:
    backend = SonicAnnotatorBackend()
    try:
        plugins = backend.discover_plugins()
        assert plugins.chord.plugin == "chordino"
        assert plugins.key.plugin == "qm-keydetector"
        assert plugins.beats.plugin == "qm-barbeattracker"
        assert plugins.bars.plugin == "qm-barbeattracker"
        signal, rate = features.load_audio_mono(CHORDS)
        result = features.analyze_signal(
            signal,
            sample_rate=rate,
            source_sha256="d" * 64,
            backend=backend,
            lead_in_seconds=0.0,
        )
    finally:
        backend.close()
    labels = [chord.label for chord in result.chords if chord.label != "N"]
    assert labels == ["C", "Am", "F", "G"]
    assert result.key.label == "C major"
    assert result.key.tonic == 1
    assert result.key.mode == 0
    assert result.bpm is not None
    assert abs(result.bpm - 136.0) <= 0.5
    assert result.grid.beats
    assert result.grid.bars
    assert result.grid.first_beat is not None
    assert result.meta.plugins[0].display_name == "Chordino"
