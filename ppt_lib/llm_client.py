"""Shared LLM client for OpenAI-compatible and Anthropic APIs."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ppt_lib.settings import Settings


class LLMError(Exception):
    """Raised when LLM call fails."""


def http_post_json(url: str, payload: dict, headers: dict | None = None, timeout: float = 30.0) -> dict:
    """POST JSON and return parsed response."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_llm(
    prompt: str,
    settings: Settings,
    *,
    max_tokens: int = 300,
    temperature: float = 0.1,
) -> str:
    """Call LLM via OpenAI-compatible or Anthropic Messages API.

    Auto-detects Anthropic format when base_url contains 'anthropic'.
    Raises LLMError on failure.
    """
    base_url = settings.cloud_vision_base_url.rstrip("/")
    api_key = settings.openai_api_key or settings.vision_api_key
    if not api_key:
        raise LLMError("No API key configured (openai_api_key or vision_api_key required)")

    model = getattr(settings, "annotation_model", None) or settings.cloud_vision_model

    try:
        if "anthropic" in base_url.lower():
            data = http_post_json(
                f"{base_url}/v1/messages",
                {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]},
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                timeout=60.0,
            )
            for block in data.get("content", []):
                if block.get("type") == "text":
                    return block["text"]
            raise LLMError(f"No text content in Anthropic response: {data}")
        else:
            data = http_post_json(
                f"{base_url}/chat/completions",
                {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": temperature, "max_tokens": max_tokens},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30.0,
            )
            return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, IndexError, OSError) as exc:
        raise LLMError(f"LLM call failed: {exc}") from exc


def call_lmstudio(
    prompt: str,
    settings: Settings,
    *,
    max_tokens: int = 200,
    temperature: float = 0.1,
    model: str | None = None,
) -> str:
    """Call LM Studio local LLM via OpenAI-compatible chat/completions endpoint.

    Uses the explicitly configured vision model, or the caller-specified model override.
    Does NOT silently pick the first available model — callers must configure a model.
    Raises LLMError on failure.
    """
    from ppt_lib.model_compat import extract_chat_text

    base_url = settings.lmstudio_base_url.rstrip("/")

    # Resolve model: explicit param > configured vision model > error
    resolved_model = model or settings.lmstudio_vision_model
    if not resolved_model:
        raise LLMError(
            "No LM Studio model configured. Set lmstudio_vision_model in config "
            "or pass model= explicitly."
        )

    try:
        data = http_post_json(
            f"{base_url}/chat/completions",
            {
                "model": resolved_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=60.0,
        )
        text = extract_chat_text(data)
        if not text:
            raise LLMError(f"LM Studio returned empty response from model {resolved_model}")
        return text
    except (urllib.error.URLError, KeyError, IndexError, OSError) as exc:
        raise LLMError(f"LM Studio call failed: {exc}") from exc
