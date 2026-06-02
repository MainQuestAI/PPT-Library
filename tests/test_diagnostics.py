from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from ppt_lib.config import load_settings
from ppt_lib.diagnostics import check_api_key, probe_lmstudio, run_diagnostics


def test_soffice_detected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ppt_lib.diagnostics.shutil.which", lambda name: "/usr/bin/soffice")
    monkeypatch.setattr("ppt_lib.diagnostics.probe_ollama", lambda base_url, timeout=2.0: ("skipped", "not checked", {}))
    monkeypatch.setattr(
        "ppt_lib.diagnostics.probe_lmstudio",
        lambda base_url, timeout=2.0, vision_model=None: ("skipped", "not checked", {}),
    )
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    report = run_diagnostics(settings)

    libreoffice = next(check for check in report.checks if check.name == "libreoffice")
    assert libreoffice.status == "ok"
    assert report.can_index is True


def test_soffice_missing_blocks_index(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ppt_lib.diagnostics.shutil.which", lambda name: None)
    monkeypatch.setattr("ppt_lib.diagnostics.probe_ollama", lambda base_url, timeout=2.0: ("skipped", "not checked", {}))
    monkeypatch.setattr(
        "ppt_lib.diagnostics.probe_lmstudio",
        lambda base_url, timeout=2.0, vision_model=None: ("skipped", "not checked", {}),
    )
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    report = run_diagnostics(settings)

    libreoffice = next(check for check in report.checks if check.name == "libreoffice")
    assert libreoffice.status == "error"
    assert report.can_index is False


def test_ollama_detected_with_vision_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ppt_lib.diagnostics.shutil.which", lambda name: "/usr/bin/soffice")
    monkeypatch.setattr(
        "ppt_lib.diagnostics.probe_ollama",
        lambda base_url, timeout=2.0: ("ok", "vision model available", {"model": "llava"}),
    )
    monkeypatch.setattr(
        "ppt_lib.diagnostics.probe_lmstudio",
        lambda base_url, timeout=2.0, vision_model=None: ("warning", "not running", {}),
    )
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    report = run_diagnostics(settings)

    assert report.can_use_vision is True
    assert report.recommended_chain[0] == "ollama"


def test_lmstudio_timeout_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ppt_lib.diagnostics.shutil.which", lambda name: "/usr/bin/soffice")
    monkeypatch.setattr("ppt_lib.diagnostics.probe_ollama", lambda base_url, timeout=2.0: ("warning", "not running", {}))
    monkeypatch.setattr("ppt_lib.diagnostics.probe_lmstudio", lambda base_url, timeout=2.0, vision_model=None: ("warning", "timeout", {}))
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    report = run_diagnostics(settings)

    lmstudio = next(check for check in report.checks if check.name == "lmstudio")
    assert lmstudio.status == "warning"
    assert "text_extraction" in report.recommended_chain


def test_api_key_redacted() -> None:
    check = check_api_key("openai_embedding", "sk-secret")

    assert check.status == "ok"
    assert check.details["api_key"] == "present"
    assert "sk-secret" not in repr(check)


def test_report_json_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ppt_lib.diagnostics.shutil.which", lambda name: "/usr/bin/soffice")
    monkeypatch.setattr("ppt_lib.diagnostics.probe_ollama", lambda base_url, timeout=2.0: ("warning", "not running", {}))
    monkeypatch.setattr(
        "ppt_lib.diagnostics.probe_lmstudio",
        lambda base_url, timeout=2.0, vision_model=None: ("warning", "not running", {}),
    )
    settings = load_settings({"home_dir": tmp_path}, config_path=tmp_path / "config.yml")

    payload = run_diagnostics(settings).to_json()

    assert payload["can_index"] is True
    assert isinstance(payload["checks"], list)
    assert "_errors" in payload


def test_report_json_includes_embedding_vision_and_fallback_chains(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ppt_lib.diagnostics.shutil.which", lambda name: "/usr/bin/soffice")
    monkeypatch.setattr("ppt_lib.diagnostics.probe_ollama", lambda base_url, timeout=2.0: ("warning", "not running", {}))
    monkeypatch.setattr(
        "ppt_lib.diagnostics.probe_lmstudio",
        lambda base_url, timeout=2.0, vision_model=None: ("ok", "vision model available", {"models": []}),
    )
    monkeypatch.setattr(
        "ppt_lib.diagnostics.probe_embedding_provider",
        lambda settings, timeout=10.0: ("ok", "lmstudio embedding available", {}),
    )
    settings = load_settings(
        {"home_dir": tmp_path, "embedding_provider": "lmstudio", "vision_provider": "lmstudio"},
        config_path=tmp_path / "config.yml",
    )

    payload = run_diagnostics(settings).to_json()
    chains = cast(dict[str, dict[str, object]], payload["chains"])

    assert chains["embedding"]["provider"] == "lmstudio"
    assert chains["embedding"]["status"] == "ok"
    assert chains["vision"]["provider"] == "lmstudio"
    assert chains["vision"]["status"] == "ok"
    assert chains["fallback"]["provider"] == "text_extraction"
    assert chains["fallback"]["status"] == "ok"


def test_run_diagnostics_uses_configured_vision_timeout_for_lmstudio(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen_timeouts: list[float] = []
    monkeypatch.setattr("ppt_lib.diagnostics.shutil.which", lambda name: "/usr/bin/soffice")
    monkeypatch.setattr("ppt_lib.diagnostics.probe_ollama", lambda base_url, timeout=2.0: ("warning", "not running", {}))

    def fake_probe_lmstudio(base_url: str, timeout: float = 2.0, vision_model: str | None = None):
        seen_timeouts.append(timeout)
        return "ok", "configured vision model image probe passed", {"configured_vision_model": vision_model}

    monkeypatch.setattr("ppt_lib.diagnostics.probe_lmstudio", fake_probe_lmstudio)
    settings = load_settings(
        {
            "home_dir": tmp_path,
            "vision_provider": "lmstudio",
            "vision_timeout_seconds": 45,
        },
        config_path=tmp_path / "config.yml",
    )

    run_diagnostics(settings)

    assert seen_timeouts == [45]


def test_lmstudio_detects_configured_gemma_vision_model(monkeypatch: pytest.MonkeyPatch) -> None:
    model_payload = {
        "data": [
            {"id": "google/gemma-4-26b-a4b", "object": "model", "owned_by": "organization_owner"},
            {"id": "text-embedding-qwen3-embedding-4b", "object": "model", "owned_by": "organization_owner"},
        ],
        "object": "list",
    }
    chat_payload = {"choices": [{"message": {"content": "red"}}]}

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/models"):
            return Response(model_payload)
        if url.endswith("/chat/completions"):
            return Response(chat_payload)
        raise AssertionError(url)

    monkeypatch.setattr("ppt_lib.diagnostics.urllib.request.urlopen", fake_urlopen)

    status, message, details = probe_lmstudio(
        "http://127.0.0.1:1234/v1",
        vision_model="google/gemma-4-26b-a4b",
    )

    assert status == "ok"
    assert message == "configured vision model image probe passed"
    assert details["configured_vision_model"] == "google/gemma-4-26b-a4b"


def test_lmstudio_configured_model_requires_real_image_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    model_payload = {
        "data": [
            {"id": "qwen/qwen3.6-27b", "object": "model", "owned_by": "organization_owner"},
        ],
        "object": "list",
    }
    chat_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "title": "Probe",
                            "text_content": "红色",
                            "metadata": {"dominant_color": "red"},
                            "confidence": 0.9,
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }
    called_urls: list[str] = []

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        called_urls.append(url)
        if url.endswith("/models"):
            return Response(model_payload)
        if url.endswith("/chat/completions"):
            return Response(chat_payload)
        raise AssertionError(url)

    monkeypatch.setattr("ppt_lib.diagnostics.urllib.request.urlopen", fake_urlopen)

    status, message, details = probe_lmstudio(
        "http://127.0.0.1:1234/v1",
        vision_model="qwen/qwen3.6-27b",
    )

    assert status == "ok"
    assert message == "configured vision model image probe passed"
    assert details["configured_vision_model"] == "qwen/qwen3.6-27b"
    assert any(url.endswith("/chat/completions") for url in called_urls)


def test_lmstudio_image_probe_accepts_reasoning_content(monkeypatch: pytest.MonkeyPatch) -> None:
    model_payload = {
        "data": [{"id": "qwen/qwen3.6-27b", "object": "model", "owned_by": "organization_owner"}],
        "object": "list",
    }
    chat_payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "The image is a solid red block.",
                },
                "finish_reason": "stop",
            }
        ]
    }

    class Response:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if url.endswith("/models"):
            return Response(model_payload)
        if url.endswith("/chat/completions"):
            return Response(chat_payload)
        raise AssertionError(url)

    monkeypatch.setattr("ppt_lib.diagnostics.urllib.request.urlopen", fake_urlopen)

    status, message, details = probe_lmstudio(
        "http://127.0.0.1:1234/v1",
        vision_model="qwen/qwen3.6-27b",
    )

    assert status == "ok"
    assert message == "configured vision model image probe passed"
    assert details["image_probe"] == {"response_text": "The image is a solid red block."}


def test_vision_chain_warns_when_slide_limit_disables_indexing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("ppt_lib.diagnostics.shutil.which", lambda name: "/usr/bin/soffice")
    monkeypatch.setattr("ppt_lib.diagnostics.probe_ollama", lambda base_url, timeout=2.0: ("warning", "not running", {}))
    monkeypatch.setattr(
        "ppt_lib.diagnostics.probe_lmstudio",
        lambda base_url, timeout=2.0, vision_model=None: ("ok", "configured vision model image probe passed", {}),
    )
    settings = load_settings(
        {
            "home_dir": tmp_path,
            "vision_provider": "lmstudio",
            "vision_max_slides_per_file": 0,
        },
        config_path=tmp_path / "config.yml",
    )

    payload = run_diagnostics(settings).to_json()
    chains = cast(dict[str, dict[str, object]], payload["chains"])

    assert payload["can_use_vision"] is False
    assert chains["vision"]["status"] == "warning"
    assert "vision_max_slides_per_file=0" in str(chains["vision"]["message"])
