"""Rhythm model registry and explicit install boundary (M3.2, §4.2-§4.4)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from basseparate.models.install import (
    DownloadCancelledError,
    HashMismatchError,
    ModelDownloadError,
    ModelInstallError,
    ModelNotInstalledError,
    ModelStore,
    OfflineBundleError,
    OfflineModeError,
    install_from_bundle,
    install_from_download,
)
from basseparate.models.rhythm_registry import (
    BEAT_THIS_FINAL0_ID,
    BEAT_THIS_SMALL0_ID,
    RHYTHM_MODELS,
    RhythmCheckpoint,
    RhythmModelManifest,
    RhythmRegistryError,
    _validate_manifest,
    get_rhythm_model,
    list_rhythm_models,
)

FINAL0 = get_rhythm_model(BEAT_THIS_FINAL0_ID)
SMALL0 = get_rhythm_model(BEAT_THIS_SMALL0_ID)
PAYLOAD = b"beat-this-test-checkpoint" * 100
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _manifest(**overrides: object) -> RhythmModelManifest:
    base = replace(
        FINAL0,
        model_id="test_model",
        checkpoint=RhythmCheckpoint(
            filename="test.ckpt",
            size_bytes=len(PAYLOAD),
            sha256=PAYLOAD_SHA,
            upstream_url="https://example.invalid/test.ckpt",
        ),
    )
    return replace(base, **overrides)


class FakeResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.closed = False

    def read(self, _size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    def close(self) -> None:
        self.closed = True


def _chunks(data: bytes, size: int) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


# --- Registry ------------------------------------------------------------


class TestRhythmRegistry:
    def test_pinned_models(self) -> None:
        assert set(RHYTHM_MODELS) == {FINAL0.model_id, SMALL0.model_id}
        assert [m.model_id for m in list_rhythm_models()] == [
            FINAL0.model_id,
            SMALL0.model_id,
        ]
        final = get_rhythm_model("beat_this_final0")
        assert final.checkpoint.size_bytes == 81_058_141
        assert final.checkpoint.sha256.startswith("8c328b45")
        assert final.input_sample_rate == 22_050
        assert final.frame_hop == 441
        assert final.frame_rate == 50.0
        assert final.code_license == "MIT"
        assert final.weights_license == "MIT"

    def test_unknown_model(self) -> None:
        with pytest.raises(KeyError):
            get_rhythm_model("missing")

    def test_validation_rejects_bad_manifests(self) -> None:
        with pytest.raises(RhythmRegistryError):
            _validate_manifest(replace(FINAL0, model_id=""))
        with pytest.raises(RhythmRegistryError):
            _validate_manifest(
                replace(
                    FINAL0,
                    checkpoint=replace(FINAL0.checkpoint, sha256="not-a-hash"),
                )
            )
        with pytest.raises(RhythmRegistryError):
            _validate_manifest(replace(FINAL0, frame_rate=49.0))
        with pytest.raises(RhythmRegistryError):
            _validate_manifest(
                replace(
                    FINAL0,
                    checkpoint=replace(FINAL0.checkpoint, upstream_url="http://insecure"),
                )
            )


# --- Install from download ----------------------------------------------


class TestInstallFromDownload:
    def test_success_and_provenance(self, tmp_path: Path) -> None:
        store = ModelStore(tmp_path / "models")
        manifest = _manifest()
        progress: list[tuple[int, int | None]] = []
        response = FakeResponse(_chunks(PAYLOAD, 64))

        installed = install_from_download(
            manifest,
            store,
            offline_mode=False,
            progress=lambda done, total: progress.append((done, total)),
            opener=lambda _url: response,
        )

        assert installed.model_id == manifest.model_id
        assert installed.checkpoint_path == store.checkpoint_path(manifest)
        assert installed.checkpoint_path.read_bytes() == PAYLOAD
        assert installed.sha256 == PAYLOAD_SHA
        assert progress[-1] == (len(PAYLOAD), len(PAYLOAD))
        assert response.closed
        assert store.is_installed(manifest)
        assert store.is_installed(manifest, verify_hash=True)
        assert not list(store.staging_dir.iterdir())

        record = store.installed_record(manifest)
        assert record is not None
        assert record["source"] == "download"
        assert record["checkpoint"]["sha256"] == PAYLOAD_SHA
        assert "MIT licensed" in record["license_notice"]
        assert record["notices"]
        assert store.resolve_checkpoint(manifest) == installed.checkpoint_path

    def test_offline_mode_blocks_before_network(self, tmp_path: Path) -> None:
        store = ModelStore(tmp_path / "models")
        called = False

        def opener(_url: str) -> FakeResponse:
            nonlocal called
            called = True
            return FakeResponse([])

        with pytest.raises(OfflineModeError):
            install_from_download(_manifest(), store, offline_mode=True, opener=opener)
        assert called is False
        assert not store.root.exists()

    def test_hash_mismatch_leaves_nothing(self, tmp_path: Path) -> None:
        store = ModelStore(tmp_path / "models")
        with pytest.raises(HashMismatchError):
            install_from_download(
                _manifest(),
                store,
                offline_mode=False,
                opener=lambda _url: FakeResponse(_chunks(b"x" * len(PAYLOAD), 512)),
            )
        assert not store.checkpoint_path(_manifest()).exists()
        assert not list(store.staging_dir.iterdir())

    def test_size_mismatch(self, tmp_path: Path) -> None:
        store = ModelStore(tmp_path / "models")
        with pytest.raises(ModelDownloadError):
            install_from_download(
                _manifest(),
                store,
                offline_mode=False,
                opener=lambda _url: FakeResponse([PAYLOAD[:-1]]),
            )

    def test_cancellation(self, tmp_path: Path) -> None:
        store = ModelStore(tmp_path / "models")
        calls = {"n": 0}

        def cancel() -> bool:
            calls["n"] += 1
            return calls["n"] > 1

        with pytest.raises(DownloadCancelledError):
            install_from_download(
                _manifest(),
                store,
                offline_mode=False,
                opener=lambda _url: FakeResponse(_chunks(PAYLOAD, 32)),
                cancel=cancel,
            )
        assert not list(store.staging_dir.iterdir())

    def test_network_error(self, tmp_path: Path) -> None:
        store = ModelStore(tmp_path / "models")

        def opener(_url: str) -> FakeResponse:
            raise OSError("connection refused")

        with pytest.raises(ModelDownloadError, match="connection refused"):
            install_from_download(_manifest(), store, offline_mode=False, opener=opener)

    def test_not_installed_and_tampered_checkpoint(self, tmp_path: Path) -> None:
        store = ModelStore(tmp_path / "models")
        manifest = _manifest()
        with pytest.raises(ModelNotInstalledError):
            store.resolve_checkpoint(manifest)

        store.root.mkdir(parents=True)
        model_dir = store.model_dir(manifest)
        model_dir.mkdir(parents=True)
        store.checkpoint_path(manifest).write_bytes(b"tampered" * 100)
        with pytest.raises(ModelInstallError):
            store.resolve_checkpoint(manifest)


# --- Offline bundle import ----------------------------------------------


def _write_bundle(root: Path, manifest: RhythmModelManifest, *, payload: bytes = PAYLOAD) -> Path:
    bundle = root / "bundle"
    bundle.mkdir(parents=True)
    (bundle / manifest.checkpoint.filename).write_bytes(payload)
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "model_id": manifest.model_id,
                "checkpoint_filename": manifest.checkpoint.filename,
                "size_bytes": manifest.checkpoint.size_bytes,
                "sha256": manifest.checkpoint.sha256,
                "adapter_version": manifest.adapter_version,
                "package_version": manifest.package_version,
            }
        ),
        encoding="utf-8",
    )
    return bundle


class TestInstallFromBundle:
    def test_success(self, tmp_path: Path) -> None:
        manifest = _manifest()
        bundle = _write_bundle(tmp_path, manifest)
        store = ModelStore(tmp_path / "models")
        installed = install_from_bundle(manifest, store, bundle)
        assert installed.source == "bundle"
        assert store.is_installed(manifest, verify_hash=True)
        record = store.installed_record(manifest)
        assert record is not None
        assert record["source"] == "bundle"
        assert record["bundle_manifest"]["model_id"] == manifest.model_id

    def test_identity_mismatch(self, tmp_path: Path) -> None:
        manifest = _manifest()
        bundle = _write_bundle(tmp_path, manifest)
        data = json.loads((bundle / "manifest.json").read_text())
        data["sha256"] = "f" * 64
        (bundle / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(OfflineBundleError):
            install_from_bundle(manifest, ModelStore(tmp_path / "models"), bundle)

    def test_payload_mismatch(self, tmp_path: Path) -> None:
        manifest = _manifest()
        bundle = _write_bundle(tmp_path, manifest, payload=b"corrupted")
        with pytest.raises(OfflineBundleError):
            install_from_bundle(manifest, ModelStore(tmp_path / "models"), bundle)

    def test_missing_bundle(self, tmp_path: Path) -> None:
        with pytest.raises(OfflineBundleError):
            install_from_bundle(_manifest(), ModelStore(tmp_path / "models"), tmp_path / "missing")
