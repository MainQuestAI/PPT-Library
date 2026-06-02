from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ppt_lib.settings import Settings

VisionSource = Literal["vision_model", "text_extraction", "hybrid"]


class VisionProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VisionResult:
    source: VisionSource
    title: str | None
    text_content: str
    metadata: dict[str, object]
    confidence: float
    warnings: list[str]


class VisionProvider(Protocol):
    def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult: ...


class OllamaVisionProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "llava",
        timeout_seconds: int = 30,
        max_image_bytes: int = 10_000_000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_image_bytes = max_image_bytes

    def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult:
        image_base64 = _read_image_base64(image_path, self.max_image_bytes)
        payload = {
            "model": self.model,
            "prompt": _vision_prompt(fallback_text),
            "images": [image_base64],
            "stream": False,
            "format": "json",
        }
        response = _post_json(f"{self.base_url}/api/generate", payload, timeout_seconds=self.timeout_seconds)
        content = response.get("response")
        if not isinstance(content, str):
            raise VisionProviderError("Ollama returned no response text.", code="VISION_INVALID_RESPONSE")
        return parse_vision_payload(content, fallback_text=fallback_text)


class LMStudioVisionProvider:
    name = "lmstudio"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:1234/v1",
        model: str = "",
        timeout_seconds: int = 30,
        max_image_bytes: int = 10_000_000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_image_bytes = max_image_bytes

    def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult:
        if not self.model:
            raise VisionProviderError("LM Studio vision model is not configured.", code="VISION_MODEL_NOT_CONFIGURED")
        data_url = _read_image_data_url(image_path, self.max_image_bytes)
        url = f"{self.base_url}/chat/completions"
        try:
            response = _post_json(
                url,
                _lmstudio_compatible_payload(self.model, data_url, fallback_text),
                timeout_seconds=self.timeout_seconds,
            )
            content = _extract_chat_content(response)
            return parse_vision_payload(content, fallback_text=fallback_text)
        except VisionProviderError as exc:
            first_error = exc
        payload = _openai_compatible_payload(self.model, data_url, fallback_text)
        payload["response_format"] = {"type": "text"}
        response = _post_json(url, payload, timeout_seconds=self.timeout_seconds)
        content = _extract_chat_content(response)
        result = parse_vision_payload(content, fallback_text=fallback_text)
        return VisionResult(
            source=result.source,
            title=result.title,
            text_content=result.text_content,
            metadata=result.metadata,
            confidence=result.confidence,
            warnings=[f"VISION_FORMAT_FALLBACK: {first_error.code}: {first_error}"] + result.warnings,
        )


