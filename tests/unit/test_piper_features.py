"""Pure-function and cache tests for the analysis feature layer."""

from __future__ import annotations

import json
from pathlib import Path

from basseparate.features import (
    AnalysisMeta,
    AnalysisResult,
    Bar,
    Beat,
    BeatGrid,
    ChordRegion,
    KeyResult,
    PluginRun,
    analysis_cache_key,
    bpm_from_beat_times,
    parse_chords,
    parse_grid,
    parse_key,
    plugin_specs,
    read_cache,
    write_cache,
)


def test_bpm_from_median_interval() -> None:
    assert bpm_from_beat_times([0.0, 0.5, 1.0, 1.5]) == 120.0


def test_bpm_uses_the_median_not_the_mean() -> None:
    # One missed beat (1.0 s gap) must not move the median.
    assert bpm_from_beat_times([0.0, 0.5, 1.5, 2.0]) == 120.0


def test_bpm_is_order_independent_and_ignores_duplicates() -> None:
    assert bpm_from_beat_times([1.5, 0.0, 1.0, 0.5, 0.5]) == 120.0


def test_bpm_needs_two_beats() -> None:
    assert bpm_from_beat_times([]) is None
    assert bpm_from_beat_times([1.0]) is None


def test_bpm_ignores_non_finite_values() -> None:
    assert bpm_from_beat_times([0.0, float("nan"), 0.5, float("inf"), 1.0]) == 120.0


def test_parse_grid_shifts_lead_in_and_trims_trailing_prediction() -> None:
    features = {
        "beats": [
            {"timestamp": {"s": 1, "n": 950_000_000}, "label": "4"},  # -0.05 -> 0
            {"timestamp": {"s": 2, "n": 0}, "label": "1"},
            {"timestamp": {"s": 2, "n": 500_000_000}, "label": "2"},
            {"timestamp": {"s": 5, "n": 999_000_000}, "label": "3"},  # past the end
        ],
        "bars": [
            {"timestamp": {"s": 1, "n": 950_000_000}, "label": "1"},
            {"timestamp": {"s": 3, "n": 900_000_000}, "label": "2"},
        ],
    }
    grid = parse_grid(features, bpb=4, duration_seconds=4.0, lead_in_seconds=2.0)
    assert [beat.time_seconds for beat in grid.beats] == [0.0, 0.5]
    assert [bar.time_seconds for bar in grid.bars] == [0.0, 1.9]
    assert grid.first_beat == 0.0
    assert grid.bar_count == 2
    assert grid.bpm == 120.0
    assert [beat.label for beat in grid.beats] == ["4", "2"]


def test_parse_grid_without_beats_has_no_bpm() -> None:
    grid = parse_grid({}, bpb=4, duration_seconds=10.0)
    assert grid.bpm is None
    assert grid.first_beat is None
    assert grid.bar_count == 0


def test_parse_chords_preserves_raw_labels_and_regions() -> None:
    features = {
        "simplechord": [
            {"timestamp": {"s": 0}, "label": "N"},
            {"timestamp": {"s": 1}, "label": "C:maj"},
            {"timestamp": {"s": 2}, "label": "A:min7"},
            {"timestamp": {"s": 3}, "label": "A:min7"},
            {"timestamp": {"s": 4}, "label": "G"},
        ]
    }
    chords = parse_chords(features, duration_seconds=5.0)
    assert [(chord.label, chord.start_seconds, chord.end_seconds) for chord in chords] == [
        ("N", 0.0, 1.0),
        ("C:maj", 1.0, 2.0),
        ("A:min7", 2.0, 4.0),
        ("G", 4.0, 5.0),
    ]
    assert chords[2].label == "A:min7"  # no enharmonic or quality rewriting


def test_parse_key_keeps_the_raw_label() -> None:
    features = {
        "key": [{"timestamp": {"s": 0}, "label": "C major", "featureValues": [1]}],
        "tonic": [{"timestamp": {"s": 0}, "featureValues": [1]}],
        "mode": [{"timestamp": {"s": 0}, "featureValues": [0]}],
    }
    key = parse_key(features)
    assert key.label == "C major"
    assert key.tonic == 1
    assert key.mode == 0


