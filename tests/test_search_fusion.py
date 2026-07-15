"""Tests for vector backend and search fusion (v1.6-B/C)."""

from __future__ import annotations

import sqlite3

import numpy as np

from ppt_lib.fts_search import LexicalSearchResult, SearchDocument, create_fts_tables, index_search_document
from ppt_lib.search_fusion import (
    DECK_MASTER_PROFILE,
    DEFAULT_PROFILE,
    FusedCandidate,
    get_profile,
    hybrid_search,
    list_profiles,
    reciprocal_rank_fusion,
)
from ppt_lib.vector_backend import (
    SqliteScanBackend,
    VectorBackendStatus,
    VectorSearchResult,
)


def _create_db_with_embeddings() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE slides (
            id INTEGER PRIMARY KEY,
            presentation_id INTEGER,
            embedding BLOB
        )"""
    )
    return conn


def _make_embedding(dim: int = 4, seed: int = 0) -> bytes:
    rng = np.random.RandomState(seed)
    vec = rng.randn(dim).astype(np.float32)
    vec = vec / np.linalg.norm(vec)
    return vec.tobytes()


class TestSqliteScanBackend:
    def test_is_available(self):
        conn = _create_db_with_embeddings()
        backend = SqliteScanBackend(conn)
        assert backend.is_available() is True
        assert backend.name() == "sqlite_scan"

    def test_build_index(self):
        conn = _create_db_with_embeddings()
        conn.execute("INSERT INTO slides VALUES (1, 1, ?)", (_make_embedding(),))
        conn.execute("INSERT INTO slides VALUES (2, 1, ?)", (_make_embedding(seed=1),))
        backend = SqliteScanBackend(conn)
        count = backend.build_index(conn)
        assert count == 2

    def test_search_returns_results(self):
        conn = _create_db_with_embeddings()
        for i in range(5):
            conn.execute(f"INSERT INTO slides VALUES ({i+1}, 1, ?)", (_make_embedding(seed=i),))
        backend = SqliteScanBackend(conn)
        query = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = backend.search(query, top_k=3)
        assert len(results) <= 3
        assert all(isinstance(r, VectorSearchResult) for r in results)

    def test_search_respects_top_k(self):
        conn = _create_db_with_embeddings()
        for i in range(10):
            conn.execute(f"INSERT INTO slides VALUES ({i+1}, 1, ?)", (_make_embedding(seed=i),))
        backend = SqliteScanBackend(conn)
        results = backend.search(np.array([1, 0, 0, 0], dtype=np.float32), top_k=2)
        assert len(results) <= 2

    def test_search_empty_db(self):
        conn = _create_db_with_embeddings()
        backend = SqliteScanBackend(conn)
        results = backend.search(np.array([1, 0, 0, 0], dtype=np.float32))
        assert results == []

    def test_search_zero_query(self):
        conn = _create_db_with_embeddings()
        conn.execute("INSERT INTO slides VALUES (1, 1, ?)", (_make_embedding(),))
        backend = SqliteScanBackend(conn)
        results = backend.search(np.zeros(4, dtype=np.float32))
        assert results == []

    def test_get_status(self):
        conn = _create_db_with_embeddings()
        conn.execute("INSERT INTO slides VALUES (1, 1, ?)", (_make_embedding(dim=8),))
        backend = SqliteScanBackend(conn)
        status = backend.get_status()
        assert status.backend_name == "sqlite_scan"
        assert status.available is True
        assert status.index_count == 1
        assert status.dimension == 8


class TestVectorSearchResult:
    def test_to_json(self):
        r = VectorSearchResult(slide_id=42, score=0.95, embedding_source="test")
        j = r.to_json()
        assert j["slide_id"] == 42
        assert j["score"] == 0.95


class TestVectorBackendStatus:
    def test_to_json(self):
        s = VectorBackendStatus("test", True, 100, 1536, "v1")
        j = s.to_json()
        assert j["backend_name"] == "test"
        assert j["dimension"] == 1536


class TestRRF:
    def test_basic_fusion(self):
        lexical = [
            LexicalSearchResult(1, 0.9, "A", "snippet", []),
            LexicalSearchResult(2, 0.8, "B", "snippet", []),
        ]
        vector = [
            VectorSearchResult(2, 0.95),
            VectorSearchResult(3, 0.85),
        ]
        fused = reciprocal_rank_fusion(lexical, vector, k=60)
        assert len(fused) == 3  # slides 1, 2, 3

        # Slide 2 appears in both lists, should have highest RRF score
        slide_2 = next(c for c in fused if c.slide_id == 2)
        assert slide_2.lexical_rank == 2
        assert slide_2.vector_rank == 1
        assert slide_2.fused_score > 0

    def test_lexical_only(self):
        lexical = [
            LexicalSearchResult(1, 0.9, "A", "snippet", []),
        ]
        fused = reciprocal_rank_fusion(lexical, [], k=60)
        assert len(fused) == 1
        assert fused[0].vector_rank is None
        assert fused[0].lexical_rank == 1

    def test_vector_only(self):
        vector = [
            VectorSearchResult(1, 0.9),
        ]
        fused = reciprocal_rank_fusion([], vector, k=60)
        assert len(fused) == 1
        assert fused[0].lexical_rank is None
        assert fused[0].vector_rank == 1

    def test_empty(self):
        fused = reciprocal_rank_fusion([], [], k=60)
        assert fused == []

    def test_sorted_by_score(self):
        lexical = [
            LexicalSearchResult(1, 0.9, "A", "", []),
            LexicalSearchResult(2, 0.8, "B", "", []),
            LexicalSearchResult(3, 0.7, "C", "", []),
        ]
        vector = [
            VectorSearchResult(1, 0.95),
            VectorSearchResult(2, 0.85),
        ]
        fused = reciprocal_rank_fusion(lexical, vector, k=60)
        scores = [c.fused_score for c in fused]
        assert scores == sorted(scores, reverse=True)


class TestFusedCandidate:
    def test_to_json(self):
        c = FusedCandidate(
            slide_id=1, fused_score=0.05,
            lexical_rank=1, lexical_score=0.9,
            vector_rank=2, vector_score=0.85,
            title="Test", snippet="snippet",
        )
        j = c.to_json()
        assert j["slide_id"] == 1
        assert j["lexical_rank"] == 1
        assert j["vector_rank"] == 2


class TestSearchProfiles:
    def test_default_profile(self):
        assert DEFAULT_PROFILE.name == "default"
        assert DEFAULT_PROFILE.version == "1.0"

    def test_deck_master_profile(self):
        assert DECK_MASTER_PROFILE.name == "deck_master"
        assert DECK_MASTER_PROFILE.ranking == "business"

    def test_get_profile(self):
        p = get_profile("default")
        assert p is not None
        assert p.name == "default"

    def test_get_unknown_profile(self):
        assert get_profile("nonexistent") is None

    def test_list_profiles(self):
        profiles = list_profiles()
        assert len(profiles) >= 2
        names = {p.name for p in profiles}
        assert "default" in names
        assert "deck_master" in names

    def test_profile_to_json(self):
        j = DEFAULT_PROFILE.to_json()
        assert j["name"] == "default"
        assert "rrf_k" in j


class TestHybridSearch:
    def _seed(self, conn: sqlite3.Connection) -> None:
        create_fts_tables(conn)
        for i, (title, body) in enumerate([
            ("Architecture Overview", "microservices and containers"),
            ("ML Pipeline", "deep learning training"),
            ("Dashboard", "analytics visualization"),
        ], start=1):
            doc = SearchDocument(f"sd_{i}", f"a{i}", f"srev_{i}", i,
                title, body, "", "", "", "", "", "", "", "")
            index_search_document(conn, doc)
            conn.execute(f"INSERT INTO slides VALUES ({i}, 1, ?)", (_make_embedding(seed=i),))

    def test_hybrid_lexical_only(self):
        conn = _create_db_with_embeddings()
        self._seed(conn)
        results = hybrid_search(conn, "architecture", top_k=5)
        assert len(results) > 0

    def test_hybrid_with_embedding(self):
        conn = _create_db_with_embeddings()
        self._seed(conn)
        query_emb = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        results = hybrid_search(conn, "architecture", query_embedding=query_emb, top_k=5)
        assert len(results) > 0

    def test_hybrid_with_profile(self):
        conn = _create_db_with_embeddings()
        self._seed(conn)
        results = hybrid_search(conn, "ML", profile=DECK_MASTER_PROFILE, top_k=3)
        assert isinstance(results, list)
