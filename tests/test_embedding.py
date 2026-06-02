from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from ppt_lib.config import load_settings
from ppt_lib.embedding import (
    EmbeddingDimensionError,
    EmbeddingProviderError,
    FakeEmbeddingProvider,
    UnifiedEmbeddingProvider,
    build_embedding_provider,
)


def _unified(**kw: Any) -> UnifiedEmbeddingProvider:
    kwargs: dict[str, Any] = {"api_url": "http://test/v1", "model": "m", "dimensions": 3}
    kwargs.update(kw)
    return UnifiedEmbeddingProvider(**kwargs)


def test_build_openai_provider_from_settings(tmp_path) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "openai_api_key": "sk-test"},
        config_path=tmp_path / "config.yml",
    )
    provider = build_embedding_provider(settings)
    assert isinstance(provider, UnifiedEmbeddingProvider)
    assert provider.model == "text-embedding-3-small"
    assert provider.dimensions == 1536


def test_build_lmstudio_provider_from_settings(tmp_path) -> None:
    settings = load_settings(
        {
            "home_dir": tmp_path,
            "embedding_provider": "lmstudio",
            "embedding_dimensions": 768,
        },
        config_path=tmp_path / "config.yml",
    )
    provider = build_embedding_provider(settings)
    assert isinstance(provider, UnifiedEmbeddingProvider)
    assert provider.model == "text-embedding-nomic-embed-text-v1.5"
    assert provider.dimensions == 768
    assert provider.endpoint == "http://127.0.0.1:1234/v1/embeddings"


def test_build_with_unified_fields(tmp_path) -> None:
    settings = load_settings(
        {
            "home_dir": tmp_path,
            "embedding_api_url": "http://custom:8888/v1",
            "embedding_model": "custom-model",
            "embedding_dimensions": 512,
        },
        config_path=tmp_path / "config.yml",
    )
    provider = build_embedding_provider(settings)
    assert isinstance(provider, UnifiedEmbeddingProvider)
    assert provider.model == "custom-model"
    assert provider.dimensions == 512
    assert provider.endpoint == "http://custom:8888/v1/embeddings"


def test_missing_openai_key_falls_back_to_unified(tmp_path) -> None:
    """Without an API key, the unified provider still builds (error surfaces at request time)."""
    settings = load_settings(
        {"home_dir": tmp_path, "embedding_provider": "openai", "openai_api_key": None},
        config_path=tmp_path / "config.yml",
    )
    provider = build_embedding_provider(settings)
    assert isinstance(provider, UnifiedEmbeddingProvider)
    assert provider.api_key is None


def test_fake_provider_returns_deterministic_float32_vector() -> None:
    provider = FakeEmbeddingProvider(dimensions=8)
    first = provider.encode("warehouse process")
    second = provider.encode("warehouse process")
    assert first.shape == (8,)
    assert first.dtype == np.float32
    np.testing.assert_array_equal(first, second)


def test_unified_provider_retries_timeout_then_success() -> None:
    calls: list[str] = []

    def transport(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        calls.append(payload["input"])
        if len(calls) == 1:
            raise TimeoutError("slow")
        return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    provider = _unified(api_key="sk-test", transport=transport, sleep=lambda _: None)
    vector = provider.encode("query")
    assert len(calls) == 2
    np.testing.assert_allclose(vector, np.array([0.1, 0.2, 0.3], dtype=np.float32))


def test_unified_provider_retries_rate_limit_then_success() -> None:
    calls = 0

    def transport(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise EmbeddingProviderError("limited", code="EMBEDDING_RATE_LIMIT", retryable=True)
        return {"data": [{"embedding": [1.0, 0.0]}]}

    provider = UnifiedEmbeddingProvider(
        api_url="http://test/v1",
        model="m",
        dimensions=2,
        api_key="sk-test",
        transport=transport,
        sleep=lambda _: None,
    )
    vector = provider.encode("query")
    assert calls == 3
    assert vector.tolist() == [1.0, 0.0]


def test_unified_provider_sends_auth_header_when_key_provided() -> None:
    captured: dict[str, Any] = {}

    def transport(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        captured["payload"] = payload
        captured["api_key"] = api_key
        return {"data": [{"embedding": [0.25, 0.5]}]}

    provider = UnifiedEmbeddingProvider(
        api_url="http://127.0.0.1:1234/v1/",
        model="local-embedding",
        dimensions=2,
        timeout_seconds=7,
        transport=transport,
        sleep=lambda _: None,
    )
    vector = provider.encode("  local query  ")
    assert provider.endpoint == "http://127.0.0.1:1234/v1/embeddings"
    assert captured["payload"] == {"model": "local-embedding", "input": "local query"}
    assert captured["api_key"] == ""
    assert provider.timeout_seconds == 7
    np.testing.assert_allclose(vector, np.array([0.25, 0.5], dtype=np.float32))


def test_unified_provider_does_not_retry_non_retryable_error() -> None:
    calls = 0

    def transport(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise EmbeddingProviderError("bad request", code="EMBEDDING_BAD_REQUEST", retryable=False)

    provider = _unified(api_key="sk-test", transport=transport, sleep=lambda _: None)
    with pytest.raises(EmbeddingProviderError):
        provider.encode("query")
    assert calls == 1


def test_dimension_mismatch_raises() -> None:
    provider = _unified(
        api_key="sk-test",
        transport=lambda payload, api_key: {"data": [{"embedding": [1.0, 2.0]}]},
        sleep=lambda _: None,
    )
    with pytest.raises(EmbeddingDimensionError):
        provider.encode("query")


def test_empty_text_policy_is_stable() -> None:
    provider = FakeEmbeddingProvider(dimensions=4)
    empty = provider.encode("")
    whitespace = provider.encode("   ")
    np.testing.assert_array_equal(empty, whitespace)
