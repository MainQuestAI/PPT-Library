"""Tests for contract registry and error codes (1.5-B)."""

from __future__ import annotations

import pytest

from ppt_lib.contracts import (
    CONTRACT_NOT_FOUND,
    CONTRACT_VALIDATION_FAILED,
    ContractNotFoundError,
    build_envelope_v2,
    get_registry,
    validate_envelope,
)
from ppt_lib.contracts.errors import (
    ContractError,
    error,
    warning,
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestContractRegistry:
    def test_list_contracts_returns_all_schemas(self):
        registry = get_registry()
        contracts = registry.list_contracts()
        assert len(contracts) == 7
        names = {c.name for c in contracts}
        assert "capabilities.v1" in names
        assert "search-response.v2" in names
        assert "search-request.v2" in names
        assert "asset-identity.v1" in names
        assert "feedback-event.v1" in names
        assert "job.v1" in names
        assert "deck-master-selection.v1" in names

    def test_get_returns_definition(self):
        registry = get_registry()
        defn = registry.get("capabilities.v1")
        assert defn.name == "capabilities.v1"
        assert defn.title == "PPT Library Capabilities v1"
        assert "contract" in defn.required_fields
        assert defn.schema_path.is_file()

    def test_get_unknown_raises(self):
        registry = get_registry()
        with pytest.raises(ContractNotFoundError) as exc_info:
            registry.get("nonexistent.v99")
        assert exc_info.value.contract_name == "nonexistent.v99"

    def test_has_returns_true_for_known(self):
        registry = get_registry()
        assert registry.has("capabilities.v1") is True
        assert registry.has("search-response.v2") is True

    def test_has_returns_false_for_unknown(self):
        registry = get_registry()
        assert registry.has("nonexistent.v99") is False

    def test_caching(self):
        registry = get_registry()
        defn1 = registry.get("capabilities.v1")
        defn2 = registry.get("capabilities.v1")
        assert defn1 is defn2

    def test_to_json(self):
        registry = get_registry()
        defn = registry.get("capabilities.v1")
        j = defn.to_json()
        assert j["name"] == "capabilities.v1"
        assert "title" in j
        assert "required_fields" in j


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestContractValidation:
    def test_valid_capabilities_payload(self):
        registry = get_registry()
        payload = {
            "contract": "ppt_library.capabilities.v1",
            "producer_version": "1.5.0",
            "modes": ["local"],
            "features": {"screenshots": True},
            "contracts": ["capabilities.v1"],
            "providers": {"embedding": []},
            "storage": {"metadata": ["sqlite"]},
        }
        errors = registry.validate("capabilities.v1", payload)
        assert errors == []

    def test_missing_required_field(self):
        registry = get_registry()
        payload = {
            "contract": "ppt_library.capabilities.v1",
            # missing producer_version, modes, features, etc.
        }
        errors = registry.validate("capabilities.v1", payload)
        assert len(errors) > 0
        codes = {e.code for e in errors}
        assert CONTRACT_VALIDATION_FAILED in codes

    def test_const_field_mismatch(self):
        registry = get_registry()
        payload = {
            "contract": "WRONG_VALUE",
            "producer_version": "1.5.0",
            "modes": ["local"],
            "features": {},
            "contracts": [],
            "providers": {},
            "storage": {},
        }
        errors = registry.validate("capabilities.v1", payload)
        assert any(e.code == CONTRACT_VALIDATION_FAILED for e in errors)
        assert any("WRONG_VALUE" in e.message for e in errors)

    def test_unknown_contract(self):
        registry = get_registry()
        errors = registry.validate("nonexistent.v99", {})
        assert len(errors) == 1
        assert errors[0].code == CONTRACT_NOT_FOUND

    def test_strict_additional_properties(self):
        registry = get_registry()
        # search-response.v2 has additionalProperties: false
        payload = {
            "_meta": {
                "envelope": "ppt_library.envelope.v2",
                "contract": "ppt_library.search_response.v2",
                "producer_version": "1.5.0",
                "command": "search",
                "request_id": "req-1",
                "generated_at": "2026-06-23T00:00:00Z",
            },
            "data": {"candidates": []},
            "_warnings": [],
            "_errors": [],
            "extra_field": "not allowed",
        }
        errors = registry.validate("search-response.v2", payload, strict=True)
        assert any("extra_field" in e.message for e in errors)

    def test_non_strict_allows_additional_properties(self):
        registry = get_registry()
        payload = {
            "_meta": {
                "envelope": "ppt_library.envelope.v2",
                "contract": "ppt_library.search_response.v2",
                "producer_version": "1.5.0",
                "command": "search",
                "request_id": "req-1",
                "generated_at": "2026-06-23T00:00:00Z",
            },
            "data": {"candidates": []},
            "_warnings": [],
            "_errors": [],
            "extra_field": "allowed in non-strict",
        }
        errors = registry.validate("search-response.v2", payload, strict=False)
        assert errors == []


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_build_envelope_v2(self):
        meta = build_envelope_v2(
            "search",
            "ppt_library.search_response.v2",
            request_id="req-1",
            run_id="run-1",
            query_trace_id="trace-1",
            duration_ms=42,
        )
        assert meta["envelope"] == "ppt_library.envelope.v2"
        assert meta["contract"] == "ppt_library.search_response.v2"
        assert meta["command"] == "search"
        assert meta["request_id"] == "req-1"
        assert meta["run_id"] == "run-1"
        assert meta["query_trace_id"] == "trace-1"
        assert meta["duration_ms"] == 42
        assert "producer_version" in meta
        assert "generated_at" in meta

    def test_build_envelope_v2_optional_fields(self):
        meta = build_envelope_v2("test", "test.v1")
        assert "run_id" not in meta
        assert "query_trace_id" not in meta
        assert "duration_ms" not in meta

    def test_validate_envelope_valid(self):
        data = {
            "_meta": {
                "envelope": "ppt_library.envelope.v2",
                "contract": "test.v1",
                "producer_version": "1.0.0",
                "command": "test",
                "generated_at": "2026-06-23T00:00:00Z",
            }
        }
        errors = validate_envelope(data)
        assert errors == []

    def test_validate_envelope_missing_meta(self):
        errors = validate_envelope({"data": "no meta"})
        assert len(errors) == 1
        assert "missing _meta" in errors[0].message

    def test_validate_envelope_missing_fields(self):
        data = {"_meta": {"envelope": "ppt_library.envelope.v2"}}
        errors = validate_envelope(data)
        assert len(errors) > 0
        missing_fields = {e.details.get("field") for e in errors}
        assert "contract" in missing_fields
        assert "producer_version" in missing_fields


# ---------------------------------------------------------------------------
# Error records
# ---------------------------------------------------------------------------


class TestErrorRecords:
    def test_error_to_json(self):
        err = error("TEST_CODE", "test message", source_module="test", details={"key": "value"})
        j = err.to_json()
        assert j["code"] == "TEST_CODE"
        assert j["message"] == "test message"
        assert j["severity"] == "error"
        assert j["details"] == {"key": "value"}

    def test_warning_to_json(self):
        w = warning("WARN_CODE", "warning message")
        j = w.to_json()
        assert j["code"] == "WARN_CODE"
        assert j["severity"] == "warning"

    def test_contract_error_frozen(self):
        err = ContractError(code="X", message="y")
        with pytest.raises(AttributeError):
            err.code = "Z"  # type: ignore[misc]
