"""Tests for ppt_lib.llm_client — call_lmstudio explicit model requirement."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ppt_lib.config import load_settings
from ppt_lib.llm_client import LLMError, call_lmstudio


def test_call_lmstudio_requires_model(tmp_path: Path) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "lmstudio_vision_model": ""},
        config_path=tmp_path / "config.yml",
    )

    with pytest.raises(LLMError, match="No LM Studio model configured"):
        call_lmstudio("hello", settings)


def test_call_lmstudio_uses_configured_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "lmstudio_vision_model": "my-model"},
        config_path=tmp_path / "config.yml",
    )
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        captured["model"] = body["model"]

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "response text"}}]}).encode()

        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = call_lmstudio("hello", settings)
    assert result == "response text"
    assert captured["model"] == "my-model"


def test_call_lmstudio_model_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "lmstudio_vision_model": "default-model"},
        config_path=tmp_path / "config.yml",
    )
    captured: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        captured["model"] = body["model"]

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self):
                return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    call_lmstudio("hello", settings, model="override-model")
    assert captured["model"] == "override-model"


def test_call_lmstudio_handles_reasoning_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(
        {"home_dir": tmp_path, "lmstudio_vision_model": "qwen-model"},
        config_path=tmp_path / "config.yml",
    )

    def fake_urlopen(request, timeout):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": "", "reasoning_content": "thought process"}}]
                }).encode()

        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = call_lmstudio("hello", settings)
    assert result == "thought process"
