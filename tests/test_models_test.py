from __future__ import annotations

from pathlib import Path

from ppt_lib.model_compat import ProbeResult
from ppt_lib.models_test import _test_chat, _test_embedding, _test_json_schema, run_models_test
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


def test_cloud_vision_does_not_probe_lmstudio_chat_without_key(tmp_path: Path) -> None:
    settings = Settings(
        home_dir=tmp_path,
        vision_provider="cloud",
        cloud_vision_model="gpt-4o-mini",
        lmstudio_vision_model="google/gemma-4-26b-a4b-qat",
    )

    chat_result = _test_chat(settings)
    json_schema_result = _test_json_schema(settings)

    assert chat_result["provider"] == "cloud"
    assert chat_result["status"] == "skipped"
    assert json_schema_result["provider"] == "cloud"
    assert json_schema_result["status"] == "skipped"


def test_cloud_models_test_only_blocks_on_missing_cloud_vision_key(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        home_dir=tmp_path,
        embedding_provider="lmstudio",
        embedding_api_url="http://127.0.0.1:1234/v1",
        embedding_model="text-embedding-nomic-embed-text-v1.5",
        embedding_dimensions=768,
        vision_provider="cloud",
        cloud_vision_model="gpt-4o-mini",
        lmstudio_vision_model="google/gemma-4-26b-a4b-qat",
    )

    monkeypatch.setattr(
        "ppt_lib.models_test._test_embedding",
        lambda settings: {
            "capability": "embedding",
            "provider": "lmstudio",
            "model": "text-embedding-nomic-embed-text-v1.5",
            "status": "ok",
            "message": "ok",
            "details": {"dimensions": 768},
        },
    )
    monkeypatch.setattr("ppt_lib.models_test._update_cache", lambda settings, results: None)

    result = run_models_test(settings)

    assert result["summary"]["error"] == 1
    assert [probe["capability"] for probe in result["probes"] if probe["status"] == "error"] == ["vision"]


def test_mmx_models_test_uses_mmx_vision_probe(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        home_dir=tmp_path,
        embedding_provider="lmstudio",
        embedding_api_url="http://127.0.0.1:1234/v1",
        embedding_model="text-embedding-nomic-embed-text-v1.5",
        embedding_dimensions=768,
        vision_provider="mmx",
        mmx_vision_model="default",
    )

    monkeypatch.setattr(
        "ppt_lib.models_test._test_embedding",
        lambda settings: {
            "capability": "embedding",
            "provider": "lmstudio",
            "model": "text-embedding-nomic-embed-text-v1.5",
            "status": "ok",
            "message": "ok",
            "details": {"dimensions": 768},
        },
    )
    monkeypatch.setattr(
        "ppt_lib.models_test.probe_mmx",
        lambda command="mmx", timeout=30.0: ("ok", "mmx auth and quota probe passed", {"command": command}),
    )
    monkeypatch.setattr("ppt_lib.models_test._update_cache", lambda settings, results: None)

    result = run_models_test(settings)

    assert result["summary"]["status"] == "ok"
    probes = {probe["capability"]: probe for probe in result["probes"]}
    assert probes["chat"]["provider"] == "mmx"
    assert probes["chat"]["status"] == "skipped"
    assert probes["vision"]["provider"] == "mmx"
    assert probes["vision"]["status"] == "ok"
    assert probes["json_schema"]["provider"] == "mmx"
    assert probes["json_schema"]["status"] == "skipped"
