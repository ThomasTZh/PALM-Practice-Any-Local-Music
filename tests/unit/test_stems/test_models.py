"""Model-aware cache identity, request defaults and worker dispatch (t50)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from basseparate.config import DataPaths
from basseparate.model_registry import ModelEntry, ModelFile
from basseparate.stems import (
    DEFAULT_MODEL_ID,
    STEM_LABELS,
    SeparateRequest,
    StemFile,
    StemSet,
    model_cache_hashes,
    read_stem_cache,
    stem_cache_key,
    worker_command,
)


def fake_model(
    model_id: str = "fake-six",
    *,
    engine: str = "msst",
    labels: tuple[str, ...] = ("bass", "drums", "other", "vocals", "guitar", "piano"),
    checkpoint_sha: str = "a" * 64,
) -> ModelEntry:
    return ModelEntry(
        id=model_id,
        name=model_id,
        engine=engine,
        engine_command=f"python worker.py --model-id {model_id}",
        labels=labels,
        sample_rate=48_000,
        size_bytes=10,
        source_url="https://example.invalid/model",
        license="test",
        bundled=False,
        install_dir=f"models/{model_id}",
        files=(
            ModelFile(
                role="checkpoint",
                name="weights.ckpt",
                url="https://example.invalid/weights.ckpt",
                size_bytes=8,
                sha256=checkpoint_sha,
            ),
            ModelFile(
                role="config",
                name="config.yaml",
                url="https://example.invalid/config.yaml",
                size_bytes=2,
                sha256="b" * 64,
            ),
        ),
    )


def test_separate_request_requires_an_explicit_model() -> None:
    with pytest.raises(ValidationError):
        SeparateRequest(project_id="p1")
    request = SeparateRequest(project_id="p1", model_id="scnet-xl-ihf")
    assert request.model_id == "scnet-xl-ihf"
    assert request.device == "auto"


def test_cache_key_v2_includes_model_and_weight_hashes() -> None:
    base = {"sample_rate": 48_000, "channels": 2, "model_hashes": {"checkpoint": "a" * 64}}
    four = stem_cache_key("c" * 64, model_id="four", labels=STEM_LABELS, **base)
    same = stem_cache_key("c" * 64, model_id="four", labels=STEM_LABELS, **base)
    other_model = stem_cache_key("c" * 64, model_id="six", labels=STEM_LABELS, **base)
    other_weights = stem_cache_key(
        "c" * 64,
        model_id="four",
        labels=STEM_LABELS,
        sample_rate=48_000,
        channels=2,
        model_hashes={"checkpoint": "b" * 64},
    )
    assert four == same
    assert len({four, other_model, other_weights}) == 3


def test_cache_key_includes_declared_file_hashes() -> None:
    entry = fake_model()
    hashes = model_cache_hashes(entry)
    assert hashes == {"checkpoint:weights.ckpt": "a" * 64, "config:config.yaml": "b" * 64}
    entry_other = fake_model("fake-other", checkpoint_sha="c" * 64)
    assert model_cache_hashes(entry_other) != hashes


def test_worker_command_dispatches_msst_args() -> None:
    model = fake_model()
    command = worker_command(
        model,
        pcm_path=Path("/tmp/input.f32"),
        stage=Path("/tmp/out"),
        sample_rate=48_000,
        channels=2,
        device="cpu",
        cancel_path=Path("/tmp/cancel.flag"),
        analysis_python=Path("/usr/bin/python3"),
        worker_script=Path("/tmp/separate_msst.py"),
    )
    assert command[0] == "/usr/bin/python3"
    assert command[1] == "/tmp/separate_msst.py"
    assert "--model-id" in command and command[command.index("--model-id") + 1] == "fake-six"
    assert "--bundle-dir" not in command
    assert "--models-root" in command and "--registry" in command


def test_worker_command_dispatches_demucs_args() -> None:
    model = fake_model("fake-four", engine="demucs", labels=STEM_LABELS)
    command = worker_command(
        model,
        pcm_path=Path("/tmp/input.f32"),
        stage=Path("/tmp/out"),
        sample_rate=48_000,
        channels=2,
        device="cpu",
        cancel_path=Path("/tmp/cancel.flag"),
        analysis_python=Path("/usr/bin/python3"),
        worker_script=Path("/tmp/separate_track.py"),
        bundle_dir=Path("/tmp/bundle"),
    )
    assert "--bundle-dir" in command and command[command.index("--bundle-dir") + 1] == "/tmp/bundle"
    assert "--manifest" in command
    assert "--window-seconds" in command and "--shifts" in command
    assert "--model-id" not in command


def write_cache(paths: DataPaths, key: str, labels: tuple[str, ...], *, version: int) -> Path:
    directory = paths.root / "stems" / key
    directory.mkdir(parents=True)
    rows = []
    for label in labels:
        payload = (label.encode() * 16)[:16]
        (directory / f"{label}.f32").write_bytes(payload)
        rows.append({"label": label, "file": f"{label}.f32", "frames": 2, "channels": 2})
    meta = {
        "version": version,
        "key": key,
        "sample_rate": 48_000,
        "channels": 2,
        "frames": 2,
        "stems": rows,
        "device": "cpu",
        "elapsed_seconds": 0.1,
    }
    if version == 2:
        meta["model_id"] = "fake-six"
        meta["labels"] = list(labels)
    (directory / "stems.json").write_text(json.dumps(meta))
    return directory


def test_v1_demucs_cache_entries_remain_readable(tmp_path: Path) -> None:
    paths = DataPaths.from_root(tmp_path / "data").ensure()
    key = "1" * 64
    write_cache(paths, key, STEM_LABELS, version=1)
    stem_set = read_stem_cache(paths, key)
    assert stem_set is not None
    assert stem_set.model_id == DEFAULT_MODEL_ID
    assert stem_set.labels == STEM_LABELS


def test_v2_cache_entries_use_their_own_labels(tmp_path: Path) -> None:
    paths = DataPaths.from_root(tmp_path / "data").ensure()
    key = "2" * 64
    labels = ("bass", "drums", "guitar", "piano")
    write_cache(paths, key, labels, version=2)
    stem_set = read_stem_cache(paths, key)
    assert stem_set is not None
    assert stem_set.model_id == "fake-six"
    assert stem_set.labels == labels


def test_v2_cache_meta_label_mismatch_is_rejected(tmp_path: Path) -> None:
    paths = DataPaths.from_root(tmp_path / "data").ensure()
    key = "3" * 64
    directory = write_cache(paths, key, STEM_LABELS, version=2)
    meta = json.loads((directory / "stems.json").read_text())
    meta["labels"] = ["bass", "drums"]
    (directory / "stems.json").write_text(json.dumps(meta))
    assert read_stem_cache(paths, key) is None


def test_stem_set_payload_exposes_model_labels_and_cache_paths(tmp_path: Path) -> None:
    directory = tmp_path / "stems" / "key"
    directory.mkdir(parents=True)
    stems = tuple(
        StemFile(label=label, path=directory / f"{label}.f32", frames=4, channels=2)
        for label in ("bass", "drums", "guitar", "piano")
    )
    stem_set = StemSet(
        key="key",
        directory=directory,
        sample_rate=48_000,
        channels=2,
        frames=4,
        stems=stems,
        device="cpu",
        elapsed_seconds=0.1,
        cached=True,
        metadata={},
        model_id="fake-six",
    )
    payload = stem_set.payload("p1")
    assert payload["model_id"] == payload["model"] == "fake-six"
    assert payload["labels"] == ["bass", "drums", "guitar", "piano"]
    assert [entry["label"] for entry in payload["stems"]] == list(stem_set.labels)
    assert payload["stems"][0]["path"] == "stems/key/bass.f32"
    assert payload["stems"][0]["url"] == "/api/projects/p1/stems/bass/pcm"
