from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import numpy as np

from ppt_lib.settings import Settings


class EmbeddingProvider(Protocol):
    model: str
    dimensions: int

    def encode(self, text: str) -> np.ndarray: ...

    def encode_batch(self, texts: Sequence[str]) -> list[np.ndarray]: ...


class EmbeddingProviderError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class EmbeddingAuthMissingError(EmbeddingProviderError):
    def __init__(self) -> None:
        super().__init__(
            "OpenAI API key is required for embedding provider.",
            code="EMBEDDING_AUTH_MISSING",
            retryable=False,
        )


class EmbeddingDimensionError(EmbeddingProviderError):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            f"Embedding dimension mismatch: expected {expected}, got {actual}.",
            code="EMBEDDING_DIMENSION_MISMATCH",
            retryable=False,
        )


Transport = Callable[[dict[str, Any], str], dict[str, Any]]
Sleep = Callable[[float], None]


class FakeEmbeddingProvider:
    model = "fake"

    def __init__(self, dimensions: int = 1536) -> None:
        self.dimensions = dimensions

    def encode(self, text: str) -> np.ndarray:
        normalized = _normalize_text(text)
        seed = hashlib.sha256(normalized.encode("utf-8")).digest()
        values = np.frombuffer((seed * ((self.dimensions // len(seed)) + 1))[: self.dimensions], dtype=np.uint8)
        vector = values.astype(np.float32) / 255.0
        return vector

    def encode_batch(self, texts: Sequence[str]) -> list[np.ndarray]:
        return [self.encode(text) for text in texts]


class UnifiedEmbeddingProvider:
    """OpenAI-compatible /v1/embeddings endpoint provider.

    Accepts any service that implements the OpenAI embeddings API:
    - OpenAI official (https://api.openai.com/v1)
    - LM Studio (http://127.0.0.1:1234/v1)
    - Ollama (http://127.0.0.1:11434/v1)
    - Third-party APIs (Infini AI, DeepSeek, etc.)
    """

    def __init__(
        self,
        *,
        api_url: str,
        model: str,
        dimensions: int = 1536,
        api_key: str | None = None,
        timeout_seconds: int = 30,
        transport: Transport | None = None,
        sleep: Sleep = time.sleep,
    ) -> None:
        self.endpoint = f"{api_url.rstrip('/')}/embeddings"
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key
        self._transport = transport or self._default_transport
        self._sleep = sleep

    def encode(self, text: str) -> np.ndarray:
        payload = {"model": self.model, "input": _normalize_text(text)}
        response = self._with_retries(payload)
        return _vector_from_response(response, self.dimensions)

    def encode_batch(self, texts: Sequence[str]) -> list[np.ndarray]:
        return [self.encode(text) for text in texts]

    def _with_retries(self, payload: dict[str, Any]) -> dict[str, Any]:
        attempts = 0
        while True:
            attempts += 1
            try:
                return self._transport(payload, self.api_key or "")
            except TimeoutError as exc:
                if attempts >= 3:
                    raise EmbeddingProviderError(
                        "Embedding provider timed out after retries.",
                        code="EMBEDDING_TIMEOUT",
                        retryable=True,
                    ) from exc
                self._sleep(0.2 * attempts)
            except EmbeddingProviderError as exc:
                if not exc.retryable or attempts >= 3:
                    raise
                self._sleep(0.2 * attempts)

    def _default_transport(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return _post_json(self.endpoint, payload=payload, timeout_seconds=self.timeout_seconds, headers=headers)




def _post_json(
    url: str,
    *,
    payload: dict[str, Any],
    timeout_seconds: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        retryable = exc.code == 429 or exc.code >= 500
        code = "EMBEDDING_RATE_LIMIT" if exc.code == 429 else "EMBEDDING_HTTP_ERROR"
        raise EmbeddingProviderError(str(exc), code=code, retryable=retryable) from exc
    except TimeoutError:
        raise
    except OSError as exc:
        raise EmbeddingProviderError(
            str(exc),
            code="EMBEDDING_NETWORK_ERROR",
            retryable=True,
        ) from exc
    if not isinstance(decoded, dict):
        raise EmbeddingProviderError(
            "Embedding provider returned an invalid response.",
            code="EMBEDDING_INVALID_RESPONSE",
            retryable=False,
        )
    return decoded


def _vector_from_response(response: dict[str, Any], dimensions: int) -> np.ndarray:
    try:
        embedding = response["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise EmbeddingProviderError(
            "Embedding provider returned an invalid response.",
            code="EMBEDDING_INVALID_RESPONSE",
            retryable=False,
        ) from exc
    vector = np.asarray(embedding, dtype=np.float32)
    if vector.shape != (dimensions,):
        actual = int(vector.shape[0]) if vector.ndim else 0
        raise EmbeddingDimensionError(dimensions, actual)
    return vector


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider(dimensions=settings.embedding_dimensions)

    # Use unified endpoint when available, fall back to legacy provider config
    api_url = settings.embedding_api_url
    api_key = settings.embedding_api_key
    model = settings.embedding_model

    if not api_url:
        if settings.embedding_provider == "openai":
            api_url = "https://api.openai.com/v1"
            api_key = api_key or settings.openai_api_key
        elif settings.embedding_provider == "lmstudio":
            api_url = settings.lmstudio_base_url
            model = settings.lmstudio_embedding_model
        else:
            raise EmbeddingProviderError(
                f"Unsupported embedding provider: {settings.embedding_provider}",
                code="EMBEDDING_PROVIDER_UNSUPPORTED",
                retryable=False,
            )

    return UnifiedEmbeddingProvider(
        api_url=api_url,
        model=model,
        dimensions=settings.embedding_dimensions,
        api_key=api_key,
        timeout_seconds=settings.embedding_timeout_seconds,
    )


def _normalize_text(text: str) -> str:
    normalized = text.strip()
    return normalized if normalized else " "
