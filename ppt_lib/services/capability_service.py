"""Runtime capability detection for PPT Library.

Capabilities are derived from the actual running environment, never
hard-coded.  Provider availability is probed lazily — the service does
not call out to external services unless explicitly asked via
``probe_providers=True``.
"""

from __future__ import annotations

import importlib.util
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any

from ppt_lib.contracts.registry import get_registry
from ppt_lib.settings import Settings


def _producer_version() -> str:
    try:
        return metadata.version("ppt-library")
    except metadata.PackageNotFoundError:
        return "0+unknown"


@dataclass(frozen=True)
class ProviderStatus:
    """Runtime status of a single provider (embedding / vision / OCR)."""

    name: str
    available: bool
    configured: bool
    model: str | None = None
    endpoint: str | None = None
    reason: str | None = None

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {
            "name": self.name,
            "available": self.available,
            "configured": self.configured,
        }
        if self.model:
            d["model"] = self.model
        if self.endpoint:
            d["endpoint"] = self.endpoint
        if self.reason:
            d["reason"] = self.reason
        return d


@dataclass(frozen=True)
class CapabilityReport:
    """Full capability report for the current environment."""

    contract: str = "ppt_library.capabilities.v1"
    producer_version: str = ""
    db_schema_version: int = 0
    modes: list[str] = field(default_factory=lambda: ["local"])
    features: dict[str, object] = field(default_factory=dict)
    contracts: list[str] = field(default_factory=list)
    providers: dict[str, list[ProviderStatus]] = field(default_factory=dict)
    storage: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[dict[str, object]] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "contract": self.contract,
            "producer_version": self.producer_version,
            "db_schema_version": self.db_schema_version,
            "modes": self.modes,
            "features": self.features,
            "contracts": self.contracts,
            "providers": {
                category: [p.to_json() for p in providers]
                for category, providers in self.providers.items()
            },
            "storage": self.storage,
            "warnings": self.warnings,
        }


