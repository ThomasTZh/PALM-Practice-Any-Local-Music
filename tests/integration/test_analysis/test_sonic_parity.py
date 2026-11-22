"""Gate 0 parity: real Piper vs real Sonic Annotator on all six fixtures.

N-marker policy: leading and interior Chordino N rows are preserved because
both hosts emit them (notably at the start of every chord fixture). The final
N that Sonic writes at end-of-file is an artifact absent from the Piper host;
SonicAnnotatorBackend drops it, and this test additionally normalizes any
terminal N before comparing. A lone N is preserved, so silence stays a
no-chord result.

The parity evidence records the actual preserved pack identities. On this
workspace Sonic discovers:
  vamp:embed-07-8888130:chordino:simplechord              (plugin version 5)
  vamp:qm-vamp-plugins:qm-keydetector:key                 (plugin version 6)
  vamp:qm-vamp-plugins:qm-barbeattracker:beats / :bars    (plugin version 3)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from basseparate import features
from basseparate.analysis_backend import PiperBackend
from basseparate.piper import PiperPaths
from basseparate.sonic_annotator import SonicAnnotatorBackend

ROOT = Path(__file__).resolve().parents[3]
AUDIO = ROOT / "tests" / "fixtures" / "audio"
FIXTURES = (
    "chords_c_am_f_g.wav",
    "click_120bpm.wav",
    "progression_120.wav",
    "silence.wav",
    "tone_440hz.wav",
    "tone_48k_stereo.wav",
)
BUNDLED_SONIC = (
    ROOT / "storage" / "bundled-tools" / "linux" / "sonic-annotator" / "squashfs-root" / "AppRun"
)
SONIC = (
    BUNDLED_SONIC
    if BUNDLED_SONIC.is_file()
    else ROOT / "storage" / "tools" / "sonic-annotator-1.7.0" / "squashfs-root" / "AppRun"
)
TOLERANCE_SECONDS = 0.025
BPM_TOLERANCE = 0.5

pytestmark = pytest.mark.integration


def _normalized_chords(result: features.AnalysisResult) -> tuple[str, ...]:
    labels = list(result.chord_labels)
    # Keep leading/interior N; the final N is Sonic's EOF artifact. A lone N
    # (silence) is not stripped.
    while len(labels) > 1 and labels[-1] == "N":
        labels.pop()
    return tuple(labels)


@pytest.fixture(scope="module")
def backends():
    if not SONIC.is_file():
        pytest.skip("preserved Sonic Annotator 1.7 is absent")
    paths = PiperPaths.for_project(ROOT)
    paths.validate()
    piper = PiperBackend(paths=paths)
    sonic = SonicAnnotatorBackend(
        binary=SONIC,
        plugin_paths=(
            ROOT / "storage" / "tools" / "plugins",
            ROOT / "storage" / "tools" / "vamp-plugins",
        ),
    )
    try:
        yield piper, sonic
    finally:
        sonic.close()


def test_plugin_identities_and_versions(backends) -> None:
    _piper, sonic = backends
    plugins = sonic.discover_plugins()
    assert plugins.chord.transform == "vamp:embed-07-8888130:chordino:simplechord"
    assert plugins.key.transform == "vamp:qm-vamp-plugins:qm-keydetector:key"
    assert plugins.beats.transform == "vamp:qm-vamp-plugins:qm-barbeattracker:beats"
    assert plugins.bars.transform == "vamp:qm-vamp-plugins:qm-barbeattracker:bars"
    versions = {
        "chord": sonic.plugin_version(plugins.chord),
        "key": sonic.plugin_version(plugins.key),
        "beat": sonic.plugin_version(plugins.beats),
    }
    assert versions == {"chord": "5", "key": "6", "beat": "3"}
    print(f"SONIC_PARITY plugins={plugins!r} versions={versions}")


@pytest.mark.parametrize("fixture", FIXTURES)
def test_piper_and_sonic_match(backends, fixture: str) -> None:
    piper, sonic = backends
    path = AUDIO / fixture
    signal, rate = features.load_audio_mono(path)
    piper_result = features.analyze_signal(
        signal,
        sample_rate=rate,
        source_sha256="e" * 64,
        backend=piper,
        lead_in_seconds=0.0,
    )
    sonic_result = features.analyze_signal(
        signal,
        sample_rate=rate,
        source_sha256="e" * 64,
        backend=sonic,
        lead_in_seconds=0.0,
    )

    piper_chords = _normalized_chords(piper_result)
    sonic_chords = _normalized_chords(sonic_result)
    raw_sonic = list(sonic_result.chord_labels)
    assert not (len(raw_sonic) > 1 and raw_sonic[-1] == "N"), (
        f"{fixture}: Sonic terminal N was not normalized"
    )
    assert piper_chords == sonic_chords, f"{fixture}: chord sequence"
    assert piper_result.key.label == sonic_result.key.label, f"{fixture}: key"
    assert piper_result.key.tonic == sonic_result.key.tonic, f"{fixture}: tonic"
    assert piper_result.key.mode == sonic_result.key.mode, f"{fixture}: mode"

    if piper_result.bpm is None or sonic_result.bpm is None:
        assert piper_result.bpm is None and sonic_result.bpm is None, f"{fixture}: BPM"
    else:
        assert abs(piper_result.bpm - sonic_result.bpm) <= BPM_TOLERANCE, (
            f"{fixture}: BPM {piper_result.bpm} vs {sonic_result.bpm}"
        )

    piper_beats = [beat.time_seconds for beat in piper_result.grid.beats]
    sonic_beats = [beat.time_seconds for beat in sonic_result.grid.beats]
    piper_bars = [bar.time_seconds for bar in piper_result.grid.bars]
    sonic_bars = [bar.time_seconds for bar in sonic_result.grid.bars]
    assert len(piper_beats) == len(sonic_beats), f"{fixture}: beat count"
    assert len(piper_bars) == len(sonic_bars), f"{fixture}: bar count"
    for index, (left, right) in enumerate(zip(piper_beats, sonic_beats, strict=True)):
        assert abs(left - right) <= TOLERANCE_SECONDS, f"{fixture}: beat {index} {left} vs {right}"
    for index, (left, right) in enumerate(zip(piper_bars, sonic_bars, strict=True)):
        assert abs(left - right) <= TOLERANCE_SECONDS, f"{fixture}: bar {index} {left} vs {right}"
    print(
        f"SONIC_PARITY {path} key={piper_result.key.label!r} "
        f"chords={piper_chords!r} bpm={piper_result.bpm} "
        f"beats={len(piper_beats)} bars={len(piper_bars)}"
    )
