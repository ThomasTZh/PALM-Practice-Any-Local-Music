"""Unit tests for the bundle service: verification, import, provenance (M2.3)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from pathlib import Path

import pytest

from basseparate.models import (
    ArtifactSpec,
    BundleError,
    ModelManifest,
    ProvenanceStore,
    default_bundle_dir,
    default_bundle_root,
    get_manifest,
    import_local_bundle,
    record_provisioning,
    record_qualification,
    verify_bundle,
)

NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


def sha256_of_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _fake_manifest() -> ModelManifest:
    return ModelManifest(
        model_id="fake-model",
        display_name="Fake",
        engine_requirement="test",
        upstream_revision="test",
        artifacts=(
            ArtifactSpec(
                name="preset.yaml",
                role="preset_config",
                size_bytes=4,
                sha256=sha256_of_bytes(b"bag\n"),
                upstream_url="https://example.com/preset.yaml",
            ),
            ArtifactSpec(
                name="a-11112222.th",
                role="checkpoint",
                size_bytes=5,
                sha256=sha256_of_bytes(b"alpha"),
                upstream_url="https://example.com/a.th",
            ),
            ArtifactSpec(
                name="b-33334444.th",
                role="checkpoint",
                size_bytes=5,
                sha256=sha256_of_bytes(b"bravo"),
                upstream_url="https://example.com/b.th",
            ),
        ),
        input_sample_rate=44100,
        input_channels=2,
        output_labels=("drums", "bass", "other", "vocals"),
        license_notice="test",
        notices=("test",),
        bundle_prefix="models/fake-model",
    )


def _write_bundle(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "preset.yaml").write_bytes(b"bag\n")
    (directory / "a-11112222.th").write_bytes(b"alpha")
    (directory / "b-33334444.th").write_bytes(b"bravo")


def test_verify_available_bundle(tmp_path) -> None:
    manifest = _fake_manifest()
    _write_bundle(tmp_path)
    report = verify_bundle(tmp_path, manifest)
    assert report.state == "available"
    assert report.is_available
    assert report.missing == ()
    assert report.corrupt == ()
    assert report.describe() == "bundled_available"


def test_verify_missing_directory(tmp_path) -> None:
    manifest = _fake_manifest()
    report = verify_bundle(tmp_path / "nowhere", manifest)
    assert report.state == "missing"
    assert report.missing == ("preset.yaml", "a-11112222.th", "b-33334444.th")
    assert report.corrupt == ()
    assert report.describe() == (
        "bundled_missing; missing: preset.yaml, a-11112222.th, b-33334444.th"
    )


def test_verify_missing_single_artifact(tmp_path) -> None:
    manifest = _fake_manifest()
    _write_bundle(tmp_path)
    (tmp_path / "b-33334444.th").unlink()
    report = verify_bundle(tmp_path, manifest)
    assert report.state == "missing"
    assert report.missing == ("b-33334444.th",)
    assert report.corrupt == ()


def test_verify_corrupt_hash(tmp_path) -> None:
    manifest = _fake_manifest()
    _write_bundle(tmp_path)
    (tmp_path / "a-11112222.th").write_bytes(b"ALPHA")  # same size, wrong bytes
    report = verify_bundle(tmp_path, manifest)
    assert report.state == "corrupt"
    assert report.corrupt == ("a-11112222.th",)
    assert report.missing == ()
    assert "bundled_corrupt" in report.describe()


def test_verify_corrupt_size(tmp_path) -> None:
    manifest = _fake_manifest()
    _write_bundle(tmp_path)
    (tmp_path / "a-11112222.th").write_bytes(b"alphaX")  # wrong size
    report = verify_bundle(tmp_path, manifest)
    assert report.state == "corrupt"
    assert report.corrupt == ("a-11112222.th",)


def test_verify_mixed_missing_and_corrupt_reports_both(tmp_path) -> None:
    manifest = _fake_manifest()
    _write_bundle(tmp_path)
    (tmp_path / "preset.yaml").unlink()
    (tmp_path / "a-11112222.th").write_bytes(b"ALPHA")
    report = verify_bundle(tmp_path, manifest)
    # Missing takes precedence in the state; both lists are populated.
    assert report.state == "missing"
    assert report.missing == ("preset.yaml",)
    assert report.corrupt == ("a-11112222.th",)


def test_import_local_bundle_happy_path(tmp_path) -> None:
    manifest = _fake_manifest()
    source = tmp_path / "source"
    _write_bundle(source)
    target = tmp_path / "install" / "models" / "fake-model"
    report = import_local_bundle(source, target, manifest)
    assert report.state == "available"
    for spec in manifest.artifacts:
        assert (target / spec.name).is_file()


def test_import_rejects_executable_files(tmp_path) -> None:
    manifest = _fake_manifest()
    source = tmp_path / "source"
    _write_bundle(source)
    (source / "plugin.py").write_text("import os")
    with pytest.raises(BundleError, match="executable"):
        import_local_bundle(source, tmp_path / "target", manifest)
    (source / "plugin.py").unlink()
    (source / "run.sh").write_text("#!/bin/sh")
    with pytest.raises(BundleError, match="executable"):
        import_local_bundle(source, tmp_path / "target", manifest)


def test_import_rejects_files_not_in_manifest(tmp_path) -> None:
    manifest = _fake_manifest()
    source = tmp_path / "source"
    _write_bundle(source)
    (source / "extra.txt").write_text("not registered")
    with pytest.raises(BundleError, match="not in the manifest"):
        import_local_bundle(source, tmp_path / "target", manifest)


def test_import_rejects_corrupt_source(tmp_path) -> None:
    manifest = _fake_manifest()
    source = tmp_path / "source"
    _write_bundle(source)
    (source / "a-11112222.th").write_bytes(b"ALPHA")
    with pytest.raises(BundleError, match="does not verify"):
        import_local_bundle(source, tmp_path / "target", manifest)
    assert not (tmp_path / "target").exists()


def test_import_rejects_missing_source_artifact(tmp_path) -> None:
    manifest = _fake_manifest()
    source = tmp_path / "source"
    _write_bundle(source)
    (source / "b-33334444.th").unlink()
    with pytest.raises(BundleError, match="does not verify"):
        import_local_bundle(source, tmp_path / "target", manifest)


def test_import_rejects_nonexistent_source(tmp_path) -> None:
    manifest = _fake_manifest()
    with pytest.raises(BundleError, match="not a directory"):
        import_local_bundle(tmp_path / "nope", tmp_path / "target", manifest)


def test_import_verifies_after_copy_and_cleans_up_on_failure(tmp_path, monkeypatch) -> None:
    import basseparate.models.bundle as bundle

    manifest = _fake_manifest()
    source = tmp_path / "source"
    _write_bundle(source)
    target = tmp_path / "target"

    real_sha256 = bundle.sha256_of

    def corrupting_sha256(path: Path) -> str:
        if path.parent == target:
            return "0" * 64
        return real_sha256(path)

    monkeypatch.setattr(bundle, "sha256_of", corrupting_sha256)
    with pytest.raises(BundleError, match="packaged copy does not verify"):
        import_local_bundle(source, target, manifest)
    # The copied files were removed again.
    for spec in manifest.artifacts:
        assert not (target / spec.name).exists()


def test_default_dirs_point_at_the_dev_workspace() -> None:
    manifest = get_manifest("htdemucs_ft")
    root = default_bundle_root()
    assert (root / "models").is_dir()  # the git-ignored workspace model dir
    assert default_bundle_dir(manifest) == root / "models" / "htdemucs_ft"


def test_provenance_store_round_trip(tmp_path) -> None:
    store = ProvenanceStore(tmp_path / "data" / "models.json")
    assert store.load() == {}
    record = record_provisioning(store, get_manifest("htdemucs_ft"), source="dev-download", now=NOW)
    assert record.qualification_status == "not-qualified"
    assert record.provisioned_at == "2026-10-10T12:00:00Z"
    assert len(record.artifact_hashes) == 5
    loaded = store.load()
    assert loaded["htdemucs_ft"] == record


def test_provenance_store_rejects_bad_version(tmp_path) -> None:
    path = tmp_path / "models.json"
    path.write_text('{"version": 99, "models": {}}\n', encoding="utf-8")
    with pytest.raises(BundleError, match="unsupported version"):
        ProvenanceStore(path).load()


def test_provenance_store_rejects_malformed(tmp_path) -> None:
    path = tmp_path / "models.json"
    path.write_text('{"version": 1, "models": {"x": "not-a-dict"}}\n', encoding="utf-8")
    with pytest.raises(BundleError, match="malformed"):
        ProvenanceStore(path).load()


def test_record_qualification_updates_existing_record(tmp_path) -> None:
    store = ProvenanceStore(tmp_path / "models.json")
    record_provisioning(store, get_manifest("htdemucs_ft"), source="dev-download", now=NOW)
    updated = record_qualification(
        store, "htdemucs_ft", True, "offline 5 s run, finite output", now=NOW
    )
    assert updated.qualification_status == "qualified"
    assert updated.qualification_detail == "offline 5 s run, finite output"
    assert updated.source == "dev-download"
    assert updated.provisioned_at == "2026-10-10T12:00:00Z"
    assert len(updated.artifact_hashes) == 5


def test_record_qualification_failure_status(tmp_path) -> None:
    store = ProvenanceStore(tmp_path / "models.json")
    record_provisioning(store, get_manifest("htdemucs_ft"), source="dev-download", now=NOW)
    updated = record_qualification(store, "htdemucs_ft", False, "NaN output", now=NOW)
    assert updated.qualification_status == "failed"
    assert updated.qualification_detail == "NaN output"


def test_record_qualification_creates_record_when_missing(tmp_path) -> None:
    store = ProvenanceStore(tmp_path / "models.json")
    updated = record_qualification(store, "htdemucs_ft", True, "detail", now=NOW)
    assert updated.qualification_status == "qualified"
    assert updated.source == "unrecorded"
    assert len(updated.artifact_hashes) == 5


def test_record_provisioning_resets_qualification(tmp_path) -> None:
    store = ProvenanceStore(tmp_path / "models.json")
    record_provisioning(store, get_manifest("htdemucs_ft"), source="dev-download", now=NOW)
    record_qualification(store, "htdemucs_ft", True, "ok", now=NOW)
    re_provisioned = record_provisioning(
        store, get_manifest("htdemucs_ft"), source="local-import", now=NOW
    )
    assert re_provisioned.qualification_status == "not-qualified"
    assert re_provisioned.source == "local-import"


def test_record_provisioning_requires_manifest_or_id(tmp_path) -> None:
    store = ProvenanceStore(tmp_path / "models.json")
    with pytest.raises(BundleError, match="manifest or a model_id"):
        record_provisioning(store, source="x")


def test_dataclasses_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        get_manifest("htdemucs_ft").display_name = "nope"  # type: ignore[misc]
