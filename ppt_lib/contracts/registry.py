"""Contract registry: load, list, validate JSON schemas and envelopes.

The registry is the single source of truth for all machine contracts that
PPT Library can produce or consume.  Schemas are bundled in
``ppt_lib/contracts/schemas/`` and loaded on demand.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from ppt_lib.contracts.errors import (
    CONTRACT_NOT_FOUND,
    CONTRACT_SCHEMA_INVALID,
    CONTRACT_VALIDATION_FAILED,
    ENVELOPE_FIELDS_INVALID,
    ENVELOPE_MISSING,
    ContractError,
    error,
)

_SCHEMAS_DIR = Path(__file__).parent / "schemas"

# Map of contract name -> schema file stem
_CONTRACT_ALIASES: dict[str, str] = {
    "capabilities.v1": "capabilities.v1",
    "search-request.v2": "search-request.v2",
    "search-response.v2": "search-response.v2",
    "deck-master-selection.v1": "deck-master-selection.v1",
    "deck_master_ppt_library_selection.v1": "deck-master-selection.v1",
    "asset-identity.v1": "asset-identity.v1",
    "feedback-event.v1": "feedback-event.v1",
    "job.v1": "job.v1",
}


@dataclass(frozen=True)
class ContractDefinition:
    """A registered contract with its schema and metadata."""

    name: str
    schema: dict[str, Any]
    schema_path: Path
    title: str
    required_fields: list[str]

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "title": self.title,
            "required_fields": self.required_fields,
            "schema_path": str(self.schema_path),
        }


class ContractRegistry:
    """Lazy-loading registry for JSON contract schemas."""

    def __init__(self, schemas_dir: Path | None = None) -> None:
        self._schemas_dir = schemas_dir or _SCHEMAS_DIR
        self._cache: dict[str, ContractDefinition] = {}

    # --- Query ---

    def list_contracts(self) -> list[ContractDefinition]:
        """Return all registered contracts."""
        if not self._schemas_dir.is_dir():
            return []
        result: list[ContractDefinition] = []
        for schema_file in sorted(self._schemas_dir.glob("*.schema.json")):
            name = schema_file.stem.replace(".schema", "")
            result.append(self.get(name))
        return result

    def get(self, name: str) -> ContractDefinition:
        """Load and return a contract by name."""
        if name in self._cache:
            return self._cache[name]

        resolved = _CONTRACT_ALIASES.get(name, name)
        schema_path = self._schemas_dir / f"{resolved}.schema.json"
        if not schema_path.is_file():
            raise ContractNotFoundError(name)

        with schema_path.open() as f:
            schema = json.load(f)

        defn = ContractDefinition(
            name=name,
            schema=schema,
            schema_path=schema_path,
            title=schema.get("title", name),
            required_fields=schema.get("required", []),
        )
        self._cache[name] = defn
        return defn

    def has(self, name: str) -> bool:
        resolved = _CONTRACT_ALIASES.get(name, name)
        schema_path = self._schemas_dir / f"{resolved}.schema.json"
        return schema_path.is_file()

    # --- Validation ---

    def validate(
        self,
        contract_name: str,
        data: dict[str, Any],
        *,
        strict: bool = True,
    ) -> list[ContractError]:
        """Validate data against a contract schema.

        Returns a list of errors (empty if valid).
        """
        try:
            defn = self.get(contract_name)
        except ContractNotFoundError:
            return [error(CONTRACT_NOT_FOUND, f"Unknown contract: {contract_name}", source_module="contracts.registry")]

        schema = defn.schema if strict else deepcopy(defn.schema)
        if not strict:
            # Compatibility mode only relaxes the contract envelope. Nested
            # objects retain their schema constraints and remain validated.
            schema["additionalProperties"] = True

        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            return [
                error(
                    CONTRACT_SCHEMA_INVALID,
                    f"Invalid schema for contract '{contract_name}': {exc.message}",
                    source_module="contracts.registry",
                    details={
                        "contract": contract_name,
                        "schema_path": _json_pointer(exc.absolute_schema_path),
                    },
                )
            ]

        validator = Draft202012Validator(schema)
        validation_errors = sorted(
            validator.iter_errors(data),
            key=lambda item: (
                tuple(str(part) for part in item.absolute_path),
                tuple(str(part) for part in item.absolute_schema_path),
                item.message,
            ),
        )
        return [_validation_error(contract_name, item) for item in validation_errors]


class ContractNotFoundError(KeyError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Contract not found: {name}")
        self.contract_name = name


def _validation_error(contract_name: str, exc: ValidationError) -> ContractError:
    instance_path = _json_pointer(exc.absolute_path)
    schema_path = _json_pointer(exc.absolute_schema_path)
    location = instance_path or "/"
    message = exc.message
    if exc.validator in {"const", "enum"}:
        message = f"{message}; received {exc.instance!r}"
    return error(
        CONTRACT_VALIDATION_FAILED,
        f"{location}: {message}",
        source_module="contracts.registry",
        details={
            "contract": contract_name,
            "instance_path": instance_path,
            "schema_path": schema_path,
            "validator": str(exc.validator),
        },
    )


def _json_pointer(path: Any) -> str:
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
    return "/" + "/".join(parts) if parts else ""


# --- Envelope helpers ---


def _producer_version() -> str:
    try:
        return metadata.version("ppt-library")
    except metadata.PackageNotFoundError:
        return "0+unknown"


def build_envelope_v2(
    command: str,
    contract: str,
    *,
    request_id: str | None = None,
    run_id: str | None = None,
    query_trace_id: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, object]:
    """Build a v2 _meta envelope for contract output."""
    meta: dict[str, object] = {
        "envelope": "ppt_library.envelope.v2",
        "contract": contract,
        "producer_version": _producer_version(),
        "command": command,
        "request_id": request_id or "",
        "generated_at": datetime.now(UTC).isoformat(),
    }
    if run_id is not None:
        meta["run_id"] = run_id
    if query_trace_id is not None:
        meta["query_trace_id"] = query_trace_id
    if duration_ms is not None:
        meta["duration_ms"] = duration_ms
    return meta


def validate_envelope(data: dict[str, Any]) -> list[ContractError]:
    """Validate that a payload has a well-formed _meta envelope."""
    errors: list[ContractError] = []
    meta = data.get("_meta")
    if meta is None:
        errors.append(error(ENVELOPE_MISSING, "Payload missing _meta envelope", source_module="contracts.registry"))
        return errors

    required = ["envelope", "contract", "producer_version", "command", "generated_at"]
    for field_name in required:
        if field_name not in meta:
            errors.append(
                error(
                    ENVELOPE_FIELDS_INVALID,
                    f"Envelope missing field: {field_name}",
                    source_module="contracts.registry",
                    details={"field": field_name},
                )
            )
    return errors


# Singleton registry
_registry: ContractRegistry | None = None


def get_registry() -> ContractRegistry:
    global _registry
    if _registry is None:
        _registry = ContractRegistry()
    return _registry
