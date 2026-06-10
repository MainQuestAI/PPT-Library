from __future__ import annotations

import asyncio
import base64
import importlib
import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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


@dataclass(frozen=True)
class _PaddleOCRDocumentResult:
    markdown: str
    pages: int
    images_mapping: dict[str, object]


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


class MMXVisionProvider:
    name = "mmx"

    def __init__(
        self,
        *,
        command: str = "mmx",
        model: str = "default",
        quota_check: bool = True,
        quota_resume: bool = True,
        quota_max_resume_seconds: int = 21600,
        timeout_seconds: int = 30,
        max_image_bytes: int = 10_000_000,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.command = command
        self.model = model
        self.quota_check = quota_check
        self.quota_resume = quota_resume
        self.quota_max_resume_seconds = quota_max_resume_seconds
        self.timeout_seconds = timeout_seconds
        self.max_image_bytes = max_image_bytes
        self.sleeper = sleeper
        self.clock = clock

    def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult:
        _read_image_base64(image_path, self.max_image_bytes)
        if self.quota_check:
            self._resume_after_quota_limit(self._quota_wait_seconds())
        while True:
            completed = self._run(
                [
                    "vision",
                    "describe",
                    "--image",
                    str(image_path),
                    "--prompt",
                    _vision_prompt(fallback_text),
                    "--output",
                    "json",
                    "--quiet",
                    "--non-interactive",
                ]
            )
            if completed.returncode == 0:
                content = _extract_mmx_content(completed.stdout)
                return parse_vision_payload(content, fallback_text=fallback_text)
            if completed.returncode == 4 and self.quota_resume:
                wait_seconds = self._quota_wait_seconds()
                if wait_seconds is None:
                    wait_seconds = self.quota_max_resume_seconds
                self._resume_after_quota_limit(wait_seconds)
                continue
            raise VisionProviderError(
                _mmx_error_message(completed.returncode, completed.stderr or completed.stdout),
                code=_mmx_error_code(completed.returncode),
            )

    def _quota_wait_seconds(self) -> float | None:
        completed = self._run(["quota", "show", "--output", "json", "--quiet", "--non-interactive"])
        if completed.returncode != 0:
            if completed.returncode in {3, 4, 5}:
                raise VisionProviderError(
                    _mmx_error_message(completed.returncode, completed.stderr or completed.stdout),
                    code=_mmx_error_code(completed.returncode),
                )
            return None
        return _mmx_quota_wait_seconds(completed.stdout, now_seconds=self.clock())

    def _resume_after_quota_limit(self, wait_seconds: float | None) -> None:
        if wait_seconds is None or wait_seconds <= 0:
            return
        if not self.quota_resume:
            raise VisionProviderError(
                f"MMX quota is limited until {_format_resume_at(self.clock() + wait_seconds)}.",
                code="VISION_QUOTA_EXCEEDED",
            )
        if wait_seconds > self.quota_max_resume_seconds:
            raise VisionProviderError(
                (
                    f"MMX quota resumes at {_format_resume_at(self.clock() + wait_seconds)}, "
                    f"which exceeds max wait {self.quota_max_resume_seconds}s."
                ),
                code="VISION_QUOTA_EXCEEDED",
            )
        self.sleeper(wait_seconds)

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.command, *args],
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise VisionProviderError("mmx command was not found.", code="VISION_PROVIDER_UNAVAILABLE") from exc
        except subprocess.TimeoutExpired as exc:
            raise VisionProviderError("mmx command timed out.", code="VISION_TIMEOUT") from exc


