"""Search fusion: RRF combination of lexical and vector recall (v1.6-C).

Implements Reciprocal Rank Fusion (RRF) to combine results from
multiple retrieval backends into a single ranked candidate list.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

import numpy as np

from ppt_lib.fts_search import LexicalSearchResult, lexical_search
from ppt_lib.vector_backend import SqliteScanBackend, VectorBackend, VectorBackendStatus, VectorSearchResult

# Default RRF constant (Cormack et al.)
DEFAULT_RRF_K = 60


@dataclass(frozen=True)
class FusedCandidate:
    """A candidate from fused retrieval."""

    slide_id: int
    fused_score: float
    lexical_rank: int | None
    lexical_score: float | None
    vector_rank: int | None
    vector_score: float | None
    title: str | None
    snippet: str

    def to_json(self) -> dict[str, object]:
        return {
            "slide_id": self.slide_id,
            "fused_score": round(self.fused_score, 6),
            "lexical_rank": self.lexical_rank,
            "lexical_score": round(self.lexical_score, 4) if self.lexical_score is not None else None,
            "vector_rank": self.vector_rank,
            "vector_score": round(self.vector_score, 4) if self.vector_score is not None else None,
            "title": self.title,
            "snippet": self.snippet,
        }


@dataclass(frozen=True)
class HybridSearchRun:
    candidates: list[FusedCandidate]
    lexical_results: list[LexicalSearchResult]
    vector_results: list[VectorSearchResult]
    lexical_duration_ms: int
    vector_duration_ms: int
    fusion_duration_ms: int
    vector_status: VectorBackendStatus
    fallback_reason: str | None = None


@dataclass(frozen=True)
class SearchProfile:
    """Versioned search configuration profile."""

    name: str
    version: str
    lexical_top_k: int
    vector_top_k: int
    rrf_k: int
    min_score: float
    include_versions: bool
    ranking: str

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "lexical_top_k": self.lexical_top_k,
            "vector_top_k": self.vector_top_k,
            "rrf_k": self.rrf_k,
            "min_score": self.min_score,
            "include_versions": self.include_versions,
            "ranking": self.ranking,
        }


# Built-in profiles
DEFAULT_PROFILE = SearchProfile(
    name="default",
    version="1.0",
    lexical_top_k=20,
    vector_top_k=20,
    rrf_k=DEFAULT_RRF_K,
    min_score=0.0,
    include_versions=False,
    ranking="classic",
)

DECK_MASTER_PROFILE = SearchProfile(
    name="deck_master",
    version="1.0",
    lexical_top_k=30,
    vector_top_k=30,
    rrf_k=DEFAULT_RRF_K,
    min_score=0.1,
    include_versions=False,
    ranking="business",
)

PROFILES: dict[str, SearchProfile] = {
    "default": DEFAULT_PROFILE,
    "deck_master": DECK_MASTER_PROFILE,
}


def get_profile(name: str) -> SearchProfile | None:
    """Get a search profile by name."""
    return PROFILES.get(name)


def list_profiles() -> list[SearchProfile]:
    """List all available search profiles."""
    return list(PROFILES.values())


# ---------------------------------------------------------------------------
# RRF Fusion
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    lexical_results: list[LexicalSearchResult],
    vector_results: list[VectorSearchResult],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[FusedCandidate]:
    """Combine lexical and vector results using Reciprocal Rank Fusion.

    RRF score = sum of 1/(k + rank_i) across all lists where the item appears.
    """
    scores: dict[int, float] = {}
    lexical_map: dict[int, tuple[int, LexicalSearchResult]] = {}
    vector_map: dict[int, tuple[int, VectorSearchResult]] = {}

    # Compute RRF scores from lexical results
    for rank, result in enumerate(lexical_results, start=1):
        rrf_score = 1.0 / (k + rank)
        scores[result.slide_id] = scores.get(result.slide_id, 0.0) + rrf_score
        lexical_map[result.slide_id] = (rank, result)

    # Compute RRF scores from vector results
    for vec_rank, vec_result in enumerate(vector_results, start=1):
        rrf_score = 1.0 / (k + vec_rank)
        scores[vec_result.slide_id] = scores.get(vec_result.slide_id, 0.0) + rrf_score
        vector_map[vec_result.slide_id] = (vec_rank, vec_result)

    # Build fused candidates
    candidates: list[FusedCandidate] = []
    for slide_id, fused_score in scores.items():
        lex_info = lexical_map.get(slide_id)
        vec_info = vector_map.get(slide_id)

        candidates.append(
            FusedCandidate(
                slide_id=slide_id,
                fused_score=fused_score,
                lexical_rank=lex_info[0] if lex_info else None,
                lexical_score=lex_info[1].score if lex_info else None,
                vector_rank=vec_info[0] if vec_info else None,
                vector_score=vec_info[1].score if vec_info else None,
                title=lex_info[1].title if lex_info else None,
                snippet=lex_info[1].snippet if lex_info else "",
            )
        )

    candidates.sort(key=lambda c: (-c.fused_score, c.slide_id))
    return candidates


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    query_embedding: np.ndarray | None = None,
    *,
    profile: SearchProfile | None = None,
    top_k: int = 10,
    vector_backend: VectorBackend | None = None,
) -> list[FusedCandidate]:
    """Perform hybrid search combining lexical and vector recall.

    If query_embedding is None, falls back to lexical-only search.
    """
    return run_hybrid_search(
        conn,
        query,
        query_embedding,
        profile=profile,
        top_k=top_k,
        vector_backend=vector_backend,
    ).candidates


def run_hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    query_embedding: np.ndarray | None = None,
    *,
    profile: SearchProfile | None = None,
    top_k: int = 10,
    vector_backend: VectorBackend | None = None,
) -> HybridSearchRun:
    profile = profile or DEFAULT_PROFILE
    lexical_top_k = max(profile.lexical_top_k, top_k)
    vector_top_k = max(profile.vector_top_k, top_k)

    # Lexical recall
    lexical_started = time.monotonic()
    lexical_results = lexical_search(
        conn,
        query,
        top_k=lexical_top_k,
    )
    lexical_duration_ms = int((time.monotonic() - lexical_started) * 1000)

    # Vector recall
    vector_results: list[VectorSearchResult] = []
    backend = vector_backend or SqliteScanBackend(conn)
    vector_status = backend.get_status()
    vector_duration_ms = 0
    fallback_reason: str | None = None
    if query_embedding is not None:
        if backend.is_available():
            vector_started = time.monotonic()
            try:
                vector_results = backend.search(
                    query_embedding,
                    top_k=vector_top_k,
                    min_score=profile.min_score,
                )
            except (sqlite3.Error, ValueError, TypeError) as exc:
                fallback_reason = f"{type(exc).__name__}: {exc}"
            vector_duration_ms = int((time.monotonic() - vector_started) * 1000)
        else:
            fallback_reason = "vector backend unavailable"
    else:
        fallback_reason = "query embedding unavailable"

    # Fuse
    fusion_started = time.monotonic()
    candidates = reciprocal_rank_fusion(
        lexical_results,
        vector_results,
        k=profile.rrf_k,
    )
    fusion_duration_ms = int((time.monotonic() - fusion_started) * 1000)

    return HybridSearchRun(
        candidates=candidates[:top_k],
        lexical_results=lexical_results,
        vector_results=vector_results,
        lexical_duration_ms=lexical_duration_ms,
        vector_duration_ms=vector_duration_ms,
        fusion_duration_ms=fusion_duration_ms,
        vector_status=vector_status,
        fallback_reason=fallback_reason,
    )
