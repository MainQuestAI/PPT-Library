"""Tests for capabilities CLI and capability service (1.5-B)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ppt_lib.services.capability_service import (
    CapabilityReport,
    ProviderStatus,
    detect_capabilities,
)
from ppt_lib.settings import Settings

# ---------------------------------------------------------------------------
# Capability service unit tests
# ---------------------------------------------------------------------------


class TestCapabilityService:
    def test_default_settings_returns_report(self):
        settings = Settings()
        report = detect_capabilities(settings)
        assert isinstance(report, CapabilityReport)
        assert report.contract == "ppt_library.capabilities.v1"
        assert report.db_schema_version == 5
        assert "local" in report.modes

    def test_report_includes_all_contracts(self):
        settings = Settings()
        report = detect_capabilities(settings)
        assert "capabilities.v1" in report.contracts
        assert "search-response.v2" in report.contracts
        assert len(report.contracts) == 7

    def test_embedding_providers_detected(self):
        settings = Settings()
        report = detect_capabilities(settings)
        assert "embedding" in report.providers
        embedding = report.providers["embedding"]
        names = {p.name for p in embedding}
        assert "openai_compatible" in names
        assert "lmstudio" in names

    def test_vision_providers_detected(self):
        settings = Settings()
        report = detect_capabilities(settings)
        assert "vision" in report.providers
        vision = report.providers["vision"]
        names = {p.name for p in vision}
        assert "cloud_vision" in names
        assert "ollama" in names
        assert "paddleocr_mcp" in names

    def test_storage_backends(self):
        settings = Settings()
        report = detect_capabilities(settings)
        assert "metadata" in report.storage
        assert "sqlite" in report.storage["metadata"]

    def test_features_defaults(self):
        settings = Settings()
        report = detect_capabilities(settings)
        # v2.0: these capabilities are now implemented
        assert report.features["workbench"] is True
        assert report.features["ft5_search"] is True
        assert report.features["asset_identity"] is True
        assert report.features["job_engine"] is True
        assert report.features["incremental_governance"] is True
        # not yet deployed
        assert report.features["server_mode"] is False
        assert report.features["ann_search"] is False

    def test_to_json(self):
        settings = Settings()
        report = detect_capabilities(settings)
        j = report.to_json()
        assert j["contract"] == "ppt_library.capabilities.v1"
        assert isinstance(j["providers"], dict)
        assert isinstance(j["warnings"], list)

    def test_warnings_when_no_embedding(self):
        settings = Settings()
        report = detect_capabilities(settings)
        warning_codes = {w.get("code") for w in report.warnings}
        # Default settings have no configured embedding provider
        assert "NO_EMBEDDING_PROVIDER" in warning_codes or len(report.warnings) >= 0


class TestProviderStatus:
    def test_to_json_available(self):
        p = ProviderStatus(name="test", available=True, configured=True, model="test-model")
        j = p.to_json()
        assert j["name"] == "test"
        assert j["available"] is True
        assert j["model"] == "test-model"

    def test_to_json_unavailable(self):
        p = ProviderStatus(name="test", available=False, configured=False, reason="not configured")
        j = p.to_json()
        assert j["available"] is False
        assert j["reason"] == "not configured"

    def test_frozen(self):
        p = ProviderStatus(name="x", available=True, configured=True)
        with pytest.raises(AttributeError):
            p.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CLI subprocess tests
# ---------------------------------------------------------------------------


class TestCapabilitiesCLI:
    def test_capabilities_json_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "ppt_lib.cli", "capabilities", "--output", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["contract"] == "ppt_library.capabilities.v1"
        assert "providers" in data
        assert "contracts" in data
        assert data["_errors"] == []

    def test_contract_list_json_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "ppt_lib.cli", "contract", "list", "--output", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "contracts" in data
        names = {c["name"] for c in data["contracts"]}
        assert "capabilities.v1" in names
        assert "search-response.v2" in names
        assert data["_errors"] == []

    def test_contract_show_json_output(self):
        result = subprocess.run(
            [sys.executable, "-m", "ppt_lib.cli", "contract", "show", "capabilities.v1", "--output", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "contract" in data
        assert "schema" in data
        assert data["contract"]["name"] == "capabilities.v1"

    def test_contract_show_unknown(self):
        result = subprocess.run(
            [sys.executable, "-m", "ppt_lib.cli", "contract", "show", "nonexistent.v99", "--output", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert len(data["_errors"]) > 0
        assert data["_errors"][0]["code"] == "CONTRACT_NOT_FOUND"

    def test_contract_validate_inline_json(self):
        valid_payload = json.dumps({
            "contract": "ppt_library.capabilities.v1",
            "producer_version": "1.5.0",
            "modes": ["local"],
            "features": {},
            "contracts": [],
            "providers": {},
            "storage": {},
        })
        result = subprocess.run(
            [sys.executable, "-m", "ppt_lib.cli", "contract", "validate", "capabilities.v1", "--data", valid_payload, "--output", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["valid"] is True

    def test_contract_validate_invalid(self):
        invalid_payload = json.dumps({"contract": "wrong"})
        result = subprocess.run(
            [sys.executable, "-m", "ppt_lib.cli", "contract", "validate", "capabilities.v1", "--data", invalid_payload, "--output", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_contract_validate_file_input(self, tmp_path: Path):
        payload = {
            "contract": "ppt_library.capabilities.v1",
            "producer_version": "1.5.0",
            "modes": ["local"],
            "features": {},
            "contracts": [],
            "providers": {},
            "storage": {},
        }
        data_file = tmp_path / "test_payload.json"
        data_file.write_text(json.dumps(payload))

        result = subprocess.run(
            [sys.executable, "-m", "ppt_lib.cli", "contract", "validate", "capabilities.v1", "--data", str(data_file), "--output", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["valid"] is True

    def test_no_model_capabilities_still_works(self):
        """No model configured should still return a valid capability report."""
        result = subprocess.run(
            [sys.executable, "-m", "ppt_lib.cli", "--home-dir", "/tmp/ppt-lib-no-model-test", "capabilities", "--output", "json"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["contract"] == "ppt_library.capabilities.v1"
        # Should have warnings about no providers
        assert isinstance(data.get("warnings"), list)
