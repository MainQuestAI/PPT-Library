"""ppt-lib models test: probe all configured model capabilities."""
from __future__ import annotations

from typing import Any

from ppt_lib.diagnostics import probe_lmstudio, probe_mmx
from ppt_lib.model_compat import (
    ProbeResult,
    extract_chat_text,
    probe_chat,
    probe_embedding,
    probe_ollama_vision,
    probe_openai_compatible_vision,
    record_probe_result,
)
from ppt_lib.settings import Settings


def run_models_test(settings: Settings) -> dict[str, Any]:
    """Run comprehensive model capability probes and return structured results.

    Tests: embedding, chat, vision, json_schema compatibility.
    Writes results to capability cache at ~/.ppt-library/models/capabilities.json.
    """
    results: list[dict[str, Any]] = []

    # --- Embedding probe ---
    emb_result = _test_embedding(settings)
    results.append(emb_result)

    # --- Chat probe ---
    chat_result = _test_chat(settings)
    results.append(chat_result)

    # --- Vision probe ---
    vision_result = _test_vision(settings)
    results.append(vision_result)

    # --- JSON schema probe ---
    json_result = _test_json_schema(settings)
    results.append(json_result)

    # Write cache
    _update_cache(settings, results)

    # Summary
    ok_count = sum(1 for r in results if r["status"] == "ok")
    error_count = sum(1 for r in results if r["status"] == "error")
    warning_count = sum(1 for r in results if r["status"] == "warning")

    summary_status = "error" if error_count else "warning" if warning_count else "ok"

    # Generate setup recommendation
    embedding_result = next((r for r in results if r["capability"] == "embedding"), None)
    embedding_ok = embedding_result and embedding_result["status"] == "ok"
    if embedding_ok:
        recommendation = "Production mode recommended. Embedding model is working — run `ppt-lib setup` to configure."
    else:
        recommendation = (
            "Quick Start recommended. No working embedding model detected — "
            "run `ppt-lib setup --quick` to auto-detect or configure manually."
        )

    return {
        "summary": {
            "total": len(results),
            "ok": ok_count,
            "error": error_count,
            "warning": warning_count,
            "status": summary_status,
        },
        "probes": results,
        "recommendation": recommendation,
        "cache_path": str(settings.home_dir / "models" / "capabilities.json"),
    }


def _test_embedding(settings: Settings) -> dict[str, Any]:
    provider = settings.embedding_provider
    if provider == "fake":
        return {
            "capability": "embedding",
            "provider": provider,
            "model": "fake",
            "status": "ok",
            "message": "Fake provider always works",
        }

    api_url = _embedding_api_url(settings)
    model = _embedding_model(settings)
    api_key = settings.embedding_api_key or settings.openai_api_key
    if not api_url:
        return {
            "capability": "embedding",
            "provider": provider,
            "model": model,
            "status": "warning",
            "message": f"Unknown provider: {provider}",
        }
    if _is_openai_public_endpoint(api_url) and not api_key:
        return {
            "capability": "embedding",
            "provider": provider,
            "model": model,
            "status": "error",
            "message": "Embedding API key missing",
            "details": {"api_url": api_url},
        }

    result = probe_embedding(
        api_url,
        model,
        settings.embedding_dimensions,
        timeout=float(settings.embedding_timeout_seconds),
        api_key=api_key or "",
    )
    details = dict(result.details)
    details.setdefault("api_url", api_url)
    return {
        "capability": "embedding",
        "provider": provider,
        "model": model,
        "status": result.status,
        "message": result.message,
        "details": details,
    }


def _embedding_api_url(settings: Settings) -> str | None:
    if settings.embedding_api_url:
        return settings.embedding_api_url
    if settings.embedding_provider == "openai":
        return "https://api.openai.com/v1"
    if settings.embedding_provider == "lmstudio":
        return settings.lmstudio_base_url
    return None


def _embedding_model(settings: Settings) -> str:
    if settings.embedding_provider == "lmstudio" and not settings.embedding_api_url:
        return settings.lmstudio_embedding_model
    return settings.embedding_model


def _is_openai_public_endpoint(api_url: str) -> bool:
    return api_url.rstrip("/") == "https://api.openai.com/v1"


