"""Tests for reranker and egress policy (v1.6-D)."""

from __future__ import annotations

import time

from ppt_lib.reranker import (
    DEFAULT_EGRESS_POLICY,
    EgressPolicy,
    LengthBasedReranker,
    NoopReranker,
    RerankCandidate,
    RerankerProvider,
    RerankResult,
    apply_rerank,
)


class TestRerankCandidate:
    def test_to_json(self):
        c = RerankCandidate(slide_id=1, title="Test", text="Some text", score=0.9)
        j = c.to_json()
        assert j["slide_id"] == 1
        assert j["score"] == 0.9


class TestRerankResult:
    def test_to_json(self):
        r = RerankResult(slide_id=1, original_score=0.8, rerank_score=0.95, title="Test")
        j = r.to_json()
        assert j["original_score"] == 0.8
        assert j["rerank_score"] == 0.95


class TestEgressPolicy:
    def test_default_policy_blocks_cloud(self):
        policy = DEFAULT_EGRESS_POLICY
        assert policy.can_use_cloud() is False

    def test_allow_cloud(self):
        policy = EgressPolicy(allow_cloud_rerank=True)
        assert policy.can_use_cloud() is True

    def test_allowed_providers_filter(self):
        policy = EgressPolicy(
            allow_cloud_rerank=True,
            allowed_cloud_providers=["cohere"],
        )
        assert policy.can_use_cloud("cohere") is True
        assert policy.can_use_cloud("openai") is False

    def test_to_json(self):
        j = DEFAULT_EGRESS_POLICY.to_json()
        assert j["allow_cloud_rerank"] is False


class TestNoopReranker:
    def test_preserves_order(self):
        reranker = NoopReranker()
        candidates = [
            RerankCandidate(1, "A", "text a", 0.9),
            RerankCandidate(2, "B", "text b", 0.8),
        ]
        results = reranker.rerank("query", candidates)
        assert len(results) == 2
        assert results[0].slide_id == 1
        assert results[0].rerank_score == 0.9

    def test_respects_top_n(self):
        reranker = NoopReranker()
        candidates = [RerankCandidate(i, f"T{i}", f"text {i}", 0.5) for i in range(10)]
        results = reranker.rerank("query", candidates, top_n=3)
        assert len(results) == 3

    def test_is_local(self):
        assert NoopReranker().is_local() is True
        assert NoopReranker().is_available() is True


class TestLengthBasedReranker:
    def test_reranks_candidates(self):
        reranker = LengthBasedReranker()
        candidates = [
            RerankCandidate(1, "Architecture", "This describes the system architecture with microservices", 0.8),
            RerankCandidate(2, "ML", "Deep learning", 0.9),
        ]
        results = reranker.rerank("architecture", candidates)
        assert len(results) == 2
        # Both should have rerank scores
        assert all(r.rerank_score > 0 for r in results)

    def test_is_local(self):
        assert LengthBasedReranker().is_local() is True


class TestApplyRerank:
    def _make_candidates(self) -> list[RerankCandidate]:
        return [
            RerankCandidate(1, "A", "text about architecture", 0.9),
            RerankCandidate(2, "B", "text about ML", 0.8),
            RerankCandidate(3, "C", "text about data", 0.7),
        ]

    def test_no_provider_passthrough(self):
        results, trace = apply_rerank("query", self._make_candidates())
        assert len(results) == 3
        assert trace["provider"] == "noop"
        assert trace["fallback_used"] is False

    def test_local_provider(self):
        results, trace = apply_rerank(
            "architecture",
            self._make_candidates(),
            provider=LengthBasedReranker(),
        )
        assert len(results) <= 3
        assert trace["provider"] == "length_baseline"
        assert trace["egress"] == "local"

    def test_cloud_blocked_by_policy(self):
        """Cloud reranker blocked by default egress policy."""

        class FakeCloudReranker(RerankerProvider):
            def name(self) -> str:
                return "fake_cloud"

            def is_local(self) -> bool:
                return False

            def is_available(self) -> bool:
                return True

            def rerank(self, query, candidates, *, top_n=10):
                return [
                    RerankResult(c.slide_id, c.score, 1.0, c.title)
                    for c in candidates[:top_n]
                ]

        results, trace = apply_rerank(
            "query",
            self._make_candidates(),
            provider=FakeCloudReranker(),
        )
        assert trace["fallback_used"] is True
        assert trace["egress"] == "blocked"

    def test_cloud_allowed_by_policy(self):

        class FakeCloudReranker(RerankerProvider):
            def name(self) -> str:
                return "fake_cloud"

            def is_local(self) -> bool:
                return False

            def is_available(self) -> bool:
                return True

            def rerank(self, query, candidates, *, top_n=10):
                return [
                    RerankResult(c.slide_id, c.score, 1.0, c.title)
                    for c in candidates[:top_n]
                ]

        policy = EgressPolicy(
            allow_cloud_rerank=True,
            allowed_cloud_providers=["fake_cloud"],
        )
        results, trace = apply_rerank(
            "query",
            self._make_candidates(),
            provider=FakeCloudReranker(),
            egress_policy=policy,
        )
        assert trace["provider"] == "fake_cloud"
        assert trace["egress"] == "cloud"
        assert trace["fallback_used"] is False

    def test_provider_unavailable_fallback(self):

        class UnavailableReranker(RerankerProvider):
            def name(self) -> str:
                return "unavailable"

            def is_local(self) -> bool:
                return True

            def is_available(self) -> bool:
                return False

            def rerank(self, query, candidates, *, top_n=10):
                raise RuntimeError("should not be called")

        results, trace = apply_rerank(
            "query",
            self._make_candidates(),
            provider=UnavailableReranker(),
        )
        assert trace["fallback_used"] is True
        assert trace["egress"] == "unavailable"

    def test_provider_error_fallback(self):

        class ErrorReranker(RerankerProvider):
            def name(self) -> str:
                return "error"

            def is_local(self) -> bool:
                return True

            def is_available(self) -> bool:
                return True

            def rerank(self, query, candidates, *, top_n=10):
                raise RuntimeError("simulated error")

        results, trace = apply_rerank(
            "query",
            self._make_candidates(),
            provider=ErrorReranker(),
        )
        assert trace["fallback_used"] is True
        assert trace["egress"] == "error"
        assert len(results) == 3  # fallback to noop

    def test_provider_timeout_falls_back(self):
        class SlowReranker(RerankerProvider):
            def name(self) -> str:
                return "slow"

            def is_local(self) -> bool:
                return True

            def is_available(self) -> bool:
                return True

            def rerank(self, query, candidates, *, top_n=10):
                time.sleep(0.05)
                return [RerankResult(c.slide_id, c.score, c.score, c.title) for c in candidates[:top_n]]

        results, trace = apply_rerank(
            "query",
            self._make_candidates(),
            provider=SlowReranker(),
            timeout_seconds=0.001,
        )

        assert len(results) == 3
        assert trace["fallback_used"] is True
        assert trace["egress"] == "timeout"
