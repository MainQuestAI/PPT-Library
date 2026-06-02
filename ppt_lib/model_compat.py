"""Model compatibility gate: shared response extraction, probes, and capability caching."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

CapabilityKind = Literal["embedding", "chat", "vision", "json_schema", "text_fallback"]
ProbeStatus = Literal["ok", "error"]
_RED_BLOCK_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAK0lEQVR4nO3OIQEAAAwEoetfeovxBoGnq1tKQEBAQEBAQEBAQEBAQEBgHXhUDfhqRFDd3gAAAABJRU5ErkJggg=="
)


@dataclass(frozen=True)
class ProbeResult:
    capability: CapabilityKind
    status: ProbeStatus
    message: str
    details: dict[str, object]


@dataclass
class ModelCapabilityRecord:
    provider: str
    base_url: str
    model: str
    capability: CapabilityKind
    status: ProbeStatus
    dimension: int | None = None
    last_checked_at: str = ""
    error_code: str = ""


def extract_chat_text(response: dict[str, Any]) -> str:
    """Unified extraction of text from OpenAI-compatible chat response.

    Handles standard content, empty content with reasoning_content (Qwen-style),
    and legacy text field.
    """
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        # Qwen and similar models put content in reasoning_content
        reasoning_content = message.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            return reasoning_content
        # content might be non-empty but all whitespace; still return it if no reasoning
        if isinstance(content, str):
            return content
        return ""
    # Legacy: some providers use top-level text field
    text = first.get("text")
    return text if isinstance(text, str) else ""


def list_openai_compatible_models(base_url: str, *, timeout: float = 5.0) -> list[str]:
    """Return model ids from an OpenAI-compatible /models endpoint."""
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/models", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    raw_models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        return []
    model_ids: list[str] = []
    for model in raw_models:
        if not isinstance(model, dict):
            continue
        value = model.get("id") or model.get("name") or model.get("model")
        if isinstance(value, str) and value:
            model_ids.append(value)
    return model_ids


def detect_lmstudio_chat_model(base_url: str, *, timeout: float = 5.0) -> str | None:
    """Pick a plausible chat/vision model from LM Studio without using a fake placeholder."""
    for model_id in list_openai_compatible_models(base_url, timeout=timeout):
        normalized = model_id.lower()
        if any(token in normalized for token in ("embed", "embedding", "bge-", "gte-")):
            continue
        return model_id
    return None


def probe_embedding(
    base_url: str,
    model: str,
    expected_dimensions: int,
    *,
    timeout: float = 10.0,
    api_key: str = "",
) -> ProbeResult:
    """Send a real embedding request and verify response shape + dimensions."""
    url = f"{base_url.rstrip('/')}/embeddings"
    payload = {"model": model, "input": "probe test sentence"}
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        return ProbeResult(
            capability="embedding",
            status="error",
            message=f"HTTP {exc.code}: {body}",
            details={"error_code": "EMBEDDING_HTTP_ERROR"},
        )
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return ProbeResult(
            capability="embedding",
            status="error",
            message=str(exc),
            details={"error_code": "EMBEDDING_NETWORK_ERROR"},
        )

    try:
        embedding = data["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError):
        return ProbeResult(
            capability="embedding",
            status="error",
            message="Invalid response shape: missing data[0].embedding",
            details={"error_code": "EMBEDDING_INVALID_RESPONSE", "response_keys": list(data.keys()) if isinstance(data, dict) else []},
        )

    actual_dim = len(embedding) if isinstance(embedding, list) else 0
    if actual_dim != expected_dimensions:
        return ProbeResult(
            capability="embedding",
            status="error",
            message=f"Dimension mismatch: expected {expected_dimensions}, got {actual_dim}",
            details={"error_code": "EMBEDDING_DIMENSION_MISMATCH", "expected": expected_dimensions, "actual": actual_dim},
        )

    return ProbeResult(
        capability="embedding",
        status="ok",
        message=f"Embedding probe passed ({actual_dim}d)",
        details={"dimensions": actual_dim},
    )


def probe_chat(
    base_url: str,
    model: str,
    *,
    timeout: float = 15.0,
    api_key: str = "",
) -> ProbeResult:
    """Send a minimal chat request to verify the model responds."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the word OK."}],
        "temperature": 0,
        "max_tokens": 8,
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        return ProbeResult(capability="chat", status="error", message=f"HTTP {exc.code}: {body}", details={"error_code": "CHAT_HTTP_ERROR"})
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return ProbeResult(capability="chat", status="error", message=str(exc), details={"error_code": "CHAT_NETWORK_ERROR"})

    text = extract_chat_text(data)
    if not text:
        return ProbeResult(
            capability="chat", status="error", message="Model returned empty response",
            details={"error_code": "CHAT_EMPTY_RESPONSE", "response": data},
        )

    return ProbeResult(capability="chat", status="ok", message=f"Chat probe passed: {text[:50]}", details={"response_text": text[:100]})


