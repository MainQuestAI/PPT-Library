"""Tests for query trace and explainability (v1.6-E)."""

from __future__ import annotations

import time

from ppt_lib.query_trace import (
    FallbackTrace,
    FusionTrace,
    LexicalBackendTrace,
    RerankerTrace,
    TraceBuilder,
    VectorBackendTrace,
    new_request_id,
    new_trace_id,
)


class TestTraceIDs:
    def test_new_trace_id_format(self):
        tid = new_trace_id()
        assert tid.startswith("qt_")
        assert len(tid) == 19  # qt_ + 16 hex chars

    def test_new_request_id_format(self):
        rid = new_request_id()
        assert rid.startswith("req_")
        assert len(rid) == 16  # req_ + 12 hex chars

    def test_trace_ids_unique(self):
        ids = {new_trace_id() for _ in range(100)}
        assert len(ids) == 100


class TestTraceComponents:
    def test_lexical_trace_to_json(self):
        t = LexicalBackendTrace(
            backend_name="fts5",
            candidate_count=10,
            duration_ms=5,
            fts_document_count=1000,
            query_sanitized='"architecture"',
        )
        j = t.to_json()
        assert j["backend_name"] == "fts5"
        assert j["candidate_count"] == 10

    def test_vector_trace_to_json(self):
        t = VectorBackendTrace(
            backend_name="sqlite_scan",
            candidate_count=8,
            duration_ms=12,
            index_count=500,
            dimension=1536,
            model_version="text-embedding-3-small",
            available=True,
        )
        j = t.to_json()
        assert j["dimension"] == 1536
        assert j["available"] is True

    def test_vector_trace_unavailable(self):
        t = VectorBackendTrace(
            backend_name="none",
            candidate_count=0,
            duration_ms=0,
            index_count=0,
            dimension=None,
            model_version=None,
            available=False,
            reason="not configured",
        )
        j = t.to_json()
        assert j["reason"] == "not configured"

    def test_fusion_trace_to_json(self):
        t = FusionTrace(
            method="rrf",
            rrf_k=60,
            input_lexical_count=10,
            input_vector_count=8,
            output_count=15,
            duration_ms=1,
        )
        j = t.to_json()
        assert j["method"] == "rrf"
        assert j["rrf_k"] == 60

    def test_reranker_trace_to_json(self):
        t = RerankerTrace(
            provider="local",
            model="cross-encoder",
            input_count=15,
            output_count=10,
            duration_ms=50,
            egress="local",
            fallback_used=False,
        )
        j = t.to_json()
        assert j["provider"] == "local"
        assert j["egress"] == "local"

    def test_fallback_trace_to_json(self):
        t = FallbackTrace(
            backend="vector",
            original="ann",
            fallback="sqlite_scan",
            reason="ANN index not built",
        )
        j = t.to_json()
        assert j["backend"] == "vector"
        assert j["reason"] == "ANN index not built"


class TestTraceBuilder:
    def test_build_minimal_trace(self):
        builder = TraceBuilder("test query", "default", "1.0")
        trace = builder.build()
        assert trace.query == "test query"
        assert trace.profile_name == "default"
        assert trace.lexical_backend.backend_name == "none"
        assert trace.vector_backend.backend_name == "none"
        assert trace.reranker is None
        assert trace.fallback is None
        assert trace.warnings == []

    def test_build_full_trace(self):
        builder = TraceBuilder("architecture", "default", "1.0")
        builder.set_lexical_trace(LexicalBackendTrace(
            backend_name="fts5",
            candidate_count=10,
            duration_ms=5,
            fts_document_count=1000,
            query_sanitized='"architecture"',
        ))
        builder.set_vector_trace(VectorBackendTrace(
            backend_name="sqlite_scan",
            candidate_count=8,
            duration_ms=12,
            index_count=500,
            dimension=1536,
            model_version="v1",
            available=True,
        ))
        builder.set_fusion_trace(FusionTrace(
            method="rrf",
            rrf_k=60,
            input_lexical_count=10,
            input_vector_count=8,
            output_count=15,
            duration_ms=1,
        ))
        builder.set_reranker_trace(RerankerTrace(
            provider="local",
            model="cross-encoder",
            input_count=15,
            output_count=10,
            duration_ms=50,
            egress="local",
            fallback_used=False,
        ))
        builder.add_warning("SEARCH_FALLBACK_ACTIVE", "Vector backend unavailable")

        trace = builder.build()
        assert trace.lexical_backend.backend_name == "fts5"
        assert trace.vector_backend.backend_name == "sqlite_scan"
        assert trace.fusion.method == "rrf"
        assert trace.reranker is not None
        assert len(trace.warnings) == 1

    def test_trace_id_and_request_id(self):
        builder = TraceBuilder("q", "p", "v")
        assert builder.trace_id.startswith("qt_")
        assert builder.request_id.startswith("req_")

    def test_duration_ms(self):
        builder = TraceBuilder("q", "p", "v")
        time.sleep(0.01)
        trace = builder.build()
        assert trace.duration_ms >= 10

    def test_trace_to_json(self):
        builder = TraceBuilder("test", "default", "1.0")
        builder.set_lexical_trace(LexicalBackendTrace(
            "fts5", 5, 3, 100, '"test"',
        ))
        trace = builder.build()
        j = trace.to_json()
        assert "query_trace_id" in j
        assert "request_id" in j
        assert "lexical_backend" in j
        assert "vector_backend" in j
        assert "fusion" in j
        assert "generated_at" in j

    def test_fallback_trace_in_json(self):
        builder = TraceBuilder("q", "p", "v")
        builder.set_fallback_trace(FallbackTrace(
            backend="vector",
            original="ann",
            fallback="sqlite_scan",
            reason="no index",
        ))
        trace = builder.build()
        j = trace.to_json()
        assert "fallback" in j
        assert j["fallback"]["backend"] == "vector"

    def test_no_reranker_in_json(self):
        builder = TraceBuilder("q", "p", "v")
        trace = builder.build()
        j = trace.to_json()
        assert "reranker" not in j

    def test_no_fallback_in_json(self):
        builder = TraceBuilder("q", "p", "v")
        trace = builder.build()
        j = trace.to_json()
        assert "fallback" not in j

    def test_no_warnings_in_json(self):
        builder = TraceBuilder("q", "p", "v")
        trace = builder.build()
        j = trace.to_json()
        assert "warnings" not in j
