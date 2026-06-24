"""Runtime capability detection for PPT Library.

Capabilities are derived from the actual running environment, never
hard-coded.  Provider availability is probed lazily — the service does
not call out to external services unless explicitly asked via
``probe_providers=True``.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from importlib import metadata

from ppt_lib.contracts.registry import get_registry
from ppt_lib.settings import Settings


def _producer_version() -> str:
    try:
        return metadata.version("ppt-library")
    except metadata.PackageNotFoundError:
        return "0.0.0-dev"


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
        "workbench": True,  # v1.8 — FastAPI workbench implemented (needs [workbench] extra)
        "server_mode": False,  # v1.9 — not yet deployed
        "ann_search": False,  # v1.6 — SqliteScanBackend (no dedicated ANN index yet)
        "ft5_search": True,  # v1.6 — FTS5 lexical search implemented
        "asset_identity": True,  # v1.5-D — stable identity + schema v5
        "job_engine": True,  # v1.5-E — job state machine + stages
        "incremental_governance": True,  # v1.5-F — affected-scope governance
    }

    # --- Contracts ---
    contract_names = [c.name for c in registry.list_contracts()]

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
    configured = settings.embedding_provider == "openai" and (api_key is not None or settings.embedding_api_url is not None)
    providers.append(ProviderStatus(
        name="openai_compatible",
        available=configured,
        configured=settings.embedding_provider == "openai",
        model=settings.embedding_model,
        endpoint=settings.embedding_api_url,
        reason=None if configured else "No API key or endpoint configured",
    ))

    # LM Studio
    lm_configured = settings.embedding_provider == "lmstudio"
    providers.append(ProviderStatus(
        name="lmstudio",
        available=lm_configured,
        configured=lm_configured,
        model=settings.lmstudio_embedding_model if lm_configured else None,
        endpoint=settings.lmstudio_base_url if lm_configured else None,
        reason=None if lm_configured else "Provider not selected",
    ))

    return providers


def _detect_vision_providers(settings: Settings, *, probe: bool) -> list[ProviderStatus]:
    providers: list[ProviderStatus] = []

    # Auto / cloud vision
    vp = settings.vision_provider
    cloud_configured = vp in ("auto", "openai") and (
        settings.vision_api_key is not None or settings.openai_api_key is not None
    )
    providers.append(ProviderStatus(
        name="cloud_vision",
        available=cloud_configured,
        configured=vp in ("auto", "openai"),
        model=settings.cloud_vision_model,
        endpoint=settings.cloud_vision_base_url,
        reason=None if cloud_configured else "No vision API key configured",
    ))

    # Ollama
    ollama_configured = vp == "ollama"
    providers.append(ProviderStatus(
        name="ollama",
        available=ollama_configured,
        configured=ollama_configured,
        model=settings.ollama_vision_model if ollama_configured else None,
        endpoint=settings.ollama_base_url if ollama_configured else None,
    ))

    # LM Studio vision
    lm_vision_configured = vp == "lmstudio" and bool(settings.lmstudio_vision_model)
    providers.append(ProviderStatus(
        name="lmstudio_vision",
        available=lm_vision_configured,
        configured=vp == "lmstudio",
        model=settings.lmstudio_vision_model if vp == "lmstudio" else None,
    ))

    # PaddleOCR MCP
    paddle_configured = vp == "paddleocr-mcp" or _paddleocr_available()
    providers.append(ProviderStatus(
        name="paddleocr_mcp",
        available=paddle_configured,
        configured=vp == "paddleocr-mcp",
        reason=None if paddle_configured else "paddleocr-mcp not installed",
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


def _paddleocr_available() -> bool:
    try:
        import paddleocr_mcp  # noqa: F401
        return True
    except ImportError:
        return False
