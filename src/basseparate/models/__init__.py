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
from basseparate.models.registry import (
    REGISTRY,
    ArtifactSpec,
    ModelManifest,
    RegistryError,
    get_manifest,
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
