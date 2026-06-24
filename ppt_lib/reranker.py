"""Optional reranker with provider egress control (v1.6-D).

Supports local and cloud rerankers with strict egress policy:
cloud providers never receive data silently.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class RerankCandidate:
    """A candidate to be reranked."""

    slide_id: int
    title: str | None
    text: str
    score: float

    def to_json(self) -> dict[str, object]:
        return {
            "slide_id": self.slide_id,
            "title": self.title,
            "text": self.text[:200],
            "score": round(self.score, 4),
        }


@dataclass(frozen=True)
class RerankResult:
    """A reranked candidate with new score."""

    slide_id: int
    original_score: float
    rerank_score: float
    title: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "slide_id": self.slide_id,
            "original_score": round(self.original_score, 4),
            "rerank_score": round(self.rerank_score, 4),
            "title": self.title,
        }


@dataclass(frozen=True)
class EgressPolicy:
    """Controls whether data can be sent to external services."""

    allow_cloud_rerank: bool = False
    allow_cloud_embedding: bool = False
    allowed_cloud_providers: list[str] | None = None

    def can_use_cloud(self, provider: str = "default") -> bool:
        if not self.allow_cloud_rerank:
            return False
        if self.allowed_cloud_providers is not None:
            return provider in self.allowed_cloud_providers
        return True

    def to_json(self) -> dict[str, object]:
        return {
            "allow_cloud_rerank": self.allow_cloud_rerank,
            "allow_cloud_embedding": self.allow_cloud_embedding,
            "allowed_cloud_providers": self.allowed_cloud_providers,
        }


DEFAULT_EGRESS_POLICY = EgressPolicy(
    allow_cloud_rerank=False,
    allow_cloud_embedding=False,
)


class RerankerProvider(ABC):
    """Abstract interface for reranker providers."""

    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""

    @abstractmethod
    def is_local(self) -> bool:
        """Whether this provider runs locally (no data egress)."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider is ready."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int = 10,
    ) -> list[RerankResult]:
        """Rerank candidates. Returns top_n results with new scores."""


class NoopReranker(RerankerProvider):
    """Passthrough reranker that preserves original scores and order."""

    def name(self) -> str:
        return "noop"

    def is_local(self) -> bool:
        return True

    def is_available(self) -> bool:
        return True

    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int = 10,
    ) -> list[RerankResult]:
        results: list[RerankResult] = []
        for c in candidates[:top_n]:
            results.append(RerankResult(
                slide_id=c.slide_id,
                original_score=c.score,
                rerank_score=c.score,
                title=c.title,
            ))
        return results


class LengthBasedReranker(RerankerProvider):
    """Simple local reranker that boosts candidates with text length
    closer to query length. Useful as a baseline and for testing."""

    def name(self) -> str:
        return "length_baseline"

    def is_local(self) -> bool:
        return True

    def is_available(self) -> bool:
        return True

    def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_n: int = 10,
    ) -> list[RerankResult]:
        scored: list[RerankResult] = []
        query_len = len(query)

        for c in candidates:
            # Simple score: combine original score with text relevance heuristic
            text_len = len(c.text)
            # Boost candidates whose text length is proportional to query
            length_factor = 1.0 / (1.0 + abs(text_len - query_len * 10) / max(query_len * 10, 1))
            # Count query term occurrences
            term_count = sum(1 for term in query.lower().split() if term in c.text.lower())
            term_boost = min(term_count * 0.05, 0.3)

            new_score = c.score * 0.6 + length_factor * 0.2 + term_boost * 0.2
            scored.append(RerankResult(
                slide_id=c.slide_id,
                original_score=c.score,
                rerank_score=new_score,
                title=c.title,
            ))

        scored.sort(key=lambda r: r.rerank_score, reverse=True)
        return scored[:top_n]


def apply_rerank(
    query: str,
    candidates: list[RerankCandidate],
    *,
    provider: RerankerProvider | None = None,
    egress_policy: EgressPolicy | None = None,
    top_n: int = 10,
    timeout_seconds: float = 10.0,
) -> tuple[list[RerankResult], dict[str, object]]:
    """Apply reranking with egress policy enforcement.

    Returns (results, trace_info).
    """
    policy = egress_policy or DEFAULT_EGRESS_POLICY
    trace: dict[str, object] = {
        "provider": "none",
        "fallback_used": False,
        "egress": "none",
        "duration_ms": 0,
    }

    if provider is None:
        # No reranker configured — passthrough
        noop = NoopReranker()
        results = noop.rerank(query, candidates, top_n=top_n)
        trace["provider"] = "noop"
        trace["egress"] = "local"
        return results, trace

    # Check egress policy for cloud providers
    if not provider.is_local() and not policy.can_use_cloud(provider.name()):
        trace["provider"] = provider.name()
        trace["fallback_used"] = True
        trace["egress"] = "blocked"
        # Fall back to noop
        noop = NoopReranker()
        results = noop.rerank(query, candidates, top_n=top_n)
        return results, trace

    if not provider.is_available():
        trace["provider"] = provider.name()
        trace["fallback_used"] = True
        trace["egress"] = "unavailable"
        noop = NoopReranker()
        results = noop.rerank(query, candidates, top_n=top_n)
        return results, trace

    start = time.monotonic()
    try:
        results = provider.rerank(query, candidates, top_n=top_n)
        duration_ms = int((time.monotonic() - start) * 1000)
        trace["provider"] = provider.name()
        trace["egress"] = "local" if provider.is_local() else "cloud"
        trace["duration_ms"] = duration_ms
        return results, trace
    except Exception:
        duration_ms = int((time.monotonic() - start) * 1000)
        trace["provider"] = provider.name()
        trace["fallback_used"] = True
        trace["egress"] = "error"
        trace["duration_ms"] = duration_ms
        noop = NoopReranker()
        results = noop.rerank(query, candidates, top_n=top_n)
        return results, trace
