"""Optional real native Vamp host test.

Set BASSEPARATE_VAMP_NATIVE_HOST_PATH and BASSEPARATE_VAMP_PLUGIN_PATH to
run. The normal unit suite uses fixtures and never downloads tools.
"""

from __future__ import annotations

import math
import os
import struct
from pathlib import Path

import pytest

from basseparate.vamp.native import analyze_pcm_native


@pytest.mark.skipif(
    not os.environ.get("BASSEPARATE_VAMP_NATIVE_HOST_PATH")
    or not os.environ.get("BASSEPARATE_VAMP_PLUGIN_PATH"),
    reason="native Vamp host is not configured",
)
def test_native_host_finds_beats_on_click_track(tmp_path: Path) -> None:
    rate = 48_000
    duration = 8
    frames = rate * duration
    pcm = tmp_path / "clicks.f32"
    with pcm.open("wb") as handle:
        for frame in range(frames):
            t = frame / rate
            value = 0.0
            beat = round(t / 0.5)
            if abs(t - beat * 0.5) < 0.02:
                value = 0.8 if beat % 4 == 0 else 0.4
            handle.write(struct.pack("<f", max(-1.0, min(1.0, value))))
    analysis = analyze_pcm_native(
        pcm,
        sample_rate=rate,
        channels=1,
        host_path=Path(os.environ["BASSEPARATE_VAMP_NATIVE_HOST_PATH"]),
        plugin_path=Path(os.environ["BASSEPARATE_VAMP_PLUGIN_PATH"]),
        plugin_key="qm-vamp-plugins:qm-barbeattracker",
        bpb=4,
        timeout_seconds=60,
    )
    assert analysis.bpb == 4
    assert len(analysis.beats) >= 8
    assert len(analysis.bars) >= 2
    assert math.isfinite(analysis.beats[0].time_seconds)