def detect_capabilities(
    settings: Settings,
    *,
    probe_providers: bool = False,
) -> CapabilityReport:
    """Build a capability report from the current environment.

    When *probe_providers* is False (default), availability is inferred
    from configuration only.  When True, a lightweight health probe is
    sent to each configured endpoint.
    """
    from ppt_lib.db import SCHEMA_VERSION

    registry = get_registry()

    # --- Providers ---
    embedding_providers = _detect_embedding_providers(settings, probe=probe_providers)
    vision_providers = _detect_vision_providers(settings, probe=probe_providers)

    # --- Features ---
    soffice = shutil.which("soffice") is not None
    features: dict[str, object] = {
        "screenshots": soffice,
        "ocr_paddleocr": _paddleocr_available(),
        "workbench": _workbench_available(),
        "server_mode": False,  # v1.9 — not yet deployed
        "ann_search": False,  # v1.6 — SqliteScanBackend (no dedicated ANN index yet)
        "fts5_search": True,  # canonical name
        "ft5_search": True,  # compatibility alias retained for v2.0 clients
        "selection.deck_master_v1": True,
        "asset_identity": True,  # v1.5-D — stable identity + schema v5
        "job_engine": True,  # v1.5-E — job state machine + stages
        "incremental_governance": True,  # v1.5-F — affected-scope governance
    }

    # --- Contracts ---
    contract_names = [_wire_contract_name(c.schema, c.name) for c in registry.list_contracts()]

    # --- Storage ---
    storage: dict[str, list[str]] = {
        "metadata": ["sqlite"],
        "screenshots": ["local_filesystem"],
        "embeddings": ["sqlite"],
        "staging": ["local_filesystem"],
    }

    # --- Warnings ---
    warnings: list[dict[str, object]] = []
    if not soffice:
        warnings.append({
            "code": "SCREENSHOTS_UNAVAILABLE",
            "message": "LibreOffice (soffice) not found; screenshot-based features are disabled.",
        })
    if not any(p.available for p in embedding_providers):
        warnings.append({
            "code": "NO_EMBEDDING_PROVIDER",
            "message": "No embedding provider is available; semantic search is disabled.",
        })
    if not any(p.available for p in vision_providers):
        warnings.append({
            "code": "NO_VISION_PROVIDER",
            "message": "No vision/OCR provider is available; visual understanding is disabled.",
        })

    return CapabilityReport(
        producer_version=_producer_version(),
        db_schema_version=SCHEMA_VERSION,
        features=features,
        contracts=contract_names,
        providers={
            "embedding": embedding_providers,
            "vision": vision_providers,
        },
        storage=storage,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Provider detection helpers
# ---------------------------------------------------------------------------


def _detect_embedding_providers(settings: Settings, *, probe: bool) -> list[ProviderStatus]:
    providers: list[ProviderStatus] = []

    # OpenAI-compatible (includes LM Studio, Ollama)
    api_key = settings.embedding_api_key or settings.openai_api_key
    openai_selected = settings.embedding_provider == "openai"
    configured = openai_selected and (api_key is not None or settings.embedding_api_url is not None)
    endpoint = settings.embedding_api_url or ("https://api.openai.com/v1" if openai_selected else None)
    available, reason = _provider_availability(
        configured=configured,
        probe=probe,
        endpoint=_endpoint_url(endpoint, "/models"),
        api_key=api_key,
        unavailable_reason="No API key or endpoint configured",
    )
    providers.append(ProviderStatus(
        name="openai_compatible",
        available=available,
        configured=openai_selected,
        model=settings.embedding_model,
        endpoint=endpoint,
        reason=reason,
    ))

    # LM Studio
    lm_configured = settings.embedding_provider == "lmstudio"
    lm_available, lm_reason = _provider_availability(
        configured=lm_configured,
        probe=probe,
        endpoint=_endpoint_url(settings.lmstudio_base_url, "/models"),
        unavailable_reason="Provider not selected",
    )
    providers.append(ProviderStatus(
        name="lmstudio",
        available=lm_available,
        configured=lm_configured,
        model=settings.lmstudio_embedding_model if lm_configured else None,
        endpoint=settings.lmstudio_base_url if lm_configured else None,
        reason=lm_reason,
    ))

    return providers


def _detect_vision_providers(settings: Settings, *, probe: bool) -> list[ProviderStatus]:
    providers: list[ProviderStatus] = []

    # Auto / cloud vision
    vp = settings.vision_provider
    cloud_configured = vp in ("auto", "openai") and (
        settings.vision_api_key is not None or settings.openai_api_key is not None
    )
    cloud_api_key = settings.vision_api_key or settings.openai_api_key
    cloud_available, cloud_reason = _provider_availability(
        configured=cloud_configured,
        probe=probe,
        endpoint=_endpoint_url(settings.cloud_vision_base_url, "/models"),
        api_key=cloud_api_key,
        unavailable_reason="No vision API key configured",
    )
    providers.append(ProviderStatus(
        name="cloud_vision",
        available=cloud_available,
        configured=vp in ("auto", "openai"),
        model=settings.cloud_vision_model,
        endpoint=settings.cloud_vision_base_url,
        reason=cloud_reason,
    ))

    # Ollama
    ollama_configured = vp == "ollama"
    ollama_available, ollama_reason = _provider_availability(
        configured=ollama_configured,
        probe=probe,
        endpoint=_endpoint_url(settings.ollama_base_url, "/api/tags", preserve_api_prefix=True),
        unavailable_reason="Provider not selected",
    )
    providers.append(ProviderStatus(
        name="ollama",
        available=ollama_available,
        configured=ollama_configured,
        model=settings.ollama_vision_model if ollama_configured else None,
        endpoint=settings.ollama_base_url if ollama_configured else None,
        reason=ollama_reason,
    ))

    # LM Studio vision
    lm_vision_configured = vp == "lmstudio" and bool(settings.lmstudio_vision_model)
    lm_vision_available, lm_vision_reason = _provider_availability(
        configured=lm_vision_configured,
        probe=probe,
        endpoint=_endpoint_url(settings.lmstudio_base_url, "/models"),
        unavailable_reason="Provider not selected or vision model is empty",
    )
    providers.append(ProviderStatus(
        name="lmstudio_vision",
        available=lm_vision_available,
        configured=vp == "lmstudio",
        model=settings.lmstudio_vision_model if vp == "lmstudio" else None,
        endpoint=settings.lmstudio_base_url if vp == "lmstudio" else None,
        reason=lm_vision_reason,
    ))

    # PaddleOCR MCP
    paddle_installed = _paddleocr_available()
    paddle_configured = vp == "paddleocr-mcp"
    paddle_ready = paddle_configured and (paddle_installed or bool(settings.paddleocr_mcp_base_url))
    paddle_available, paddle_reason = _provider_availability(
        configured=paddle_ready,
        probe=probe and bool(settings.paddleocr_mcp_base_url),
        endpoint=settings.paddleocr_mcp_base_url,
        api_key=settings.paddleocr_mcp_access_token,
        unavailable_reason="paddleocr-mcp not installed and no endpoint configured",
    )
    providers.append(ProviderStatus(
        name="paddleocr_mcp",
        available=paddle_available,
        configured=paddle_configured,
        endpoint=settings.paddleocr_mcp_base_url if paddle_configured else None,
        reason=paddle_reason,
    ))

    # MMX
    mmx_cmd = shutil.which(settings.mmx_command) is not None
    mmx_configured = vp == "mmx" and mmx_cmd
    providers.append(ProviderStatus(
        name="mmx",
        available=mmx_configured,
        configured=vp == "mmx",
        reason=None if mmx_configured else f"'{settings.mmx_command}' not found in PATH",
    ))

    return providers


def _provider_availability(
    *,
    configured: bool,
    probe: bool,
    endpoint: str | None,
    unavailable_reason: str,
    api_key: str | None = None,
) -> tuple[bool, str | None]:
    if not configured:
        return False, unavailable_reason
    if not probe:
        return True, "Configured; live probe not requested"
    if not endpoint:
        return False, "No probe endpoint configured"
    return _probe_endpoint(endpoint, api_key=api_key)


def _probe_endpoint(url: str, *, api_key: str | None = None, timeout_seconds: float = 2.0) -> tuple[bool, str | None]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        return False, f"Probe failed with HTTP {exc.code}"
    except (TimeoutError, OSError, urllib.error.URLError) as exc:
        reason = getattr(exc, "reason", exc)
        return False, f"Probe failed: {reason}"
    if 200 <= status < 300:
        return True, None
    return False, f"Probe failed with HTTP {status}"


def _endpoint_url(base_url: str | None, suffix: str, *, preserve_api_prefix: bool = False) -> str | None:
    if not base_url:
        return None
    base = base_url.rstrip("/")
    if preserve_api_prefix:
        return f"{base}{suffix}"
    if base.endswith("/v1") and suffix.startswith("/"):
        return f"{base}{suffix}"
    return f"{base}{suffix}"


def _wire_contract_name(schema: dict[str, Any], fallback: str) -> str:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return fallback
    for key in ("contract", "schema_version"):
        field = properties.get(key)
        if isinstance(field, dict) and isinstance(field.get("const"), str):
            return str(field["const"])
    meta = properties.get("_meta")
    if isinstance(meta, dict):
        meta_properties = meta.get("properties")
        if isinstance(meta_properties, dict):
            contract = meta_properties.get("contract")
            if isinstance(contract, dict) and isinstance(contract.get("const"), str):
                return str(contract["const"])
    return fallback


def _workbench_available() -> bool:
    return importlib.util.find_spec("fastapi") is not None and importlib.util.find_spec("uvicorn") is not None


def _paddleocr_available() -> bool:
    try:
        import paddleocr_mcp  # noqa: F401
        return True
    except ImportError:
        return False
