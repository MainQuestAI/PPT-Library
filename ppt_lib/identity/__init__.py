"""PPT Library stable asset identity."""

from ppt_lib.identity.fingerprint import (
    FINGERPRINT_VERSION,
    compute_content_hash,
    compute_deck_revision_id,
    compute_file_content_hash,
    compute_slide_revision_id,
)
from ppt_lib.identity.registry import (
    IdentityCoverageReport,
    IdentityMapping,
    export_identity_registry,
    get_identity_by_canonical,
    get_identity_by_revision,
    get_identity_coverage,
    import_identity_registry,
    upsert_identity_mapping,
)

__all__ = [
    "FINGERPRINT_VERSION",
    "IdentityCoverageReport",
    "IdentityMapping",
    "compute_content_hash",
    "compute_deck_revision_id",
    "compute_file_content_hash",
    "compute_slide_revision_id",
    "export_identity_registry",
    "get_identity_by_canonical",
    "get_identity_by_revision",
    "get_identity_coverage",
    "import_identity_registry",
    "upsert_identity_mapping",
]
