"""Six-label model path with a fake engine (no real weights or torch)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from basseparate import stems
from basseparate.app import create_app
from basseparate.config import Settings
from basseparate.model_registry import ModelEntry, ModelFile
from basseparate.projects import ProjectStore, build_audio_info, build_project
from basseparate.stems import (
    StemError,
    publish_project_stems,
    read_stem_cache,
    separate_project,
)

SIX_LABELS = ("bass", "drums", "other", "vocals", "guitar", "piano")
FOUR_LABELS = ("drums", "bass", "other", "vocals")


def fake_model(
    model_id: str,
    *,
    labels: tuple[str, ...],
    engine: str = "msst",
    checkpoint_sha: str = "a" * 64,
) -> ModelEntry:
    return ModelEntry(
        id=model_id,
        name=model_id,
        engine=engine,
        engine_command=f"python worker.py --model-id {model_id}",
        labels=labels,
        sample_rate=48_000,
        size_bytes=12,
        source_url="https://example.invalid/model",
        license="test",
        bundled=False,
        install_dir=f"models/{model_id}",
        files=(
            ModelFile(
                role="checkpoint",
                name="weights.ckpt",
                url="https://example.invalid/weights.ckpt",
                size_bytes=10,
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


FAKE_WORKER = r"""
import argparse
import json
import os
from array import array
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--sample-rate", type=int, required=True)
parser.add_argument("--channels", type=int, required=True)
parser.add_argument("--model-id", default=None)
parser.add_argument("--device", default="auto")
args, _unknown = parser.parse_known_args()

labels = json.loads(os.environ["FAKE_STEM_LABELS"])
amplitudes = json.loads(os.environ["FAKE_STEM_AMPS"])
model_id = args.model_id or os.environ["FAKE_STEM_MODEL"]
frames = args.input.stat().st_size // (args.channels * 4)
args.out.mkdir(parents=True, exist_ok=True)
for index, label in enumerate(labels):
    amplitude = amplitudes[index]
    payload = array("f", [amplitude]) * (frames * args.channels)
    if sys.byteorder != "little":
        payload.byteswap()
    (args.out / f"{label}.f32").write_bytes(payload.tobytes())
