"""Unit tests for the bundled model registry (M2.3)."""

from __future__ import annotations

import dataclasses

import pytest

from basseparate.models import (
    REGISTRY,
    ArtifactSpec,
    ModelManifest,
    RegistryError,
    get_manifest,
)


def test_registry_contains_exactly_the_htdemucs_ft_baseline() -> None:
    assert set(REGISTRY) == {"htdemucs_ft"}


def test_manifest_structure() -> None:
    manifest = get_manifest("htdemucs_ft")
    assert manifest.display_name
    assert manifest.engine_requirement
    assert manifest.upstream_revision
    assert manifest.bundle_prefix == "models/htdemucs_ft"
    assert manifest.input_sample_rate == 44100
    assert manifest.input_channels == 2
    assert manifest.output_labels == ("drums", "bass", "other", "vocals")
    assert manifest.license_notice
    assert manifest.notices


def test_manifest_artifact_set() -> None:
    manifest = get_manifest("htdemucs_ft")
    names = [spec.name for spec in manifest.artifacts]
    assert names == [
        "htdemucs_ft.yaml",
        "f7e0c4bc-ba3fe64a.th",
        "d12395a8-e57c48e6.th",
        "92cfc3b6-ef3bcb9c.th",
        "04573f0d-f3cf25b2.th",
    ]
    roles = {spec.name: spec.role for spec in manifest.artifacts}
    assert roles["htdemucs_ft.yaml"] == "preset_config"
    for name in names[1:]:
        assert roles[name] == "checkpoint"


def test_manifest_sizes_and_total() -> None:
    manifest = get_manifest("htdemucs_ft")
    sizes = {spec.name: spec.size_bytes for spec in manifest.artifacts}
    assert sizes["htdemucs_ft.yaml"] == 149
    for name in list(sizes)[1:]:
        assert sizes[name] == 84141271
    assert manifest.total_size_bytes == 149 + 4 * 84141271 == 336565233


def test_checkpoint_hashes_match_embedded_filename_checksums() -> None:
    """demucs embeds the first 8 hex chars of the SHA-256 in the file name."""
    manifest = get_manifest("htdemucs_ft")
    for spec in manifest.artifacts:
        if spec.role != "checkpoint":
            continue
        stem = spec.name.removesuffix(".th")
        signature, embedded = stem.rsplit("-", 1)
        assert spec.sha256.startswith(embedded), spec.name
        assert len(signature) == 8


def test_upstream_urls_are_https_provenance() -> None:
    manifest = get_manifest("htdemucs_ft")
    for spec in manifest.artifacts:
        assert spec.upstream_url.startswith("https://")
        assert spec.name.rsplit(".", 1)[0] in spec.upstream_url
    yaml_spec = manifest.artifact("htdemucs_ft.yaml")
    assert "github.com/adefossez/demucs" in yaml_spec.upstream_url
    for spec in list(manifest.artifacts)[1:]:
        assert "dl.fbaipublicfiles.com/demucs/hybrid_transformer" in spec.upstream_url


def test_get_manifest_unknown_id_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        get_manifest("no-such-model")


def _manifest(**overrides: object) -> ModelManifest:
    base = get_manifest("htdemucs_ft")
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def _spec(**overrides: object) -> ArtifactSpec:
    base = get_manifest("htdemucs_ft").artifacts[0]
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def test_invariants_accept_the_checked_in_manifest() -> None:
    # Import-time validation already ran; re-running must not raise.
    manifest = get_manifest("htdemucs_ft")
    from basseparate.models.registry import _validate_manifest

    _validate_manifest(manifest)


def test_invariants_reject_duplicates() -> None:
    from basseparate.models.registry import _validate_manifest

    manifest = _manifest(
        artifacts=(
            get_manifest("htdemucs_ft").artifacts[0],
            get_manifest("htdemucs_ft").artifacts[0],
        )
    )
    with pytest.raises(RegistryError, match="duplicate artifact name"):
        _validate_manifest(manifest)


def test_invariants_reject_bad_hash() -> None:
    from basseparate.models.registry import _validate_manifest

    manifest = _manifest(
        artifacts=(
            _spec(sha256="XYZ"),
            *get_manifest("htdemucs_ft").artifacts[1:],
        )
    )
    with pytest.raises(RegistryError, match="sha256"):
        _validate_manifest(manifest)


def test_invariants_reject_non_positive_size() -> None:
    from basseparate.models.registry import _validate_manifest

    manifest = _manifest(
        artifacts=(_spec(size_bytes=0), *get_manifest("htdemucs_ft").artifacts[1:])
    )
    with pytest.raises(RegistryError, match="size must be positive"):
        _validate_manifest(manifest)


def test_invariants_reject_path_traversal_prefix() -> None:
    from basseparate.models.registry import _validate_manifest

    manifest = _manifest(bundle_prefix="../escape")
    with pytest.raises(RegistryError, match="traversal"):
        _validate_manifest(manifest)


def test_invariants_reject_non_https_url() -> None:
    from basseparate.models.registry import _validate_manifest

    manifest = _manifest(artifacts=(_spec(upstream_url="http://insecure.example/x"),))
    with pytest.raises(RegistryError, match="https"):
        _validate_manifest(manifest)


def test_invariants_reject_unsafe_artifact_name() -> None:
    from basseparate.models.registry import _validate_manifest

    manifest = _manifest(artifacts=(_spec(name="sub/dir.th"),))
    with pytest.raises(RegistryError, match="plain file name"):
        _validate_manifest(manifest)


def test_invariants_reject_empty_labels() -> None:
    from basseparate.models.registry import _validate_manifest

    manifest = _manifest(output_labels=())
    with pytest.raises(RegistryError, match="output_labels"):
        _validate_manifest(manifest)


def test_invariants_reject_duplicate_labels() -> None:
    from basseparate.models.registry import _validate_manifest

    manifest = _manifest(output_labels=("bass", "bass"))
    with pytest.raises(RegistryError, match="duplicate output label"):
        _validate_manifest(manifest)


def test_invariants_reject_empty_artifact_list() -> None:
    from basseparate.models.registry import _validate_manifest

    manifest = _manifest(artifacts=())
    with pytest.raises(RegistryError, match="at least one artifact"):
        _validate_manifest(manifest)
