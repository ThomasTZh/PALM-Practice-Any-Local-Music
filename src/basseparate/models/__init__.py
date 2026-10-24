"""Bundled model baseline: registry, verification, import, provenance.

The registry (``registry.py``) is the checked-in, hash-pinned description of
the bundled Demucs preset. The bundle service (``bundle.py``) verifies
artifact directories, imports local bundles, and records provenance. No
torch or demucs imports — model *loading* happens in the analysis
environment.
"""

from basseparate.models.bundle import (
    BundleError,
    BundleReport,
    ProvenanceRecord,
    ProvenanceStore,
    default_bundle_dir,
    default_bundle_root,
    import_local_bundle,
    record_provisioning,
    record_qualification,
    sha256_of,
    verify_bundle,
)
from basseparate.models.install import (
    DownloadCancelledError,
    HashMismatchError,
    InstalledModel,
    ModelDownloadError,
    ModelInstallError,
    ModelNotInstalledError,
    ModelStore,
    OfflineBundleError,
    OfflineModeError,
    install_from_bundle,
    install_from_download,
    sha256_file,
)
from basseparate.models.registry import (
    REGISTRY,
    ArtifactSpec,
    ModelManifest,
    RegistryError,
    get_manifest,
)
from basseparate.models.rhythm_registry import (
    BEAT_THIS_FINAL0_ID,
    BEAT_THIS_SMALL0_ID,
    RHYTHM_MODELS,
    RhythmCheckpoint,
    RhythmModelManifest,
    RhythmRegistryError,
    get_rhythm_model,
    list_rhythm_models,
)
from basseparate.models.verification import (
    VERIFICATION_STORE_VERSION,
    VerificationRecord,
    VerificationStore,
)

__all__ = [
    "REGISTRY",
    "ArtifactSpec",
    "BundleError",
    "BundleReport",
    "ModelManifest",
    "ProvenanceRecord",
    "ProvenanceStore",
    "RegistryError",
    "DownloadCancelledError",
    "HashMismatchError",
    "InstalledModel",
    "ModelDownloadError",
    "ModelInstallError",
    "ModelNotInstalledError",
    "ModelStore",
    "OfflineBundleError",
    "OfflineModeError",
    "install_from_bundle",
    "install_from_download",
    "sha256_file",
    "BEAT_THIS_FINAL0_ID",
    "BEAT_THIS_SMALL0_ID",
    "RHYTHM_MODELS",
    "RhythmCheckpoint",
    "RhythmModelManifest",
    "RhythmRegistryError",
    "get_rhythm_model",
    "list_rhythm_models",
    "default_bundle_dir",
    "default_bundle_root",
    "get_manifest",
    "import_local_bundle",
    "record_provisioning",
    "record_qualification",
    "sha256_of",
    "verify_bundle",
    "VERIFICATION_STORE_VERSION",
    "VerificationRecord",
    "VerificationStore",
]