class PaddleOCRMCPVisionProvider:
    name = "paddleocr_mcp"

    def __init__(
        self,
        *,
        pipeline: str = "PaddleOCR-VL-1.6",
        source: str = "aistudio",
        base_url: str | None = None,
        access_token: str | None = None,
        timeout_seconds: int = 30,
        max_image_bytes: int = 10_000_000,
        use_layout_detection: bool = True,
        use_chart_recognition: bool = True,
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
    ) -> None:
        self.pipeline = pipeline
        self.source = source
        self.base_url = base_url or os.environ.get("PADDLEOCR_MCP_AISTUDIO_BASE_URL") or os.environ.get("PADDLEOCR_MCP_SERVER_URL")
        self.access_token = access_token or os.environ.get("PADDLEOCR_MCP_AISTUDIO_ACCESS_TOKEN")
        self.timeout_seconds = timeout_seconds
        self.max_image_bytes = max_image_bytes
        self.runtime_params = {
            "use_layout_detection": use_layout_detection,
            "use_chart_recognition": use_chart_recognition,
            "use_doc_orientation_classify": use_doc_orientation_classify,
            "use_doc_unwarping": use_doc_unwarping,
        }

    def describe_slide(self, image_path: Path, fallback_text: str = "") -> VisionResult:
        _read_image_base64(image_path, self.max_image_bytes)
        result = self._predict(image_path)
        markdown = str(getattr(result, "markdown", "") or "").strip()
        if not markdown and fallback_text:
            markdown = fallback_text
        warnings = [] if markdown else ["VISION_EMPTY_CONTENT"]
        metadata: dict[str, object] = {
            "provider": self.name,
            "pipeline": self.pipeline,
            "source": self.source,
            "format": "markdown",
            "pages": int(getattr(result, "pages", 1) or 1),
            "raw_markdown": markdown,
        }
        images_mapping = getattr(result, "images_mapping", None)
        if isinstance(images_mapping, dict) and images_mapping:
            metadata["image_count"] = len(images_mapping)
        return VisionResult(
            source="vision_model",
            title=_markdown_title(markdown),
            text_content=markdown,
            metadata=metadata,
            confidence=0.8 if markdown else 0.0,
            warnings=warnings,
        )

    def _predict(self, image_path: Path) -> object:
        if self.source == "self_hosted":
            return self._predict_self_hosted(image_path)
        if self.source == "aistudio" and not self.access_token:
            raise VisionProviderError(
                "PaddleOCR MCP AI Studio access token is missing.",
                code="VISION_AUTH_MISSING",
            )
        try:
            return asyncio.run(self._predict_async(image_path))
        except VisionProviderError:
            raise
        except RuntimeError as exc:
            raise VisionProviderError(f"PaddleOCR MCP runtime error: {exc}", code="VISION_PROVIDER_UNAVAILABLE") from exc

    def _predict_self_hosted(self, image_path: Path) -> _PaddleOCRDocumentResult:
        if not self.base_url:
            raise VisionProviderError(
                "PaddleOCR self-hosted base URL is missing.",
                code="VISION_PROVIDER_UNAVAILABLE",
            )
        payload: dict[str, object] = {
            "file": _read_image_base64(image_path, self.max_image_bytes),
            "fileType": 1,
            "useDocOrientationClassify": self.runtime_params["use_doc_orientation_classify"],
            "useDocUnwarping": self.runtime_params["use_doc_unwarping"],
            "useLayoutDetection": self.runtime_params["use_layout_detection"],
            "useChartRecognition": self.runtime_params["use_chart_recognition"],
        }
        response = _post_json(
            f"{self.base_url.rstrip('/')}/layout-parsing",
            payload,
            timeout_seconds=self.timeout_seconds,
        )
        results = response.get("result", response)
        if not isinstance(results, dict):
            raise VisionProviderError("PaddleOCR self-hosted response is invalid.", code="VISION_INVALID_RESPONSE")
        pages = results.get("layoutParsingResults")
        if not isinstance(pages, list) or not pages:
            raise VisionProviderError("PaddleOCR self-hosted response has no parsed pages.", code="VISION_INVALID_RESPONSE")
        markdown_parts: list[str] = []
        images_mapping: dict[str, object] = {}
        for page in pages:
            if not isinstance(page, dict):
                continue
            markdown = page.get("markdown")
            if not isinstance(markdown, dict):
                continue
            text = markdown.get("text")
            if isinstance(text, str):
                markdown_parts.append(text)
            images = markdown.get("images")
            if isinstance(images, dict):
                images_mapping.update(images)
        return _PaddleOCRDocumentResult(
            markdown="\n".join(markdown_parts),
            pages=len(pages),
            images_mapping=images_mapping,
        )

    async def _predict_async(self, image_path: Path) -> object:
        try:
            inference_module = importlib.import_module("paddleocr_mcp.inference")
            types_module = importlib.import_module("paddleocr_mcp.inference.types")
        except ImportError as exc:
            raise VisionProviderError(
                "paddleocr-mcp is not installed in this Python environment. Run with `uv run --with paddleocr-mcp ...`.",
                code="VISION_PROVIDER_UNAVAILABLE",
            ) from exc
        create_inference = inference_module.create_inference
        inference_request = types_module.InferenceRequest
        kwargs: dict[str, object] = {
            "request_timeout": float(self.timeout_seconds),
            "poll_timeout": float(self.timeout_seconds * 10),
        }
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.source == "aistudio":
            kwargs["token"] = self.access_token
        inference = create_inference(self.pipeline, self.source, **kwargs)
        try:
            await inference.start()
            return await inference.predict(
                inference_request(
                    input_data=str(image_path),
                    file_type="image",
                    runtime_params=self.runtime_params,
                )
            )
        except Exception as exc:
            raise VisionProviderError(_paddleocr_error_message(exc), code=_paddleocr_error_code(exc)) from exc
        finally:
            await inference.stop()


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
    if settings.vision_provider in {"auto", "mmx"}:
        chain.append(
            MMXVisionProvider(
                command=settings.mmx_command,
                model=settings.mmx_vision_model,
                quota_check=settings.mmx_quota_check,
                quota_resume=settings.mmx_quota_resume,
                quota_max_resume_seconds=settings.mmx_quota_max_resume_seconds,
                timeout_seconds=settings.vision_timeout_seconds,
                max_image_bytes=settings.vision_max_image_bytes,
            )
        )
    if settings.vision_provider == "paddleocr_mcp":
        chain.append(
            PaddleOCRMCPVisionProvider(
                pipeline=settings.paddleocr_mcp_pipeline,
                source=settings.paddleocr_mcp_source,
                base_url=settings.paddleocr_mcp_base_url,
                access_token=settings.paddleocr_mcp_access_token,
                timeout_seconds=settings.vision_timeout_seconds,
                max_image_bytes=settings.vision_max_image_bytes,
                use_layout_detection=settings.paddleocr_mcp_use_layout_detection,
                use_chart_recognition=settings.paddleocr_mcp_use_chart_recognition,
                use_doc_orientation_classify=settings.paddleocr_mcp_use_doc_orientation_classify,
                use_doc_unwarping=settings.paddleocr_mcp_use_doc_unwarping,
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
            if settings.vision_provider == "paddleocr_mcp" and getattr(provider, "name", "") == "paddleocr_mcp":
                raise
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
        "Return only one valid JSON object. Do not wrap it in markdown. Do not add explanation. "
        "Use exactly these top-level keys: title, text_content, metadata, confidence. "
        "title may be null. text_content must be a compact but complete description of visible text, charts, layout, "
        "business meaning, and reusable sales/solution context. "
        "metadata must be a JSON object with useful tags such as layout_type, chart_types, business_domain, "
        "key_entities, visual_elements, use_cases, business_meaning, visual_notes, and language when visible. "
        "confidence must be a number between 0 and 1. "
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


def _extract_mmx_content(raw_stdout: str) -> str:
    raw = raw_stdout.strip()
    if not raw:
        raise VisionProviderError("mmx returned empty output.", code="VISION_INVALID_RESPONSE")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return raw
    for key in ("content", "text", "description", "response", "answer", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    try:
        text = _extract_chat_content(payload)
    except VisionProviderError:
        text = ""
    if text.strip():
        return text
    return raw


def _markdown_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:120]
    return None


def _paddleocr_error_code(exc: Exception) -> str:
    name = type(exc).__name__
    detail = str(exc)
    if "Auth" in name or "Unauthorized" in detail:
        return "VISION_AUTH_MISSING"
    if "Timeout" in name:
        return "VISION_TIMEOUT"
    if "ServiceUnavailable" in name or "503" in detail:
        return "VISION_PROVIDER_UNAVAILABLE"
    if "JobFailed" in name or "APIError" in name:
        return "VISION_PROVIDER_ERROR"
    return "VISION_PROVIDER_UNAVAILABLE"


def _paddleocr_error_message(exc: Exception) -> str:
    detail = str(exc).strip()
    return f"PaddleOCR MCP failed: {detail[:500]}" if detail else f"PaddleOCR MCP failed: {type(exc).__name__}"


def _mmx_error_code(returncode: int) -> str:
    return {
        2: "VISION_USAGE_ERROR",
        3: "VISION_AUTH_MISSING",
        4: "VISION_QUOTA_EXCEEDED",
        5: "VISION_TIMEOUT",
        10: "VISION_CONTENT_FILTER",
    }.get(returncode, "VISION_PROVIDER_UNAVAILABLE")


def _mmx_error_message(returncode: int, output: str) -> str:
    detail = output.strip()
    prefix = {
        2: "mmx usage error",
        3: "mmx authentication error",
        4: "mmx quota exceeded",
        5: "mmx request timed out",
        10: "mmx content filter triggered",
    }.get(returncode, f"mmx failed with exit code {returncode}")
    return f"{prefix}: {detail[:500]}" if detail else prefix


def _mmx_quota_wait_seconds(raw_stdout: str, *, now_seconds: float) -> float | None:
    try:
        payload = json.loads(raw_stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    remains = payload.get("model_remains")
    if not isinstance(remains, list):
        return None
    waits: list[float] = []
    for item in remains:
        if not isinstance(item, dict):
            continue
        model_name = str(item.get("model_name") or "").lower()
        if model_name and model_name not in {"general", "vision", "vlm", "image"}:
            continue
        percent = item.get("current_interval_remaining_percent")
        total = item.get("current_interval_total_count")
        used = item.get("current_interval_usage_count")
        exhausted_by_percent = isinstance(percent, (int, float)) and percent <= 0
        exhausted_by_count = (
            isinstance(total, (int, float))
            and isinstance(used, (int, float))
            and total > 0
            and used >= total
        )
        if not exhausted_by_percent and not exhausted_by_count:
            continue
        wait_seconds = _quota_item_wait_seconds(item, now_seconds=now_seconds)
        if wait_seconds is not None:
            waits.append(wait_seconds)
    return max(waits) if waits else None


def _quota_item_wait_seconds(item: dict[str, object], *, now_seconds: float) -> float | None:
    remains_time = item.get("remains_time")
    if isinstance(remains_time, (int, float)) and remains_time > 0:
        return float(remains_time) / 1000.0
    end_time = item.get("end_time")
    if isinstance(end_time, (int, float)) and end_time > 0:
        return max(0.0, float(end_time) / 1000.0 - now_seconds)
    return None


def _format_resume_at(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, UTC).isoformat()