def _sample_result(cache_key: str = "a" * 64) -> AnalysisResult:
    return AnalysisResult(
        grid=BeatGrid(
            bpm=120.0,
            bpb=4,
            beats=(Beat(0.0, "1"), Beat(0.5, "2")),
            bars=(Bar(0.0, "1"),),
        ),
        key=KeyResult(label="C major", tonic=1, mode=0),
        chords=(ChordRegion(0.0, 2.0, "C:maj"), ChordRegion(2.0, 4.0, "A:min7")),
        meta=AnalysisMeta(
            cache_key=cache_key,
            source_sha256="f" * 64,
            source_name="fixture.wav",
            sample_rate=44_100,
            duration_seconds=4.0,
            bpb=4,
            lead_in_seconds=0.0,
            elapsed_seconds=1.25,
            plugins=(
                PluginRun(
                    role="Chordino",
                    display_name="Chordino",
                    key="embed-07-8888130:chordino",
                    version="1",
                    parameters={},
                    block_size=16_384,
                    step_size=2048,
                ),
            ),
        ),
        output_dir=None,
        cached=False,
    )


def test_cache_round_trip_publishes_four_documents(tmp_path: Path) -> None:
    result = _sample_result()
    published = write_cache(tmp_path, result)
    assert published == tmp_path / ("a" * 64)
    assert {path.name for path in published.iterdir()} == {
        "beats.json",
        "key.json",
        "chords.json",
        "meta.json",
    }
    cached = read_cache(tmp_path, "a" * 64)
    assert cached is not None
    assert cached.cached is True
    assert cached.bpm == 120.0
    assert cached.key_label == "C major"
    assert cached.chord_labels == ("C:maj", "A:min7")
    assert cached.grid.first_beat == 0.0
    assert cached.meta.source_name == "fixture.wav"


def test_cache_is_all_or_nothing(tmp_path: Path) -> None:
    result = _sample_result()
    write_cache(tmp_path, result)
    entry = tmp_path / ("a" * 64)
    (entry / "key.json").unlink()
    assert read_cache(tmp_path, "a" * 64) is None
    assert not [path for path in tmp_path.iterdir() if path.name.startswith(".")]


def test_corrupt_cache_is_a_miss(tmp_path: Path) -> None:
    result = _sample_result()
    entry = write_cache(tmp_path, result)
    (entry / "beats.json").write_text("{not json", encoding="utf-8")
    assert read_cache(tmp_path, "a" * 64) is None


def test_write_cache_repairs_a_corrupt_entry(tmp_path: Path) -> None:
    result = _sample_result()
    entry = write_cache(tmp_path, result)
    (entry / "key.json").unlink()
    assert read_cache(tmp_path, result.meta.cache_key) is None
    repaired = write_cache(tmp_path, result)
    assert repaired == entry
    assert read_cache(tmp_path, result.meta.cache_key) is not None


def test_cache_key_is_content_addressed(tmp_path: Path) -> None:
    specs = plugin_specs(4)
    first = analysis_cache_key(
        "a" * 64, sample_rate=44_100, bpb=4, lead_in_seconds=0.0, specs=specs
    )
    again = analysis_cache_key(
        "a" * 64, sample_rate=44_100, bpb=4, lead_in_seconds=0.0, specs=specs
    )
    assert first == again
    assert len(first) == 64
    assert first != analysis_cache_key(
        "b" * 64, sample_rate=44_100, bpb=4, lead_in_seconds=0.0, specs=specs
    )
    assert first != analysis_cache_key(
        "a" * 64, sample_rate=48_000, bpb=4, lead_in_seconds=0.0, specs=specs
    )
    assert first != analysis_cache_key(
        "a" * 64, sample_rate=44_100, bpb=3, lead_in_seconds=0.0, specs=plugin_specs(3)
    )
    assert first != analysis_cache_key(
        "a" * 64, sample_rate=44_100, bpb=4, lead_in_seconds=2.0, specs=specs
    )


def test_cache_key_includes_plugin_parameters() -> None:
    base = (("Chordino", {}),)
    changed = (("Chordino", {"useNNLS": 0.0}),)
    assert analysis_cache_key(
        "a" * 64, sample_rate=44_100, bpb=4, lead_in_seconds=0.0, specs=base
    ) != analysis_cache_key("a" * 64, sample_rate=44_100, bpb=4, lead_in_seconds=0.0, specs=changed)


def test_cache_meta_lists_resolved_plugin_keys(tmp_path: Path) -> None:
    result = _sample_result()
    entry = write_cache(tmp_path, result)
    meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
    assert meta["labels_raw"] is True
    assert meta["plugins"][0]["display_name"] == "Chordino"
    assert meta["plugins"][0]["key"] == "embed-07-8888130:chordino"


def test_write_cache_is_idempotent(tmp_path: Path) -> None:
    result = _sample_result()
    first = write_cache(tmp_path, result)
    second = write_cache(tmp_path, result)
    assert first == second
    assert read_cache(tmp_path, result.meta.cache_key) is not None
