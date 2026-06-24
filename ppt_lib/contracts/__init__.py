"""PPT Library contract registry and error codes."""

from ppt_lib.contracts.errors import (
    CONTRACT_NOT_FOUND,
    CONTRACT_SCHEMA_INVALID,
    CONTRACT_VALIDATION_FAILED,
    ContractError,
    error,
    warning,
)
from ppt_lib.contracts.registry import (
    ContractDefinition,
    ContractNotFoundError,
    ContractRegistry,
    build_envelope_v2,
    get_registry,
    validate_envelope,
)

__all__ = [
    "CONTRACT_NOT_FOUND",
    "CONTRACT_SCHEMA_INVALID",
    "CONTRACT_VALIDATION_FAILED",
    "ContractDefinition",
    "ContractError",
    "ContractNotFoundError",
    "ContractRegistry",
    "build_envelope_v2",
    "error",
    "get_registry",
    "validate_envelope",
    "warning",
]
