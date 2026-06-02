from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from ppt_lib.settings import Settings
from ppt_lib.setup_probe import (
    detect_environment,
    detect_lmstudio,
    detect_ollama,
    detect_openai_key,
    recommend_setup,
)


class _MockResponse:
    """Minimal context manager that mimics a successful urllib response."""

    def __enter__(self) -> _MockResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def mock_urlopen_success(url: str, **kwargs: object) -> _MockResponse:
    """A urllib.request.urlopen replacement that returns a successful response."""
    return _MockResponse()


def mock_urlopen_failure(url: str, **kwargs: object) -> _MockResponse:
    """A urllib.request.urlopen replacement that raises URLError."""
    raise urllib.error.URLError("Connection refused")


# ── detect_openai_key ─────────────────────────────────────────────────────


def test_detect_openai_key_found() -> None:
    """openai_api_key set on Settings -> detect_openai_key() returns True."""
    settings = Settings(openai_api_key="sk-test-12345", home_dir=Path("/tmp"))
    assert detect_openai_key(settings) is True


def test_detect_openai_key_missing() -> None:
    """openai_api_key is None -> detect_openai_key() returns False."""
    settings = Settings(openai_api_key=None, home_dir=Path("/tmp"))
    assert detect_openai_key(settings) is False


# ── detect_lmstudio ───────────────────────────────────────────────────────


def test_detect_lmstudio_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 200 from /v1/models -> detect_lmstudio() returns True."""
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_success)
    assert detect_lmstudio() is True


def test_detect_lmstudio_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connection refused -> detect_lmstudio() returns False."""
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_failure)
    assert detect_lmstudio() is False


# ── detect_ollama ─────────────────────────────────────────────────────────


def test_detect_ollama_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 200 from /api/tags -> detect_ollama() returns True."""
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_success)
    assert detect_ollama() is True


def test_detect_ollama_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connection refused -> detect_ollama() returns False."""
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen_failure)
    assert detect_ollama() is False


# ── recommend_setup ───────────────────────────────────────────────────────


def test_recommend_setup_openai() -> None:
    """Provider openai -> recommend 'openai' mode with matching overrides."""
    env = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "base_url": None,
        "api_key_available": True,
        "details": "OpenAI API key detected.",
    }
    mode, message, overrides = recommend_setup(env)

    assert mode == "openai"
    assert "openai" in message.lower()
    assert overrides["embedding_api_url"] == "https://api.openai.com/v1"
    assert overrides["vision_max_slides_per_file"] == 0


def test_recommend_setup_lmstudio() -> None:
    """Provider lmstudio -> recommend 'lmstudio' mode with local embedding."""
    env = {
        "provider": "lmstudio",
        "model": "text-embedding-nomic-embed-text-v1.5",
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key_available": False,
        "details": "LM Studio running.",
    }
    mode, message, overrides = recommend_setup(env)

    assert mode == "lmstudio"
    assert "lm studio" in message.lower()
    assert overrides["embedding_api_url"] == "http://127.0.0.1:1234/v1"
    assert overrides["vision_max_slides_per_file"] == 0


def test_recommend_setup_none() -> None:
    """Provider None -> recommend 'needs_config' with empty overrides."""
    env = {
        "provider": None,
        "model": None,
        "base_url": None,
        "api_key_available": False,
        "details": "No supported provider detected.",
    }
    mode, message, overrides = recommend_setup(env)

    assert mode == "needs_config"
    assert overrides == {}


# ── detect_environment priority ───────────────────────────────────────────


def test_detect_environment_priority(tmp_path: Path) -> None:
    """OpenAI key available -> detect_environment returns openai (highest priority)."""
    from ppt_lib.config import load_settings

    settings = load_settings({"home_dir": tmp_path, "openai_api_key": "sk-priority-test"})
    env = detect_environment(settings)

    assert env["provider"] == "openai"
    assert env["api_key_available"] is True