print(json.dumps({"type": "progress", "stage": "separating", "fraction": 0.5}), flush=True)
meta = {
    "status": "complete",
    "labels": labels,
    "frames": frames,
    "sample_rate": args.sample_rate,
    "channels": args.channels,
    "model_id": model_id,
    "device": "cpu",
    "elapsed_seconds": 0.01,
}
(args.out / "meta.json").write_text(json.dumps(meta))
"""


def make_workspace(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data", web_dir=tmp_path / "dist")
    paths = settings.data_paths.ensure()
    store = ProjectStore(paths.projects)
    frames, channels, rate = 4_800, 2, 48_000
    asset_id = "model-asset"
    asset_dir = paths.asset_dir(asset_id)
    asset_dir.mkdir(parents=True)
    (asset_dir / "source.wav").write_bytes(b"RIFF")
    (asset_dir / "pcm.f32").write_bytes(np.zeros(frames * channels, dtype="<f4").tobytes())
    audio = build_audio_info(
        asset_id=asset_id,
        source_name="model.wav",
        source_format="wav",
        sample_rate=rate,
        channels=channels,
        frames=frames,
        content_sha256="d" * 64,
        peak_counts={},
    )
    project = store.create(build_project(audio, name="Model fake"))
    worker = tmp_path / "fake_worker.py"
    worker.write_text("import sys\n" + FAKE_WORKER)
    return settings, paths, store, project, worker, frames


def run_fake(
    project,
    paths,
    worker,
    model,
    labels,
    amplitudes,
    monkeypatch,
):
    monkeypatch.setenv("FAKE_STEM_LABELS", json.dumps(list(labels)))
    monkeypatch.setenv("FAKE_STEM_AMPS", json.dumps(list(amplitudes)))
    monkeypatch.setenv("FAKE_STEM_MODEL", model.id)
    return separate_project(
        project,
        paths=paths,
        model=model,
        analysis_python=Path(sys.executable),
        worker_script=worker,
        device="cpu",
    )


def test_six_label_fake_engine_end_to_end(tmp_path: Path, monkeypatch) -> None:
    settings, paths, store, project, worker, frames = make_workspace(tmp_path)
    six = fake_model("bs-roformer-sw", labels=SIX_LABELS)
    four = fake_model("fake-four", labels=FOUR_LABELS, checkpoint_sha="c" * 64)
    amplitudes = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)

    stem_set = run_fake(project, paths, worker, six, SIX_LABELS, amplitudes, monkeypatch)
    assert stem_set.model_id == "bs-roformer-sw"
    assert stem_set.labels == SIX_LABELS
    assert stem_set.cached is False
    assert stem_set.key != ""
    metadata = json.loads((stem_set.directory / "stems.json").read_text())
    assert metadata["version"] == 2
    assert metadata["model_id"] == "bs-roformer-sw"
    assert metadata["labels"] == list(SIX_LABELS)
    assert metadata["model_hashes"]["checkpoint:weights.ckpt"] == "a" * 64
    for stem in stem_set.stems:
        assert stem.path.stat().st_size == frames * 2 * 4

    # A second run of the same model is a cache hit and starts no child.
    with monkeypatch.context() as cache_patch:
        cache_patch.setattr(
            stems.subprocess,
            "Popen",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("cache hit must not spawn")),
        )
        again = separate_project(project, paths=paths, model=six)
    assert again.cached is True
    assert again.key == stem_set.key

    # The other model has a different identity and a separate cache entry.
    four_set = run_fake(
        project, paths, worker, four, FOUR_LABELS, (0.1, 0.2, 0.3, 0.4), monkeypatch
    )
    assert four_set.key != stem_set.key
    assert four_set.labels == FOUR_LABELS
    assert read_stem_cache(paths, stem_set.key).model_id == "bs-roformer-sw"

    # Publish and exercise the variable-label routes and six-stem export.
    publish_project_stems(store, project.id, stem_set)
    stored = store.get(project.id)
    assert stored.document["stemModel"] == "bs-roformer-sw"
    assert [entry["label"] for entry in stored.document["stems"]] == list(SIX_LABELS)

    app = create_app(settings)
    with TestClient(app) as client:
        listing = client.get(f"/api/projects/{project.id}/stems")
        assert listing.status_code == 200
        assert listing.json()["model"] == "bs-roformer-sw"
        assert listing.json()["model_id"] == "bs-roformer-sw"
        assert [entry["label"] for entry in listing.json()["stems"]] == list(SIX_LABELS)

        guitar = client.get(f"/api/projects/{project.id}/stems/guitar/pcm")
        assert guitar.status_code == 200
        assert guitar.headers["x-stem-label"] == "guitar"
        assert len(guitar.content) == frames * 2 * 4
        peaks = client.get(
            f"/api/projects/{project.id}/stems/guitar/peaks", params={"buckets": 1024}
        )
        assert peaks.status_code == 200
        assert peaks.headers["x-stem-label"] == "guitar"
        assert client.get(f"/api/projects/{project.id}/stems/nope/pcm").status_code == 404
        assert client.get(f"/api/projects/{project.id}/stems/nope/peaks").status_code == 404

        mixer = {"stems": {label: {"gain": 0.0} for label in SIX_LABELS}}
        mixer["stems"]["bass"] = {"gain": 1.0}
        mixer["stems"]["guitar"] = {"gain": 0.5}
        mixer["stems"]["drums"] = {"gain": 1.0, "muted": True}
        export = client.post(f"/api/projects/{project.id}/exports", json={"mixer": mixer})
        assert export.status_code == 201, export.text
        body = export.json()
        assert body["frames"] == frames
        assert body["layers"] == ["bass", "guitar"]
        download = client.get(body["download_url"])
        assert download.status_code == 200
        with __import__("wave").open(__import__("io").BytesIO(download.content)) as wav:
            assert wav.getnframes() == frames
            values = np.frombuffer(wav.readframes(frames), dtype="<i2")
        # bass 0.1 * 1.0 + guitar 0.5 * 0.5 = 0.35; drums are muted and the
        # other three stems have gain 0.
        assert np.max(np.abs(values.astype(np.float64) / 32767.0 - 0.35)) < 3 / 32767.0

    # Model listing is local-only and reports the registry fields + metrics.
    with TestClient(app) as client:
        models = client.get("/api/separation/models").json()
        assert models["default"] == "htdemucs_ft"
        by_id = {model["id"]: model for model in models["models"]}
        assert set(by_id) == {"htdemucs_ft", "scnet-xl-ihf", "bs-roformer-sw"}
        assert by_id["bs-roformer-sw"]["labels"] == list(SIX_LABELS)
        assert by_id["bs-roformer-sw"]["metrics"]["peak_rss_mib"] > 0
        assert by_id["bs-roformer-sw"]["install_command"].startswith("make models-install")
        assert by_id["htdemucs_ft"]["default"] is True


def test_mismatched_labels_are_rejected(tmp_path: Path, monkeypatch) -> None:
    _settings, paths, _store, project, worker, _frames = make_workspace(tmp_path)
    six = fake_model("bs-roformer-sw", labels=SIX_LABELS)
    with pytest.raises(StemError, match="expected"):
        run_fake(project, paths, worker, six, ("bass", "drums"), (0.1, 0.2), monkeypatch)
    cache = paths.root / "stems"
    assert not cache.exists() or not any(cache.iterdir())


def test_separate_endpoint_records_the_model_on_the_job(tmp_path: Path) -> None:
    settings, _paths, _store, project, _worker, _frames = make_workspace(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        # Replace the engine-backed runner with a contract-only one so this test
        # never loads weights; request validation is unchanged.
        app.state.jobs.register(
            "separate",
            lambda _ctx, params: {"model_id": params["model_id"], "stems": []},
        )
        created = client.post("/api/separate", json={"project_id": project.id})
        assert created.status_code == 202, created.text
        assert created.json()["model_id"] == "htdemucs_ft"
        job_id = created.json()["id"]
        deadline = __import__("time").monotonic() + 5
        while __import__("time").monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["state"] in {"succeeded", "failed", "cancelled"}:
                break
            __import__("time").sleep(0.01)
        assert job["state"] == "succeeded", job
        assert job["result"]["model_id"] == "htdemucs_ft"


def test_separate_endpoint_rejects_unknown_and_missing_models(tmp_path: Path, monkeypatch) -> None:
    settings, _paths, _store, project, _worker, _frames = make_workspace(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        before = client.get("/api/jobs").json()["jobs"]
        unknown = client.post(
            "/api/separate", json={"project_id": project.id, "model_id": "not-a-model"}
        )
        assert unknown.status_code == 400
        assert "unknown model" in unknown.json()["detail"]

        # Simulate a registry model whose weights are not installed, regardless
        # of what this checkout happens to have downloaded locally.
        from basseparate.model_registry import ModelState, load_registry

        registry = load_registry()
        entry = registry.get("bs-roformer-sw")
        missing_state = ModelState(
            entry=entry,
            status="missing",
            model_dir="models/bs-roformer-sw",
            detail="weights are absent",
        )
        monkeypatch.setattr(stems, "verify_model", lambda _entry: missing_state)
        missing = client.post(
            "/api/separate", json={"project_id": project.id, "model_id": "bs-roformer-sw"}
        )
        assert missing.status_code == 400
        assert "not installed" in missing.json()["detail"]
        assert "make models-install" in missing.json()["detail"]
        assert client.get("/api/jobs").json()["jobs"] == before