def probe_openai_compatible_vision(
    base_url: str,
    model: str,
    *,
    timeout: float = 30.0,
    api_key: str = "",
) -> ProbeResult:
    """Send a real image request to an OpenAI-compatible chat endpoint."""
    if not model:
        return ProbeResult(
            capability="vision",
            status="error",
            message="No vision model configured",
            details={"error_code": "VISION_MODEL_NOT_CONFIGURED"},
        )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is the dominant color in this image? Answer briefly."},
                    {"type": "image_url", "image_url": {"url": _RED_BLOCK_PNG_DATA_URL}},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 64,
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        return ProbeResult(
            capability="vision",
            status="error",
            message=f"HTTP {exc.code}: {body}",
            details={"error_code": "VISION_HTTP_ERROR"},
        )
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return ProbeResult(
            capability="vision",
            status="error",
            message=str(exc),
            details={"error_code": "VISION_NETWORK_ERROR"},
        )
    text = extract_chat_text(data)
    if not text:
        return ProbeResult(
            capability="vision",
            status="error",
            message="Vision model returned empty response",
            details={"error_code": "VISION_EMPTY_RESPONSE", "response": data},
        )
    return ProbeResult(
        capability="vision",
        status="ok",
        message=f"Vision image probe passed: {text[:50]}",
        details={"response_text": text[:100]},
    )


def probe_ollama_vision(
    base_url: str,
    model: str,
    *,
    timeout: float = 30.0,
) -> ProbeResult:
    """Send a real image request to Ollama /api/generate."""
    image_base64 = _RED_BLOCK_PNG_DATA_URL.split(",", 1)[1]
    payload = {
        "model": model,
        "prompt": "What is the dominant color in this image? Answer briefly.",
        "images": [image_base64],
        "stream": False,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        return ProbeResult(
            capability="vision",
            status="error",
            message=f"HTTP {exc.code}: {body}",
            details={"error_code": "VISION_HTTP_ERROR"},
        )
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return ProbeResult(
            capability="vision",
            status="error",
            message=str(exc),
            details={"error_code": "VISION_NETWORK_ERROR"},
        )
    text = data.get("response") if isinstance(data, dict) else None
    if not isinstance(text, str) or not text.strip():
        return ProbeResult(
            capability="vision",
            status="error",
            message="Ollama vision model returned empty response",
            details={"error_code": "VISION_EMPTY_RESPONSE", "response": data if isinstance(data, dict) else {}},
        )
    return ProbeResult(
        capability="vision",
        status="ok",
        message=f"Ollama vision image probe passed: {text[:50]}",
        details={"response_text": text[:100]},
    )


# --- Capability cache ---

_CACHE_FILE = "models/capabilities.json"


def _cache_path(home_dir: Path) -> Path:
    return home_dir / _CACHE_FILE


def load_capability_cache(home_dir: Path) -> list[dict[str, Any]]:
    path = _cache_path(home_dir)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_capability_cache(home_dir: Path, records: list[dict[str, Any]]) -> None:
    path = _cache_path(home_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")


def record_probe_result(
    home_dir: Path,
    *,
    provider: str,
    base_url: str,
    model: str,
    result: ProbeResult,
    dimension: int | None = None,
) -> None:
    """Append or update a probe result in the capability cache."""
    records = load_capability_cache(home_dir)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Remove existing entry for same provider+model+capability
    records = [
        r for r in records
        if not (r.get("provider") == provider and r.get("model") == model and r.get("capability") == result.capability)
    ]
    records.append({
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "capability": result.capability,
        "status": result.status,
        "dimension": dimension,
        "last_checked_at": now,
        "error_code": result.details.get("error_code", ""),
    })
    save_capability_cache(home_dir, records)
