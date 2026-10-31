"""Pure parameter, result and document mapping for the analysis job."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from basseparate.analysis_jobs import (
    AnalysisJobError,
    AnalysisParams,
    analysis_cache_dir,
    analysis_document,
    analysis_result_payload,
    read_project_signal,
    validate_analysis_params,
)
from basseparate.api.models import InvalidRequest
from basseparate.config import DataPaths
from basseparate.features import (
    AnalysisMeta,
    AnalysisResult,
    Bar,
    Beat,
    BeatGrid,
    ChordRegion,
    KeyResult,
    PluginRun,
)
from basseparate.projects import (
    Project,
    ProjectNotFound,
    ProjectStore,
    build_audio_info,
    build_project,
)


def sample_result(*, cached: bool = False) -> AnalysisResult:
    return AnalysisResult(
        grid=BeatGrid(
            bpm=120.0,
            bpb=4,
            beats=(Beat(0.0, "1"), Beat(0.5, "2"), Beat(1.0, "3")),
            bars=(Bar(0.0, "1"),),
        ),
        key=KeyResult(label="C major", tonic=1, mode=0),
        chords=(
            ChordRegion(0.0, 2.0, "C:maj"),
            ChordRegion(2.0, 3.0, "A:min7"),
        ),
        meta=AnalysisMeta(
            cache_key="cache-abc",
            source_sha256="f" * 64,
            source_name="fixture.wav",
            sample_rate=48_000,
            duration_seconds=4.0,
            bpb=4,
            lead_in_seconds=2.0,
            elapsed_seconds=1.25,
            plugins=(
                PluginRun(
                    role="Chordino",
                    display_name="Chordino",
                    key="embed-07-8888130:chordino",
                    version="5",
                    parameters={"useNNLS": 1.0},
                    block_size=16384,
                    step_size=2048,
                ),
            ),
        ),
        output_dir=None,
        cached=cached,
    )


def test_params_validate_project_and_bpb() -> None:
    parsed = AnalysisParams.model_validate({"project_id": "abc-123", "bpb": 6})
    assert parsed.project_id == "abc-123"
    assert parsed.bpb == 6
    assert AnalysisParams.model_validate({"project_id": "abc"}).bpb == 4
    for bad in (
        {"project_id": "abc", "bpb": 1},
        {"project_id": "abc", "bpb": 17},
        {"project_id": "bad/id", "bpb": 4},
        {"project_id": "abc", "bpb": 4, "extra": True},
    ):
        with pytest.raises(ValidationError):
            AnalysisParams.model_validate(bad)


def test_result_payload_is_exactly_the_ui_contract() -> None:
    payload = analysis_result_payload(sample_result(cached=True))
    assert set(payload) == {"cached", "bpb", "bpm", "key", "chords", "beats", "bars"}
    assert payload == {
        "cached": True,
        "bpb": 4,
        "bpm": 120.0,
        "key": "C major",
        "chords": [
            {"start_seconds": 0.0, "end_seconds": 2.0, "label": "C:maj"},
            {"start_seconds": 2.0, "end_seconds": 3.0, "label": "A:min7"},
        ],
        "beats": [0.0, 0.5, 1.0],
        "bars": [0.0],
    }


def test_document_contains_grid_key_chords_and_meta() -> None:
    document = {
        "state_version": 1,
        "sections": [{"id": "s1", "start_bar": 0, "end_bar": 2}],
        "mixer": {"drums": {"gain": 0.5}},
        "unknown": {"keep": True},
    }
    merged = analysis_document(document, sample_result(cached=True))
    assert merged["grid"]["bpb"] == 4
    assert merged["grid"]["beats"] == [0.0, 0.5, 1.0]
    assert merged["grid"]["bars"] == [0.0]
    assert merged["grid"]["bpm"] == 120.0
    assert merged["grid"]["meter"] == {"numerator": 4, "denominator": 4}
    assert merged["grid"]["offsetSeconds"] == 0.0
    assert merged["key"] == "C major"
    assert merged["chords"][0] == {
        "start_seconds": 0.0,
        "end_seconds": 2.0,
        "label": "C:maj",
    }
    analysis = merged["analysis"]
    assert analysis["cache_key"] == "cache-abc"
    assert analysis["source_sha256"] == "f" * 64
    assert analysis["sample_rate"] == 48_000
    assert analysis["bpm"] == 120.0
    assert analysis["key"] == "C major"
    assert analysis["bpb"] == 4
    assert analysis["cached"] is True
    assert analysis["lead_in_seconds"] == 2.0
    assert analysis["plugins"][0]["display_name"] == "Chordino"
    # Existing practice state and unknown keys survive the merge.
    assert merged["state_version"] == 1
    assert merged["sections"] == document["sections"]
    assert merged["mixer"] == document["mixer"]
    assert merged["unknown"] == {"keep": True}
    assert "updated_at" in analysis


def _project(
    tmp_path: Path, *, frames: int, channels: int, samples: list[float]
) -> tuple[Project, DataPaths]:
    settings_root = tmp_path / "data"
    paths = DataPaths.from_root(settings_root).ensure()
    asset_id = "asset-test"
    directory = paths.asset_dir(asset_id)
    directory.mkdir(parents=True, exist_ok=True)
    np.asarray(samples, dtype="<f4").tofile(directory / "pcm.f32")
    audio = build_audio_info(
        asset_id=asset_id,
        source_name="test.wav",
        source_format="wav",
        sample_rate=48_000,
        channels=channels,
        frames=frames,
        content_sha256="a" * 64,
        peak_counts={},
    )
    return build_project(audio, name="test"), paths


def test_read_project_signal_downmixes_without_redecoding(tmp_path: Path) -> None:
    project, paths = _project(
        tmp_path,
        frames=2,
        channels=2,
        samples=[1.0, 3.0, 2.0, 4.0],
    )
    signal = read_project_signal(project, paths)
    assert signal.dtype == np.float32
    np.testing.assert_allclose(signal, [2.0, 3.0])


def test_read_project_signal_rejects_a_truncated_stream(tmp_path: Path) -> None:
    project, paths = _project(
        tmp_path,
        frames=2,
        channels=2,
        samples=[1.0, 3.0],
    )
    with pytest.raises(AnalysisJobError, match="bytes"):
        read_project_signal(project, paths)


def test_analysis_cache_dir_is_under_the_data_root(tmp_path: Path) -> None:
    paths = DataPaths.from_root(tmp_path / "data").ensure()
    assert analysis_cache_dir(paths) == paths.root / "analysis"


def test_validate_analysis_params_uses_the_project_store(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects")
    project, paths = _project(tmp_path, frames=1, channels=1, samples=[0.0])
    store.create(project)
    validate_analysis_params("analysis", {"project_id": project.id, "bpb": 4}, store)
    with pytest.raises(InvalidRequest, match="invalid analysis"):
        validate_analysis_params("analysis", {"project_id": project.id, "bpb": 1}, store)
    with pytest.raises(ProjectNotFound):
        validate_analysis_params("analysis", {"project_id": "missing", "bpb": 4}, store)
    # Other kinds are untouched.
    validate_analysis_params("import", {"path": "/tmp/x"}, store)
