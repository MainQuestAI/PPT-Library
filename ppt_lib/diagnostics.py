from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Literal

from ppt_lib.config import ensure_dirs
from ppt_lib.settings import Settings

CheckStatus = Literal["ok", "warning", "error", "skipped"]
_RED_PIXEL_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAK0lEQVR4nO3OIQEAAAwEoetfeovxBoGnq1tKQEBAQEBAQEBAQEBAQEBgHXhUDfhqRFDd3gAAAABJRU5ErkJggg=="
)


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    status: CheckStatus
    message: str
    details: dict[str, object]


@dataclass(frozen=True)
class DiagnosticReport:
    checks: list[DiagnosticCheck]
    recommended_chain: list[str]
    chains: dict[str, dict[str, object]]
    can_index: bool
    can_use_vision: bool

    def to_json(self) -> dict[str, object]:
        return {
            "checks": [asdict(check) for check in self.checks],
            "recommended_chain": self.recommended_chain,
            "chains": self.chains,
            "can_index": self.can_index,
            "can_use_vision": self.can_use_vision,
            "_errors": [],
        }


def run_diagnostics(settings: Settings) -> DiagnosticReport:
    checks: list[DiagnosticCheck] = []
    soffice = shutil.which("soffice")
    checks.append(
        DiagnosticCheck(
            name="libreoffice",
            status="ok" if soffice else "error",
            message="soffice available" if soffice else "soffice not found",
            details={"path": soffice or "missing"},
        )
    )
    checks.append(
        DiagnosticCheck(
            name="sqlite",
            status="ok" if sqlite3.sqlite_version else "error",
            message=f"sqlite {sqlite3.sqlite_version}",
            details={"version": sqlite3.sqlite_version},
        )
    )
    try:
        ensure_dirs(settings)
        screenshots_status: CheckStatus = "ok"
        screenshots_message = "screenshots directory writable"
    except Exception as exc:
        screenshots_status = "error"
        screenshots_message = str(exc)
    checks.append(
        DiagnosticCheck(
            name="screenshots_dir",
            status=screenshots_status,
            message=screenshots_message,
            details={"path": str(settings.screenshots_dir)},
        )
    )
    checks.append(check_api_key("openai_embedding", settings.openai_api_key))
    checks.append(check_api_key("cloud_vision", settings.vision_api_key, required=False))
    mmx_status, mmx_message, mmx_details = probe_mmx(settings.mmx_command, timeout=float(settings.vision_timeout_seconds))
    checks.append(DiagnosticCheck("mmx", mmx_status, mmx_message, mmx_details))
    paddleocr_status, paddleocr_message, paddleocr_details = probe_paddleocr_mcp(settings)
    checks.append(DiagnosticCheck("paddleocr_mcp", paddleocr_status, paddleocr_message, paddleocr_details))

    ollama_status, ollama_message, ollama_details = probe_ollama(settings.ollama_base_url)
    checks.append(DiagnosticCheck("ollama", ollama_status, ollama_message, ollama_details))
    lm_status, lm_message, lm_details = probe_lmstudio(
        settings.lmstudio_base_url,
        timeout=float(settings.vision_timeout_seconds),
        vision_model=settings.lmstudio_vision_model,
    )
    checks.append(DiagnosticCheck("lmstudio", lm_status, lm_message, lm_details))

    # Independent embedding probe
    emb_status, emb_message, emb_details = probe_embedding_provider(settings, timeout=float(settings.embedding_timeout_seconds))
    checks.append(DiagnosticCheck("embedding_probe", emb_status, emb_message, emb_details))

    can_index = all(
        check.status == "ok"
        for check in checks
        if check.name in {"libreoffice", "sqlite", "screenshots_dir"}
    )
    chains = _diagnostic_chains(settings, checks)
    vision_chain = chains["vision"]
    can_use_vision = vision_chain["status"] == "ok" and settings.vision_max_slides_per_file != 0
    recommended_chain = _recommended_chain(settings, checks)
    return DiagnosticReport(
        checks=checks,
        recommended_chain=recommended_chain,
        chains=chains,
        can_index=can_index,
        can_use_vision=can_use_vision,
    )