def _test_chat(settings: Settings) -> dict[str, Any]:
    if settings.vision_provider == "cloud":
        api_key = settings.vision_api_key or settings.openai_api_key
        model = getattr(settings, "annotation_model", None) or settings.cloud_vision_model
        if not api_key:
            return {
                "capability": "chat",
                "provider": "cloud",
                "model": model,
                "status": "skipped",
                "message": "Cloud chat probe skipped; API key missing",
            }
        base_url = settings.cloud_vision_base_url.rstrip("/")
        result = probe_chat(base_url, model, timeout=15.0, api_key=api_key)
        return {
            "capability": "chat",
            "provider": "cloud",
            "model": model,
            "status": result.status,
            "message": result.message,
            "details": result.details,
        }

    if settings.vision_provider == "text_extraction":
        return {
            "capability": "chat",
            "provider": "text_extraction",
            "model": "text_extraction",
            "status": "skipped",
            "message": "Chat probe skipped; text extraction only",
        }

    if settings.vision_provider == "mmx":
        return {
            "capability": "chat",
            "provider": "mmx",
            "model": settings.mmx_vision_model,
            "status": "skipped",
            "message": "Chat probe skipped; mmx vision provider uses `mmx vision describe`",
        }

    if settings.vision_provider == "paddleocr_mcp":
        return {
            "capability": "chat",
            "provider": "paddleocr_mcp",
            "model": settings.paddleocr_mcp_pipeline,
            "status": "skipped",
            "message": "Chat probe skipped; PaddleOCR MCP provider uses document parsing",
        }

    if settings.openai_api_key:
        base_url = settings.cloud_vision_base_url.rstrip("/")
        model = getattr(settings, "annotation_model", None) or settings.cloud_vision_model
        result = probe_chat(base_url, model, timeout=15.0, api_key=settings.openai_api_key)
        return {
            "capability": "chat",
            "provider": "cloud",
            "model": model,
            "status": result.status,
            "message": result.message,
            "details": result.details,
        }

    if settings.lmstudio_vision_model:
        result = probe_chat(settings.lmstudio_base_url, settings.lmstudio_vision_model, timeout=30.0)
        return {
            "capability": "chat",
            "provider": "lmstudio",
            "model": settings.lmstudio_vision_model,
            "status": result.status,
            "message": result.message,
            "details": result.details,
        }

    return {"capability": "chat", "provider": "none", "model": "?", "status": "error", "message": "No chat model configured"}


def _test_vision(settings: Settings) -> dict[str, Any]:
    provider = settings.vision_provider

    if provider == "lmstudio":
        status, message, details = probe_lmstudio(
            settings.lmstudio_base_url,
            timeout=float(settings.vision_timeout_seconds),
            vision_model=settings.lmstudio_vision_model,
        )
        return {
            "capability": "vision",
            "provider": provider,
            "model": settings.lmstudio_vision_model or "auto",
            "status": status,
            "message": message,
            "details": details,
        }

    if provider == "ollama":
        result = probe_ollama_vision(
            settings.ollama_base_url,
            settings.ollama_vision_model,
            timeout=float(settings.vision_timeout_seconds),
        )
        return {
            "capability": "vision",
            "provider": provider,
            "model": settings.ollama_vision_model,
            "status": result.status,
            "message": result.message,
            "details": result.details,
        }

    if provider == "cloud":
        api_key = settings.vision_api_key or settings.openai_api_key
        if not api_key:
            return {
                "capability": "vision", "provider": provider,
                "model": settings.cloud_vision_model, "status": "error",
                "message": "Vision API key missing",
            }
        result = probe_openai_compatible_vision(
            settings.cloud_vision_base_url,
            settings.cloud_vision_model,
            timeout=float(settings.vision_timeout_seconds),
            api_key=api_key,
        )
        return {
            "capability": "vision", "provider": provider,
            "model": settings.cloud_vision_model,
            "status": result.status,
            "message": result.message,
            "details": result.details,
        }

    if provider == "mmx":
        status, message, details = probe_mmx(settings.mmx_command, timeout=float(settings.vision_timeout_seconds))
        return {
            "capability": "vision",
            "provider": provider,
            "model": settings.mmx_vision_model,
            "status": status,
            "message": message,
            "details": details,
        }

    if provider == "text_extraction":
        return {
            "capability": "vision", "provider": provider,
            "model": "text_extraction", "status": "skipped",
            "message": "Vision disabled; text extraction only",
        }

    status, message, details = probe_lmstudio(
        settings.lmstudio_base_url,
        timeout=float(settings.vision_timeout_seconds),
        vision_model=settings.lmstudio_vision_model,
    )
    if status == "ok":
        return {
            "capability": "vision", "provider": "lmstudio",
            "model": settings.lmstudio_vision_model,
            "status": status,
            "message": message,
            "details": details,
        }
    api_key = settings.vision_api_key or settings.openai_api_key
    if api_key:
        result = probe_openai_compatible_vision(
            settings.cloud_vision_base_url,
            settings.cloud_vision_model,
            timeout=float(settings.vision_timeout_seconds),
            api_key=api_key,
        )
        return {
            "capability": "vision", "provider": "cloud",
            "model": settings.cloud_vision_model,
            "status": result.status,
            "message": result.message,
            "details": result.details,
        }
    return {
        "capability": "vision", "provider": "auto", "model": "auto",
        "status": "error",
        "message": "No working vision provider detected",
        "details": details,
    }


