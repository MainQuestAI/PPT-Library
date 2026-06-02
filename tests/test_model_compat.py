"""Tests for ppt_lib.model_compat — shared response extraction, probes, and cache."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppt_lib.model_compat import (
    ProbeResult,
    detect_lmstudio_chat_model,
    extract_chat_text,
    load_capability_cache,
    probe_chat,
    probe_embedding,
    probe_ollama_vision,
    probe_openai_compatible_vision,
    record_probe_result,
    save_capability_cache,
)


class TestExtractChatText:
    def test_standard_content(self) -> None:
        resp = {"choices": [{"message": {"content": "hello world"}}]}
        assert extract_chat_text(resp) == "hello world"

    def test_reasoning_content_fallback(self) -> None:
        resp = {"choices": [{"message": {"content": "", "reasoning_content": "thinking out loud"}}]}
        assert extract_chat_text(resp) == "thinking out loud"

    def test_reasoning_content_only_when_content_empty(self) -> None:
        resp = {"choices": [{"message": {"content": "real answer", "reasoning_content": "thinking"}}]}
        assert extract_chat_text(resp) == "real answer"

    def test_empty_choices(self) -> None:
        assert extract_chat_text({"choices": []}) == ""

    def test_no_choices_key(self) -> None:
        assert extract_chat_text({"data": "something"}) == ""

    def test_none_content_with_reasoning(self) -> None:
        resp = {"choices": [{"message": {"content": None, "reasoning_content": "fallback"}}]}
        # content is None, not a string — should fall through to reasoning_content
        assert extract_chat_text(resp) == "fallback"

    def test_whitespace_content_no_reasoning(self) -> None:
        resp = {"choices": [{"message": {"content": "   "}}]}
        # whitespace-only content, no reasoning_content — returns the whitespace
        assert extract_chat_text(resp) == "   "

    def test_legacy_text_field(self) -> None:
        resp = {"choices": [{"text": "legacy response"}]}
        assert extract_chat_text(resp) == "legacy response"


class TestProbeEmbedding:
    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(request, timeout):
            class Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def read(self):
                    return json.dumps({"data": [{"embedding": [0.1] * 768}]}).encode()

            return Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = probe_embedding("http://localhost:1234/v1", "model", 768)
        assert result.status == "ok"
        assert result.details["dimensions"] == 768

    def test_dimension_mismatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(request, timeout):
            class Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def read(self):
                    return json.dumps({"data": [{"embedding": [0.1] * 512}]}).encode()

            return Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = probe_embedding("http://localhost:1234/v1", "model", 768)
        assert result.status == "error"
        assert "EMBEDDING_DIMENSION_MISMATCH" in str(result.details)

    def test_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(request, timeout):
            raise OSError("Connection refused")

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = probe_embedding("http://localhost:1234/v1", "model", 768)
        assert result.status == "error"
        assert "EMBEDDING_NETWORK_ERROR" in str(result.details)


class TestProbeChat:
    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(request, timeout):
            class Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def read(self):
                    return json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()

            return Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = probe_chat("http://localhost:1234/v1", "model")
        assert result.status == "ok"


class TestModelDetection:
    def test_detect_lmstudio_chat_model_skips_embedding_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(request, timeout):
            class Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def read(self):
                    return json.dumps({
                        "data": [
                            {"id": "text-embedding-qwen3-embedding-4b"},
                            {"id": "qwen/qwen3.6-27b"},
                        ]
                    }).encode()

            return Resp()

        monkeypatch.setattr("ppt_lib.model_compat.urllib.request.urlopen", fake_urlopen)

        assert detect_lmstudio_chat_model("http://localhost:1234/v1") == "qwen/qwen3.6-27b"


class TestVisionProbes:
    def test_openai_compatible_vision_sends_real_image_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen_content_types: list[str] = []

        def fake_urlopen(request, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            seen_content_types.append(payload["messages"][0]["content"][1]["type"])

            class Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def read(self):
                    return json.dumps({"choices": [{"message": {"content": "red"}}]}).encode()

            return Resp()

        monkeypatch.setattr("ppt_lib.model_compat.urllib.request.urlopen", fake_urlopen)

        result = probe_openai_compatible_vision("http://localhost:1234/v1", "qwen")

        assert result.status == "ok"
        assert seen_content_types == ["image_url"]

    def test_ollama_vision_sends_image_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen_image_count: list[int] = []

        def fake_urlopen(request, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            seen_image_count.append(len(payload["images"]))

            class Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def read(self):
                    return json.dumps({"response": "red"}).encode()

            return Resp()

        monkeypatch.setattr("ppt_lib.model_compat.urllib.request.urlopen", fake_urlopen)

        result = probe_ollama_vision("http://localhost:11434", "llava")

        assert result.status == "ok"
        assert seen_image_count == [1]

    def test_empty_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(request, timeout):
            class Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def read(self):
                    return json.dumps({"choices": [{"message": {"content": ""}}]}).encode()

            return Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = probe_chat("http://localhost:1234/v1", "model")
        assert result.status == "error"
        assert "CHAT_EMPTY_RESPONSE" in str(result.details)

    def test_reasoning_content_counts_as_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_urlopen(request, timeout):
            class Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def read(self):
                    return json.dumps({"choices": [{"message": {"content": "", "reasoning_content": "thinking"}}]}).encode()

            return Resp()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        result = probe_chat("http://localhost:1234/v1", "model")
        assert result.status == "ok"


class TestCapabilityCache:
    def test_roundtrip(self, tmp_path: Path) -> None:
        records = [{"provider": "lmstudio", "model": "test", "capability": "embedding", "status": "ok"}]
        save_capability_cache(tmp_path, records)
        loaded = load_capability_cache(tmp_path)
        assert loaded == records

    def test_empty_when_missing(self, tmp_path: Path) -> None:
        assert load_capability_cache(tmp_path) == []

    def test_record_probe_result_deduplicates(self, tmp_path: Path) -> None:
        result = ProbeResult(capability="embedding", status="ok", message="ok", details={})
        record_probe_result(tmp_path, provider="lmstudio", base_url="http://x", model="m", result=result)
        record_probe_result(tmp_path, provider="lmstudio", base_url="http://x", model="m", result=result)
        loaded = load_capability_cache(tmp_path)
        assert len(loaded) == 1