def check_api_key(name: str, value: str | None, *, required: bool = True) -> DiagnosticCheck:
    if value:
        return DiagnosticCheck(name, "ok", "API key present", {"api_key": "present"})
    return DiagnosticCheck(
        name,
        "error" if required else "skipped",
        "API key missing" if required else "API key not configured",
        {"api_key": "missing"},
    )


def probe_ollama(base_url: str = "http://127.0.0.1:11434", timeout: float = 2.0) -> tuple[CheckStatus, str, dict[str, object]]:
    return _probe_json_models(f"{base_url.rstrip('/')}/api/tags", timeout)


def probe_lmstudio(
    base_url: str = "http://127.0.0.1:1234/v1",
    timeout: float = 2.0,
    vision_model: str | None = None,
) -> tuple[CheckStatus, str, dict[str, object]]:
    return _probe_json_models(
        f"{base_url.rstrip('/')}/models",
        timeout,
        configured_vision_model=vision_model,
    )


def probe_mmx(command: str = "mmx", timeout: float = 30.0) -> tuple[CheckStatus, str, dict[str, object]]:
    if shutil.which(command) is None:
        return "warning", "mmx command not found", {"command": command}
    try:
        auth = subprocess.run(
            [command, "auth", "status", "--output", "json", "--quiet", "--non-interactive"],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "warning", "mmx auth status timed out", {"command": command}
    except FileNotFoundError:
        return "warning", "mmx command not found", {"command": command}
    if auth.returncode != 0:
        return _mmx_probe_error(auth.returncode, auth.stderr or auth.stdout, command=command)

    try:
        quota = subprocess.run(
            [command, "quota", "show", "--output", "json", "--quiet", "--non-interactive"],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "warning", "mmx quota show timed out", {"command": command}
    except FileNotFoundError:
        return "warning", "mmx command not found", {"command": command}
    if quota.returncode != 0:
        return _mmx_probe_error(quota.returncode, quota.stderr or quota.stdout, command=command)

    return "ok", "mmx auth and quota probe passed", {"command": command, "auth": _safe_json(auth.stdout), "quota": _safe_json(quota.stdout)}


def probe_paddleocr_mcp(settings: Settings) -> tuple[CheckStatus, str, dict[str, object]]:
    try:
        import importlib.util

        installed = importlib.util.find_spec("paddleocr_mcp") is not None
    except Exception:
        installed = False
    token_present = bool(settings.paddleocr_mcp_access_token or os.environ.get("PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN"))
    base_url = (
        settings.paddleocr_mcp_base_url
        or os.environ.get("PADDLEOCR_MCP_AISTUDIO_BASE_URL")
        or os.environ.get("PADDLEOCR_MCP_SERVER_URL")
    )
    details: dict[str, object] = {
        "pipeline": settings.paddleocr_mcp_pipeline,
        "source": settings.paddleocr_mcp_source,
        "base_url": base_url or "default",
        "package": "present" if installed else "missing",
        "access_token": "present" if token_present else "missing",
    }
    if settings.vision_provider != "paddleocr_mcp":
        return "skipped", "PaddleOCR MCP not selected", details
    if settings.paddleocr_mcp_source == "self_hosted":
        if not base_url:
            return "error", "PaddleOCR self-hosted base URL missing", details
        return "ok", "PaddleOCR self-hosted endpoint configured", details
    if not installed:
        return "warning", "paddleocr-mcp package not installed in current Python environment", details
    if settings.paddleocr_mcp_source == "aistudio" and not token_present:
        return "error", "PaddleOCR MCP AI Studio access token missing", details
    return "ok", "PaddleOCR MCP configured", details


def probe_embedding_provider(settings: Settings, timeout: float = 10.0) -> tuple[CheckStatus, str, dict[str, object]]:
    """Independent embedding probe: sends a real embedding request to verify endpoint, model, and dimensions."""
    from ppt_lib.model_compat import probe_embedding

    if settings.embedding_provider == "fake":
        return "ok", "fake embedding provider", {}

    # Resolve endpoint — prefer unified field, fall back to legacy configs
    api_url = settings.embedding_api_url
    model = settings.embedding_model
    api_key = settings.embedding_api_key

    if not api_url:
        if settings.embedding_provider == "openai":
            api_url = "https://api.openai.com/v1"
            api_key = api_key or settings.openai_api_key
        elif settings.embedding_provider == "lmstudio":
            api_url = settings.lmstudio_base_url
            model = settings.lmstudio_embedding_model
        else:
            return "warning", f"Unknown embedding provider: {settings.embedding_provider}", {}

    if api_key:
        result = probe_embedding(api_url, model, settings.embedding_dimensions, timeout=timeout, api_key=api_key)
    else:
        result = probe_embedding(api_url, model, settings.embedding_dimensions, timeout=timeout)

    if result.status == "ok":
        return "ok", result.message, result.details
    return "warning", result.message, result.details


def _probe_json_models(
    url: str,
    timeout: float,
    *,
    configured_vision_model: str | None = None,
) -> tuple[CheckStatus, str, dict[str, object]]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return "warning", str(exc), {}

    model_ids = _extract_model_ids(payload)
    if configured_vision_model and configured_vision_model in model_ids:
        probe_status, probe_message, probe_details = _probe_lmstudio_image_capability(
            url.removesuffix("/models"),
            configured_vision_model,
            timeout,
        )
        details = {
            "models": payload,
            "configured_vision_model": configured_vision_model,
            "image_probe": probe_details,
        }
        if probe_status == "ok":
            return "ok", "configured vision model image probe passed", details
        return "warning", probe_message, details

    text = json.dumps(payload).lower()
    has_vision = any(token in text for token in ["vision", "llava", "bakllava", "moondream"])
    if has_vision:
        return "ok", "vision model available", {"models": payload}
    return "warning", "service available but no vision model detected", {"models": payload}


def _probe_lmstudio_image_capability(
    base_url: str,
    model: str,
    timeout: float,
) -> tuple[CheckStatus, str, dict[str, object]]:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is the dominant color in this image? Answer briefly."},
                    {"type": "image_url", "image_url": {"url": _RED_PIXEL_PNG_DATA_URL}},
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 64,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        message = f"configured vision model image probe failed: HTTP {exc.code}"
        if body:
            message = f"{message} - {body[:300]}"
        return "warning", message, {"error": message}
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        message = f"configured vision model image probe failed: {exc}"
        return "warning", message, {"error": str(exc)}

    content = _extract_chat_text(response_payload)
    if not content:
        return "warning", "configured vision model image probe returned no text", {"response": response_payload}
    return "ok", "configured vision model image probe passed", {"response_text": content[:200]}


def _extract_chat_text(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    from ppt_lib.model_compat import extract_chat_text

    return extract_chat_text(payload)


def _extract_model_ids(payload: object) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    raw_models = payload.get("data") or payload.get("models") or []
    if not isinstance(raw_models, list):
        return set()

    model_ids: set[str] = set()
    for model in raw_models:
        if not isinstance(model, dict):
            continue
        for key in ("id", "name", "model"):
            value = model.get(key)
            if isinstance(value, str) and value:
                model_ids.add(value)
    return model_ids


def _recommended_chain(settings: Settings, checks: list[DiagnosticCheck]) -> list[str]:
    by_name = {check.name: check for check in checks}
    chain: list[str] = []
    if settings.vision_provider == "ollama" and by_name.get("ollama") and by_name["ollama"].status == "ok":
        chain.append("ollama")
    elif settings.vision_provider == "lmstudio" and by_name.get("lmstudio") and by_name["lmstudio"].status == "ok":
        chain.append("lmstudio")
    elif settings.vision_provider == "cloud" and by_name.get("cloud_vision") and by_name["cloud_vision"].status == "ok":
        chain.append("cloud")
    elif settings.vision_provider == "mmx" and by_name.get("mmx") and by_name["mmx"].status == "ok":
        chain.append("mmx")
    elif settings.vision_provider == "paddleocr_mcp" and by_name.get("paddleocr_mcp") and by_name["paddleocr_mcp"].status == "ok":
        chain.append("paddleocr_mcp")
    elif settings.vision_provider == "auto":
        if by_name.get("mmx") and by_name["mmx"].status == "ok":
            chain.append("mmx")
        if by_name.get("ollama") and by_name["ollama"].status == "ok":
            chain.append("ollama")
        if by_name.get("lmstudio") and by_name["lmstudio"].status == "ok":
            chain.append("lmstudio")
        if by_name.get("cloud_vision") and by_name["cloud_vision"].status == "ok":
            chain.append("cloud")
    chain.append("text_extraction")
    return chain


def _diagnostic_chains(settings: Settings, checks: list[DiagnosticCheck]) -> dict[str, dict[str, object]]:
    by_name = {check.name: check for check in checks}
    lmstudio = by_name.get("lmstudio")
    ollama = by_name.get("ollama")
    openai_embedding = by_name.get("openai_embedding")
    cloud_vision = by_name.get("cloud_vision")
    mmx = by_name.get("mmx")
    paddleocr = by_name.get("paddleocr_mcp")
    embedding_probe = by_name.get("embedding_probe")

    # Use independent embedding probe when available
    if embedding_probe:
        embedding_status = embedding_probe.status
        embedding_message = embedding_probe.message
    elif settings.embedding_provider == "lmstudio":
        embedding_status = lmstudio.status if lmstudio else "warning"
        embedding_message = lmstudio.message if lmstudio else "LM Studio not checked"
    elif settings.embedding_provider == "openai":
        embedding_status = openai_embedding.status if openai_embedding else "error"
        embedding_message = openai_embedding.message if openai_embedding else "OpenAI embedding key not checked"
    else:
        embedding_status = "ok"
        embedding_message = f"{settings.embedding_provider} embedding provider configured"

    if settings.embedding_provider == "lmstudio":
        embedding_model = settings.lmstudio_embedding_model
    else:
        embedding_model = settings.embedding_model

    if settings.vision_provider == "lmstudio":
        vision_status = lmstudio.status if lmstudio else "warning"
        vision_message = lmstudio.message if lmstudio else "LM Studio not checked"
        vision_model = settings.lmstudio_vision_model
    elif settings.vision_provider == "ollama":
        vision_status = ollama.status if ollama else "warning"
        vision_message = ollama.message if ollama else "Ollama not checked"
        vision_model = settings.ollama_vision_model
    elif settings.vision_provider == "cloud":
        vision_status = cloud_vision.status if cloud_vision else "skipped"
        vision_message = cloud_vision.message if cloud_vision else "Cloud vision not configured"
        vision_model = settings.cloud_vision_model
    elif settings.vision_provider == "mmx":
        vision_status = mmx.status if mmx else "warning"
        vision_message = mmx.message if mmx else "mmx not checked"
        vision_model = settings.mmx_vision_model
    elif settings.vision_provider == "paddleocr_mcp":
        vision_status = paddleocr.status if paddleocr else "warning"
        vision_message = paddleocr.message if paddleocr else "PaddleOCR MCP not checked"
        vision_model = settings.paddleocr_mcp_pipeline
    elif settings.vision_provider == "text_extraction":
        vision_status = "skipped"
        vision_message = "Vision model disabled; text extraction only"
        vision_model = "text_extraction"
    else:
        local_ok = any(check and check.status == "ok" for check in [mmx, ollama, lmstudio])
        cloud_ok = cloud_vision is not None and cloud_vision.status == "ok"
        vision_status = "ok" if local_ok or cloud_ok else "warning"
        vision_message = "At least one vision provider available" if vision_status == "ok" else "No vision provider available"
        vision_model = "auto"
    if vision_status == "ok" and settings.vision_max_slides_per_file == 0:
        vision_status = "warning"
        vision_message = f"{vision_message}; vision_max_slides_per_file=0 disables vision calls during indexing"

    return {
        "embedding": {
            "provider": settings.embedding_provider,
            "model": embedding_model,
            "status": embedding_status,
            "message": embedding_message,
        },
        "vision": {
            "provider": settings.vision_provider,
            "model": vision_model,
            "status": vision_status,
            "message": vision_message,
        },
        "fallback": {
            "provider": "text_extraction",
            "model": "pptx_text",
            "status": "ok",
            "message": "Text extraction fallback is always available after PPTX text extraction.",
        },
    }


def _mmx_probe_error(returncode: int, output: str, *, command: str) -> tuple[CheckStatus, str, dict[str, object]]:
    status: CheckStatus = "error" if returncode in {3, 4} else "warning"
    label = {
        2: "usage error",
        3: "authentication error",
        4: "quota exceeded",
        5: "timeout",
        10: "content filter triggered",
    }.get(returncode, f"exit code {returncode}")
    detail = output.strip()
    message = f"mmx {label}"
    if detail:
        message = f"{message}: {detail[:300]}"
    return status, message, {"command": command, "exit_code": returncode}


def _safe_json(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()
