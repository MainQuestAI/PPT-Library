from __future__ import annotations

from pathlib import Path

from ppt_lib.model_compat import ProbeResult
from ppt_lib.models_test import _test_embedding
from ppt_lib.settings import Settings


def test_embedding_probe_uses_unified_openai_compatible_endpoint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_probe_embedding(base_url, model, dimensions, *, timeout, api_key=None):
        captured.update({
            "base_url": base_url,
            "model": model,
            "dimensions": dimensions,
            "timeout": timeout,
            "api_key": api_key,
        })
        return ProbeResult(
            capability="embedding",
            status="ok",
            message="ok",
            details={"dimensions": dimensions},
        )

    monkeypatch.setattr("ppt_lib.models_test.probe_embedding", fake_probe_embedding)
    settings = Settings(
        home_dir=Path("/tmp/ppt-lib-test"),
        embedding_provider="openai",
        embedding_api_url="http://127.0.0.1:8888/v1",
        embedding_api_key="local-key",
        embedding_model="custom-embedding",
        embedding_dimensions=768,
    )

    result = _test_embedding(settings)

    assert result["status"] == "ok"
    assert result["model"] == "custom-embedding"
    assert result["details"]["api_url"] == "http://127.0.0.1:8888/v1"
    assert captured == {
        "base_url": "http://127.0.0.1:8888/v1",
        "model": "custom-embedding",
        "dimensions": 768,
        "timeout": 30.0,
        "api_key": "local-key",
    }


def test_embedding_probe_requires_key_only_for_public_openai_endpoint() -> None:
    settings = Settings(
        home_dir=Path("/tmp/ppt-lib-test"),
        embedding_provider="openai",
        embedding_api_url="https://api.openai.com/v1",
        embedding_model="text-embedding-3-small",
    )

    result = _test_embedding(settings)

    assert result["status"] == "error"
    assert result["message"] == "Embedding API key missing"