def _test_json_schema(settings: Settings) -> dict[str, Any]:
    """Probe whether the chat model supports structured output (json_schema response_format)."""
    import json
    import urllib.error
    import urllib.request

    if settings.vision_provider not in {"auto", "lmstudio"}:
        return {
            "capability": "json_schema",
            "provider": settings.vision_provider,
            "model": _vision_model_label(settings),
            "status": "skipped",
            "message": "json_schema probe skipped for non-LM Studio vision provider",
        }

    if not settings.lmstudio_vision_model:
        return {
            "capability": "json_schema", "provider": "none", "model": "?",
            "status": "skipped", "message": "No LM Studio model configured",
        }

    base_url = settings.lmstudio_base_url.rstrip("/")
    payload = {
        "model": settings.lmstudio_vision_model,
        "messages": [{"role": "user", "content": "Reply with a JSON object: {\"test\": true}"}],
        "temperature": 0,
        "max_tokens": 32,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "probe",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"test": {"type": "boolean"}},
                    "required": ["test"],
                    "additionalProperties": False,
                },
            },
        },
    }

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = extract_chat_text(data)
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and "test" in parsed:
                    return {
                        "capability": "json_schema",
                        "provider": "lmstudio",
                        "model": settings.lmstudio_vision_model,
                        "status": "ok",
                        "message": "json_schema supported",
                        "details": {"parsed": parsed},
                    }
            except json.JSONDecodeError:
                pass
        return {
            "capability": "json_schema",
            "provider": "lmstudio",
            "model": settings.lmstudio_vision_model,
            "status": "warning",
            "message": f"json_schema sent but response not valid JSON: {text[:100]}",
        }
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError) as exc:
        return {
            "capability": "json_schema",
            "provider": "lmstudio",
            "model": settings.lmstudio_vision_model,
            "status": "warning",
            "message": f"json_schema not supported: {exc}",
            "details": {"text_fallback_recommended": True},
        }


def _vision_model_label(settings: Settings) -> str:
    if settings.vision_provider == "cloud":
        return settings.cloud_vision_model
    if settings.vision_provider == "mmx":
        return settings.mmx_vision_model
    if settings.vision_provider == "paddleocr_mcp":
        return settings.paddleocr_mcp_pipeline
    if settings.vision_provider == "ollama":
        return settings.ollama_vision_model
    if settings.vision_provider == "text_extraction":
        return "text_extraction"
    return "?"


def _update_cache(settings: Settings, results: list[dict[str, Any]]) -> None:
    """Write probe results to capability cache."""
    for r in results:
        if r["status"] == "skipped":
            continue
        details = r.get("details", {})
        base_url = details.get("api_url") if isinstance(details, dict) else None
        if not isinstance(base_url, str):
            base_url = settings.lmstudio_base_url if r.get("provider") == "lmstudio" else "https://api.openai.com/v1"
        record_probe_result(
            settings.home_dir,
            provider=r.get("provider", "unknown"),
            base_url=base_url,
            model=r.get("model", "unknown"),
            result=ProbeResult(
                capability=r["capability"],
                status="ok" if r["status"] == "ok" else "error",
                message=r.get("message", ""),
                details=r.get("details", {}),
            ),
            dimension=r.get("details", {}).get("dimensions"),
        )
