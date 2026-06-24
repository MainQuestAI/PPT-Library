"""Stable error codes for PPT Library contracts.

All machine-readable error output MUST use these codes. Never invent ad-hoc
strings; add a new constant here first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ErrorSeverity = Literal["error", "warning"]


# --- Envelope / Contract errors ---
CONTRACT_NOT_FOUND = "CONTRACT_NOT_FOUND"
CONTRACT_SCHEMA_INVALID = "CONTRACT_SCHEMA_INVALID"
CONTRACT_VALIDATION_FAILED = "CONTRACT_VALIDATION_FAILED"
CONTRACT_VERSION_MISMATCH = "CONTRACT_VERSION_MISMATCH"
CONTRACT_PRODUCER_UNKNOWN = "CONTRACT_PRODUCER_UNKNOWN"
ENVELOPE_MISSING = "ENVELOPE_MISSING"
ENVELOPE_FIELDS_INVALID = "ENVELOPE_FIELDS_INVALID"

# --- Capability errors ---
CAPABILITY_PROVIDER_UNAVAILABLE = "CAPABILITY_PROVIDER_UNAVAILABLE"
CAPABILITY_PROVIDER_UNHEALTHY = "CAPABILITY_PROVIDER_UNHEALTHY"
CAPABILITY_FEATURE_DISABLED = "CAPABILITY_FEATURE_DISABLED"

# --- Identity errors ---
IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
IDENTITY_LEGACY_UNMAPPED = "IDENTITY_LEGACY_UNMAPPED"

# --- Job errors ---
JOB_NOT_FOUND = "JOB_NOT_FOUND"
JOB_ALREADY_RUNNING = "JOB_ALREADY_RUNNING"
JOB_NOT_RESUMABLE = "JOB_NOT_RESUMABLE"
JOB_CANCELLED = "JOB_CANCELLED"
JOB_STAGE_FAILED = "JOB_STAGE_FAILED"
JOB_IDEMPOTENCY_CONFLICT = "JOB_IDEMPOTENCY_CONFLICT"

# --- Migration errors ---
MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
MIGRATION_FAILED = "MIGRATION_FAILED"
MIGRATION_INCOMPLETE = "MIGRATION_INCOMPLETE"
MIGRATION_BACKUP_MISSING = "MIGRATION_BACKUP_MISSING"

# --- PPTX / Renderer safety ---
PPTX_ARCHIVE_LIMIT_EXCEEDED = "PPTX_ARCHIVE_LIMIT_EXCEEDED"
PPTX_PATH_TRAVERSAL_DETECTED = "PPTX_PATH_TRAVERSAL_DETECTED"
PPTX_EXTERNAL_RELATIONSHIP_BLOCKED = "PPTX_EXTERNAL_RELATIONSHIP_BLOCKED"
RENDER_TIMEOUT = "RENDER_TIMEOUT"
SOURCE_CHANGED_DURING_INDEX = "SOURCE_CHANGED_DURING_INDEX"
DISK_SPACE_INSUFFICIENT = "DISK_SPACE_INSUFFICIENT"

# --- Search errors ---
SEARCH_NO_RESULTS = "SEARCH_NO_RESULTS"
SEARCH_BACKEND_UNAVAILABLE = "SEARCH_BACKEND_UNAVAILABLE"
SEARCH_FALLBACK_ACTIVE = "SEARCH_FALLBACK_ACTIVE"
SEARCH_PROFILE_UNKNOWN = "SEARCH_PROFILE_UNKNOWN"

# --- Generic ---
INTERNAL_ERROR = "INTERNAL_ERROR"
INVALID_INPUT = "INVALID_INPUT"
CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
FILE_NOT_FOUND = "FILE_NOT_FOUND"
PERMISSION_DENIED = "PERMISSION_DENIED"


@dataclass(frozen=True)
class ContractError:
    """A structured error record for machine contract output."""

    code: str
    message: str
    source_module: str = ""
    severity: ErrorSeverity = "error"
    details: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "source_module": self.source_module,
            "severity": self.severity,
            "details": self.details,
        }


def error(
    code: str,
    message: str,
    *,
    source_module: str = "",
    details: dict[str, object] | None = None,
) -> ContractError:
    return ContractError(
        code=code,
        message=message,
        source_module=source_module,
        details=details or {},
    )


def warning(
    code: str,
    message: str,
    *,
    source_module: str = "",
    details: dict[str, object] | None = None,
) -> ContractError:
    return ContractError(
        code=code,
        message=message,
        source_module=source_module,
        severity="warning",
        details=details or {},
    )
