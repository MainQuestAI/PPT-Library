from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

from ppt_lib.settings import Settings


def detect_openai_key(settings: Settings) -> bool:
    """Detect if an OpenAI API key is available (from env var or config).

    Returns:
        True if a non-empty openai_api_key is present on the Settings object.
    """
    return bool(settings.openai_api_key)


def detect_lmstudio(base_url: str = "http://127.0.0.1:1234/v1", timeout: float = 2.0) -> bool:
    """Detect whether LM Studio is running.

    Sends a GET to the /v1/models endpoint and returns True if the endpoint
    responds within the timeout.

    Args:
        base_url: LM Studio server base URL.
        timeout: Request timeout in seconds.

    Returns:
        True if the endpoint responds successfully.
    """
    url = f"{base_url.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def detect_ollama(base_url: str = "http://127.0.0.1:11434", timeout: float = 2.0) -> bool:
    """Detect whether Ollama is running.

    Sends a GET to the /api/tags endpoint and returns True if the endpoint
    responds within the timeout.

    Args:
        base_url: Ollama server base URL.
        timeout: Request timeout in seconds.

    Returns:
        True if the endpoint responds successfully.
    """
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def detect_environment(settings: Settings) -> dict[str, Any]:
    """Detect available model configurations in the local environment.

    Detection priority: OpenAI API key > LM Studio > Ollama.
    Stops at the first available provider.

    Returns:
        A dict with keys:
        - provider: "openai" | "lmstudio" | "ollama" | None
        - model: detected model name or None
        - base_url: detected base URL or None
        - api_key_available: whether an API key is configured
        - details: human-readable status description
    """
    openai_available = detect_openai_key(settings)
    if openai_available:
        return {
            "provider": "openai",
            "model": settings.embedding_model,
            "base_url": None,
            "api_key_available": True,
            "details": "OpenAI API key detected.",
        }

    lmstudio_available = detect_lmstudio(
        base_url=settings.lmstudio_base_url,
        timeout=2.0,
    )
    if lmstudio_available:
        return {
            "provider": "lmstudio",
            "model": settings.lmstudio_embedding_model,
            "base_url": settings.lmstudio_base_url,
            "api_key_available": False,
            "details": f"LM Studio running at {settings.lmstudio_base_url}.",
        }

    ollama_available = detect_ollama(
        base_url=settings.ollama_base_url,
        timeout=2.0,
    )
    if ollama_available:
        return {
            "provider": "ollama",
            "model": settings.ollama_vision_model,
            "base_url": settings.ollama_base_url,
            "api_key_available": False,
            "details": f"Ollama running at {settings.ollama_base_url}.",
        }

    return {
        "provider": None,
        "model": None,
        "base_url": None,
        "api_key_available": False,
        "details": (
            "No supported provider detected. "
            "Options: 1) Set PPT_LIB_OPENAI_API_KEY, "
            "2) Start LM Studio (http://127.0.0.1:1234), "
            "3) Start Ollama (http://127.0.0.1:11434)."
        ),
    }


def recommend_setup(env: dict[str, Any]) -> tuple[str, str, dict[str, object]]:
    """Recommend a setup mode and configuration based on environment detection.

    Args:
        env: Output from detect_environment().

    Returns:
        A tuple of (mode_name, human_readable_message, config_overrides).
        mode_name maps to SETUP_MODE_CONFIGS keys ("openai", "lmstudio")
        or "needs_config" when no supported provider is available.
    """
    provider = env.get("provider")

    if provider == "openai":
        return (
            "openai",
            "OpenAI API key detected. Using cloud embedding; vision calls are disabled for first indexing.",
            {
                "embedding_api_url": "https://api.openai.com/v1",
                "embedding_model": "text-embedding-3-small",
                "embedding_dimensions": 1536,
                "vision_max_slides_per_file": 0,
            },
        )

    if provider == "lmstudio":
        return (
            "lmstudio",
            "LM Studio detected. Using local embedding; vision calls are disabled for first indexing.",
            {
                "embedding_api_url": "http://127.0.0.1:1234/v1",
                "embedding_model": "text-embedding-nomic-embed-text-v1.5",
                "embedding_dimensions": 768,
                "vision_max_slides_per_file": 0,
            },
        )

    if provider == "ollama":
        return (
            "needs_config",
            "Ollama detected — use `--mode openai` with embedding_api_url=http://127.0.0.1:11434/v1",
            {},
        )

    return (
        "needs_config",
        "No supported provider detected. "
        "Options: 1) Set PPT_LIB_OPENAI_API_KEY, "
        "2) Start LM Studio, "
        "3) Start Ollama, "
        "or use --mode to configure manually.",
        {},
    )
