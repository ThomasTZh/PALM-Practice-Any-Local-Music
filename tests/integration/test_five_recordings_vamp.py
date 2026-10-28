"""Five-recording Vamp grid acceptance.

Opt in with the local native host and the user-supplied recordings:

    BASSEPARATE_VAMP_NATIVE_HOST_PATH=... BASSEPARATE_VAMP_PLUGIN_PATH=... \
      pytest tests/integration/test_five_recordings_vamp.py -q

Each source is cut to a 20 s excerpt so the test remains a quick runtime
and quality sanity check rather than a full-song benchmark.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from basseparate.vamp.native import analyze_pcm_native

SOURCE_NAMES = (
    "46.GIBBS - Simplicity.wav",
    "Carousel Theory Full Mix V1 (With Limiter).wav",
    "Summer By The Sea Instrumental Demo.wav",
    "Sweet Demo.wav",
    "Videoslave Instrumental Demo.wav",
)
ROOT = Path(__file__).resolve().parents[2]
HOST = os.environ.get("BASSEPARATE_VAMP_NATIVE_HOST_PATH")
PLUGINS = os.environ.get("BASSEPARATE_VAMP_PLUGIN_PATH")

pytestmark = pytest.mark.skipif(
    not HOST or not PLUGINS or not shutil.which("ffmpeg"),
    reason="native Vamp host, plugin path, or ffmpeg is not configured",
)


@pytest.mark.parametrize("name", SOURCE_NAMES)
def test_supplied_recording_produces_grid(tmp_path: Path, name: str) -> None:
    source = ROOT / "audio2test" / name
    if not source.is_file():
        pytest.skip(f"recording not present: {name}")
    excerpt = tmp_path / "excerpt.f32"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            "30",
            "-t",
            "20",
            "-i",
            str(source),
            "-ac",
            "1",
            "-ar",
            "44100",
            "-f",
            "f32le",
            str(excerpt),
        ],
        check=True,
    )
    analysis = analyze_pcm_native(
        excerpt,
        sample_rate=44_100,
        channels=1,
        host_path=Path(HOST or ""),
        plugin_path=Path(PLUGINS or ""),
        plugin_key="qm-vamp-plugins:qm-barbeattracker",
        bpb=4,
        timeout_seconds=60,
    )
    assert analysis.bpb == 4
    assert len(analysis.beats) >= 8, name
    assert len(analysis.bars) >= 2, name
