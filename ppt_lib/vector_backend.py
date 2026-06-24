"""Vector backend interface and ANN lifecycle (v1.6-B).

Provides a pluggable vector backend interface with a local SQLite-scan
compatibility backend and hooks for future ANN implementations.
"""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VectorSearchResult:
    """A result from vector similarity search."""

    slide_id: int
    score: float
    embedding_source: str = "unknown"

    def to_json(self) -> dict[str, object]:
        return {
            "slide_id": self.slide_id,
            "score": round(self.score, 4),
            "embedding_source": self.embedding_source,
        }


@dataclass(frozen=True)
class VectorBackendStatus:
    """Health and status of a vector backend."""

    backend_name: str
    available: bool
    index_count: int
    dimension: int | None
    model_version: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "backend_name": self.backend_name,
            "available": self.available,
            "index_count": self.index_count,
            "dimension": self.dimension,
            "model_version": self.model_version,
        }


class VectorBackend(ABC):
    """Abstract interface for vector storage and search."""

    @abstractmethod
    def name(self) -> str:
        """Backend identifier."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether the backend is ready for queries."""

    @abstractmethod
    def build_index(self, conn: sqlite3.Connection) -> int:
        """Build the vector index from embeddings in the database.

        Returns the number of vectors indexed.
        """

    @abstractmethod
    def search(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors."""

    @abstractmethod
    def get_status(self) -> VectorBackendStatus:
        """Get backend health and status."""


class SqliteScanBackend(VectorBackend):
    """Fallback backend that performs full SQLite vector scan.

    This is the current default behavior — computes cosine similarity
    against all stored embeddings in memory.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def name(self) -> str:
        return "sqlite_scan"

    def is_available(self) -> bool:
        return True

    def build_index(self, conn: sqlite3.Connection) -> int:
        # SQLite scan doesn't build an index — it reads all embeddings at query time
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM embeddings WHERE embedding IS NOT NULL")
        return cursor.fetchone()[0]

    def search(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int = 10,
        min_score: float = 0.0,
    ) -> list[VectorSearchResult]:
        cursor = self._conn.cursor()
        cursor.execute(
            """SELECT e.slide_id, e.embedding
               FROM embeddings e
               WHERE e.embedding IS NOT NULL"""
        )

        results: list[VectorSearchResult] = []
        query_norm = np.linalg.norm(query_embedding)
        if query_norm == 0:
            return []

        for slide_id, embedding_blob in cursor.fetchall():
            if embedding_blob is None:
                continue
            try:
                embedding = np.frombuffer(embedding_blob, dtype=np.float32)
                emb_norm = np.linalg.norm(embedding)
                if emb_norm == 0:
                    continue
                score = float(np.dot(query_embedding, embedding) / (query_norm * emb_norm))
                if score >= min_score:
                    results.append(VectorSearchResult(
                        slide_id=slide_id,
                        score=score,
                        embedding_source="sqlite_scan",
                    ))
            except (ValueError, TypeError):
                continue

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def get_status(self) -> VectorBackendStatus:
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM embeddings WHERE embedding IS NOT NULL")
            count = cursor.fetchone()[0]
            # Try to get dimension from first embedding
            cursor.execute(
                "SELECT embedding FROM embeddings WHERE embedding IS NOT NULL LIMIT 1"
            )
            row = cursor.fetchone()
            dimension = len(np.frombuffer(row[0], dtype=np.float32)) if row else None
            return VectorBackendStatus(
                backend_name="sqlite_scan",
                available=True,
                index_count=count,
                dimension=dimension,
                model_version=None,
            )
        except Exception:
            return VectorBackendStatus(
                backend_name="sqlite_scan",
                available=False,
                index_count=0,
                dimension=None,
                model_version=None,
            )