class CloudVisionProvider:
    name = "cloud"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout_seconds: int = 30,
        max_image_bytes: int = 10_000_000,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_image_bytes = max_image_bytes

    def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult:
        if not self.api_key:
            raise VisionProviderError("Cloud vision API key is missing.", code="VISION_AUTH_MISSING")
        data_url = _read_image_data_url(image_path, self.max_image_bytes)
        payload = _openai_compatible_payload(self.model, data_url, fallback_text)
        response = _post_json(
            f"{self.base_url}/chat/completions",
            payload,
            timeout_seconds=self.timeout_seconds,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        content = _extract_chat_content(response)
        return parse_vision_payload(content, fallback_text=fallback_text)


class TextExtractionVisionProvider:
    name = "text_extraction"

    def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult:
        warnings = [] if fallback_text else ["VISION_EMPTY_CONTENT"]
        return VisionResult(
            source="text_extraction",
            title=None,
            text_content=fallback_text,
            metadata={},
            confidence=0.2 if fallback_text else 0.0,
            warnings=warnings,
        )


def build_vision_chain(settings: Settings) -> list[VisionProvider]:
    chain: list[VisionProvider] = []
    if settings.vision_provider in {"auto", "ollama"}:
        chain.append(
            OllamaVisionProvider(
                base_url=settings.ollama_base_url,
                model=settings.ollama_vision_model,
                timeout_seconds=settings.vision_timeout_seconds,
                max_image_bytes=settings.vision_max_image_bytes,
            )
        )
    if settings.vision_provider in {"auto", "lmstudio"}:
        chain.append(
            LMStudioVisionProvider(
                base_url=settings.lmstudio_base_url,
                model=settings.lmstudio_vision_model,
                timeout_seconds=settings.vision_timeout_seconds,
                max_image_bytes=settings.vision_max_image_bytes,
            )
        )
    if settings.vision_provider in {"auto", "cloud"} and settings.vision_api_key:
        chain.append(
            CloudVisionProvider(
                settings.vision_api_key,
                base_url=settings.cloud_vision_base_url,
                model=settings.cloud_vision_model,
                timeout_seconds=settings.vision_timeout_seconds,
                max_image_bytes=settings.vision_max_image_bytes,
            )
        )
    chain.append(TextExtractionVisionProvider())
    return chain


def describe_slide_with_fallback(image_path: Path, fallback_text: str, settings: Settings) -> VisionResult:
    warnings: list[str] = []
    for provider in build_vision_chain(settings):
        try:
            result = provider.describe_slide(image_path, fallback_text)
        except VisionProviderError as exc:
            warnings.append(f"{exc.code}: {exc}")
            continue
        except OSError as exc:
            warnings.append(f"VISION_PROVIDER_OS_ERROR: {exc}")
            continue
        return VisionResult(
            source=result.source,
            title=result.title,
            text_content=result.text_content,
            metadata=result.metadata,
            confidence=_clamp_confidence(result.confidence),
            warnings=warnings + result.warnings,
        )
    fallback = TextExtractionVisionProvider().describe_slide(image_path, fallback_text)
    return VisionResult(
        source=fallback.source,
        title=fallback.title,
        text_content=fallback.text_content,
        metadata=fallback.metadata,
        confidence=fallback.confidence,
        warnings=warnings + fallback.warnings,
    )


def parse_vision_payload(payload: str, fallback_text: str = "") -> VisionResult:
    warnings: list[str] = []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return VisionResult(
            source="vision_model",
            title=None,
            text_content=payload.strip() or fallback_text,
            metadata={},
            confidence=0.5 if payload.strip() else 0.2,
            warnings=["VISION_INVALID_JSON"],
        )
    if not isinstance(data, dict):
        return VisionResult(
            source="vision_model",
            title=None,
            text_content=fallback_text,
            metadata={"raw_payload": data},
            confidence=0.2 if fallback_text else 0.0,
            warnings=["VISION_INVALID_JSON"],
        )

    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {"raw_metadata": metadata}
        warnings.append("VISION_METADATA_TYPE_COERCED")

    text_content = str(data.get("text_content") or fallback_text or "")
    if not text_content:
        warnings.append("VISION_EMPTY_CONTENT")

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
        warnings.append("VISION_CONFIDENCE_TYPE_COERCED")

    return VisionResult(
        source="vision_model",
        title=str(data["title"]) if data.get("title") is not None else None,
        text_content=text_content,
        metadata=metadata,
        confidence=_clamp_confidence(confidence),
        warnings=warnings,
    )


def _clamp_confidence(value: float) -> float:
    return min(1.0, max(0.0, value))


def _post_json(
    url: str,
    payload: dict[str, object],
    *,
    timeout_seconds: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=request_headers, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        detail = f"HTTP {exc.code}: {exc.reason}"
        if body:
            detail = f"{detail} - {body[:500]}"
        raise VisionProviderError(detail, code="VISION_HTTP_ERROR") from exc
    except URLError as exc:
        raise VisionProviderError(str(exc.reason), code="VISION_PROVIDER_UNAVAILABLE") from exc
    except TimeoutError as exc:
        raise VisionProviderError("Vision provider request timed out.", code="VISION_TIMEOUT") from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VisionProviderError("Vision provider returned invalid JSON envelope.", code="VISION_INVALID_RESPONSE") from exc
    if not isinstance(decoded, dict):
        raise VisionProviderError("Vision provider returned non-object JSON envelope.", code="VISION_INVALID_RESPONSE")
    return decoded


def _read_image_base64(image_path: Path, max_image_bytes: int) -> str:
    if not image_path.exists():
        raise VisionProviderError(f"Image does not exist: {image_path}", code="VISION_IMAGE_MISSING")
    if image_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise VisionProviderError(f"Unsupported image type: {image_path.suffix}", code="VISION_IMAGE_UNSUPPORTED")
    size = image_path.stat().st_size
    if size > max_image_bytes:
        raise VisionProviderError(f"Image is too large: {size} bytes", code="VISION_IMAGE_TOO_LARGE")
    data = image_path.read_bytes()
    if image_path.suffix.lower() == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise VisionProviderError("PNG image header is invalid.", code="VISION_IMAGE_INVALID")
    if image_path.suffix.lower() in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8"):
        raise VisionProviderError("JPEG image header is invalid.", code="VISION_IMAGE_INVALID")
    return base64.b64encode(data).decode("ascii")


def _read_image_data_url(image_path: Path, max_image_bytes: int) -> str:
    mime = "image/jpeg" if image_path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64,{_read_image_base64(image_path, max_image_bytes)}"


def _vision_prompt(fallback_text: str) -> str:
    return (
        "Describe this presentation slide as compact JSON with keys title, text_content, metadata, confidence. "
        "metadata should be an object with layout_type, chart_types, business_domain, key_entities, "
        "visual_elements, use_cases, and language when visible. "
        f"Fallback extracted text: {fallback_text}"
    )


def _openai_compatible_payload(model: str, data_url: str, fallback_text: str) -> dict[str, object]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _vision_prompt(fallback_text)},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }


def _lmstudio_compatible_payload(model: str, data_url: str, fallback_text: str) -> dict[str, object]:
    payload = _openai_compatible_payload(model, data_url, fallback_text)
    payload["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "slide_description",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "text_content": {"type": "string"},
                    "metadata": {"type": "object"},
                    "confidence": {"type": "number"},
                },
                "required": ["title", "text_content", "metadata", "confidence"],
                "additionalProperties": False,
            },
        },
    }
    return payload


def _extract_chat_content(response: dict[str, Any]) -> str:
    from ppt_lib.model_compat import extract_chat_text

    text = extract_chat_text(response)
    if not text and text != "":
        raise VisionProviderError("Chat provider returned no choices.", code="VISION_INVALID_RESPONSE")
    # If extract_chat_text returned "" and there were no choices at all, raise
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise VisionProviderError("Chat provider returned no choices.", code="VISION_INVALID_RESPONSE")
    if not text.strip():
        # Check if reasoning_content was used (already handled by extract_chat_text)
        # If truly empty, raise
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                # extract_chat_text already checked reasoning_content
                if not message.get("content") and not message.get("reasoning_content"):
                    raise VisionProviderError("Chat provider returned no message content.", code="VISION_INVALID_RESPONSE")
    return text
