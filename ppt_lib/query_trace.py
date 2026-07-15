"""Query trace and explainability (v1.6-E).

Every search produces a reproducible trace with full provenance:
backend counts, timings, model versions, fallback, and score breakdown.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class QueryTrace:
    """Full provenance trace for a single search execution."""

    query_trace_id: str
    request_id: str
    query: str
    profile_name: str
    profile_version: str
    generated_at: str
    duration_ms: int
    lexical_backend: LexicalBackendTrace
    vector_backend: VectorBackendTrace
    fusion: FusionTrace
    reranker: RerankerTrace | None
    fallback: FallbackTrace | None
    warnings: list[dict[str, str]] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {
            "query_trace_id": self.query_trace_id,
            "request_id": self.request_id,
            "query": self.query,
            "profile_name": self.profile_name,
            "profile_version": self.profile_version,
            "generated_at": self.generated_at,
            "duration_ms": self.duration_ms,
            "lexical_backend": self.lexical_backend.to_json(),
            "vector_backend": self.vector_backend.to_json(),
            "fusion": self.fusion.to_json(),
        }
        if self.reranker:
            d["reranker"] = self.reranker.to_json()
        if self.fallback:
            d["fallback"] = self.fallback.to_json()
        if self.warnings:
            d["warnings"] = self.warnings
        return d


@dataclass(frozen=True)
class LexicalBackendTrace:
    """Trace for the lexical (FTS5) backend."""

    backend_name: str
    candidate_count: int
    duration_ms: int
    fts_document_count: int
    query_sanitized: str

    def to_json(self) -> dict[str, object]:
        return {
            "backend_name": self.backend_name,
            "candidate_count": self.candidate_count,
            "duration_ms": self.duration_ms,
            "fts_document_count": self.fts_document_count,
            "query_sanitized": self.query_sanitized,
        }


@dataclass(frozen=True)
class VectorBackendTrace:
    """Trace for the vector backend."""

    backend_name: str
    candidate_count: int
    duration_ms: int
    index_count: int
    dimension: int | None
    model_version: str | None
    available: bool
    reason: str | None = None

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {
            "backend_name": self.backend_name,
            "candidate_count": self.candidate_count,
            "duration_ms": self.duration_ms,
            "index_count": self.index_count,
            "dimension": self.dimension,
            "model_version": self.model_version,
            "available": self.available,
        }
        if self.reason:
            d["reason"] = self.reason
        return d


@dataclass(frozen=True)
class FusionTrace:
    """Trace for the fusion step."""

    method: str
    rrf_k: int
    input_lexical_count: int
    input_vector_count: int
    output_count: int
    duration_ms: int

    def to_json(self) -> dict[str, object]:
        return {
            "method": self.method,
            "rrf_k": self.rrf_k,
            "input_lexical_count": self.input_lexical_count,
            "input_vector_count": self.input_vector_count,
            "output_count": self.output_count,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class RerankerTrace:
    """Trace for optional reranker."""

    provider: str
    model: str | None
    input_count: int
    output_count: int
    duration_ms: int
    egress: str  # "local" | "cloud" | "none"
    fallback_used: bool

    def to_json(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_count": self.input_count,
            "output_count": self.output_count,
            "duration_ms": self.duration_ms,
            "egress": self.egress,
            "fallback_used": self.fallback_used,
        }


@dataclass(frozen=True)
class FallbackTrace:
    """Trace when a backend fell back to a degraded mode."""

    backend: str
    original: str
    fallback: str
    reason: str

    def to_json(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "original": self.original,
            "fallback": self.fallback,
            "reason": self.reason,
        }


def new_trace_id() -> str:
    """Generate a new query trace ID."""
    return f"qt_{uuid.uuid4().hex[:16]}"


def new_request_id() -> str:
    """Generate a new request ID."""
    return f"req_{uuid.uuid4().hex[:12]}"


class TraceBuilder:
    """Builder for constructing query traces during search execution."""

    def __init__(
        self,
        query: str,
        profile_name: str,
        profile_version: str,
        *,
        request_id: str | None = None,
    ) -> None:
        self._query = query
        self._profile_name = profile_name
        self._profile_version = profile_version
        self._trace_id = new_trace_id()
        self._request_id = request_id or new_request_id()
        self._start_time = time.monotonic()
        self._lexical_trace: LexicalBackendTrace | None = None
        self._vector_trace: VectorBackendTrace | None = None
        self._fusion_trace: FusionTrace | None = None
        self._reranker_trace: RerankerTrace | None = None
        self._fallback_trace: FallbackTrace | None = None
        self._warnings: list[dict[str, str]] = []

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def request_id(self) -> str:
        return self._request_id

    def set_lexical_trace(self, trace: LexicalBackendTrace) -> None:
        self._lexical_trace = trace

    def set_vector_trace(self, trace: VectorBackendTrace) -> None:
        self._vector_trace = trace

    def set_fusion_trace(self, trace: FusionTrace) -> None:
        self._fusion_trace = trace

    def set_reranker_trace(self, trace: RerankerTrace) -> None:
        self._reranker_trace = trace

    def set_fallback_trace(self, trace: FallbackTrace) -> None:
        self._fallback_trace = trace

    def add_warning(self, code: str, message: str) -> None:
        self._warnings.append({"code": code, "message": message})

    def build(self) -> QueryTrace:
        duration_ms = int((time.monotonic() - self._start_time) * 1000)
        return QueryTrace(
            query_trace_id=self._trace_id,
            request_id=self._request_id,
            query=self._query,
            profile_name=self._profile_name,
            profile_version=self._profile_version,
            generated_at=datetime.now(UTC).isoformat(),
            duration_ms=duration_ms,
            lexical_backend=self._lexical_trace or LexicalBackendTrace(
                backend_name="none",
                candidate_count=0,
                duration_ms=0,
                fts_document_count=0,
                query_sanitized="",
            ),
            vector_backend=self._vector_trace or VectorBackendTrace(
                backend_name="none",
                candidate_count=0,
                duration_ms=0,
                index_count=0,
                dimension=None,
                model_version=None,
                available=False,
                reason="not configured",
            ),
            fusion=self._fusion_trace or FusionTrace(
                method="none",
                rrf_k=0,
                input_lexical_count=0,
                input_vector_count=0,
                output_count=0,
                duration_ms=0,
            ),
            reranker=self._reranker_trace,
            fallback=self._fallback_trace,
            warnings=self._warnings,
        )
