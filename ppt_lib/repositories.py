"""Repository interfaces for multi-backend support (v1.9-A).

Defines protocol interfaces for repository implementations.
SQLite and Postgres backends implement these protocols.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SlideRow:
    """A row from the slides table."""

    id: int
    presentation_id: int
    slide_index: int
    title: str | None
    text_content: str
    source: str
    metadata_json: str


@dataclass(frozen=True)
class PresentationRow:
    """A row from the presentations table."""

    id: int
    path: str
    filename: str
    project_name: str | None
    slide_count: int
    content_hash: str


@dataclass(frozen=True)
class PaginationParams:
    """Pagination parameters."""

    limit: int = 50
    offset: int = 0


@dataclass(frozen=True)
class PaginatedResult:
    """Paginated query result."""

    items: list[Any]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + self.limit < self.total

    def to_json(self) -> dict[str, object]:
        return {
            "total": self.total,
            "limit": self.limit,
            "offset": self.offset,
            "has_more": self.has_more,
            "count": len(self.items),
        }


@runtime_checkable
class SlideRepository(Protocol):
    """Protocol for slide data access."""

    def get_by_id(self, slide_id: int) -> SlideRow | None:
        """Get a slide by ID."""
        ...

    def list_slides(
        self,
        *,
        presentation_id: int | None = None,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResult:
        """List slides with optional filtering and pagination."""
        ...

    def count(self, *, presentation_id: int | None = None) -> int:
        """Count slides."""
        ...

    def search_text(self, query: str, *, limit: int = 50) -> list[SlideRow]:
        """Full-text search on slide content."""
        ...


@runtime_checkable
class PresentationRepository(Protocol):
    """Protocol for presentation data access."""

    def get_by_id(self, pres_id: int) -> PresentationRow | None:
        """Get a presentation by ID."""
        ...

    def list_presentations(
        self,
        *,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResult:
        """List presentations with pagination."""
        ...

    def count(self) -> int:
        """Count presentations."""
        ...


class SqliteSlideRepository:
    """SQLite implementation of SlideRepository."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_by_id(self, slide_id: int) -> SlideRow | None:
        cursor = self._conn.cursor()
        cursor.execute(
            """SELECT id, presentation_id, slide_index, title, text_content,
                      source, metadata_json
               FROM slides WHERE id = ?""",
            (slide_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return SlideRow(*row)

    def list_slides(
        self,
        *,
        presentation_id: int | None = None,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResult:
        cursor = self._conn.cursor()
        pagination = pagination or PaginationParams()

        conditions: list[str] = []
        params: list[Any] = []
        if presentation_id is not None:
            conditions.append("presentation_id = ?")
            params.append(presentation_id)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        cursor.execute(f"SELECT COUNT(*) FROM slides{where}", params)
        total = cursor.fetchone()[0]

        cursor.execute(
            f"""SELECT id, presentation_id, slide_index, title, text_content,
                       source, metadata_json
                FROM slides{where}
                ORDER BY id
                LIMIT ? OFFSET ?""",
            [*params, pagination.limit, pagination.offset],
        )
        items = [SlideRow(*row) for row in cursor.fetchall()]

        return PaginatedResult(
            items=items,
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
        )

    def count(self, *, presentation_id: int | None = None) -> int:
        cursor = self._conn.cursor()
        if presentation_id is not None:
            cursor.execute(
                "SELECT COUNT(*) FROM slides WHERE presentation_id = ?",
                (presentation_id,),
            )
        else:
            cursor.execute("SELECT COUNT(*) FROM slides")
        return cursor.fetchone()[0]

    def search_text(self, query: str, *, limit: int = 50) -> list[SlideRow]:
        cursor = self._conn.cursor()
        cursor.execute(
            """SELECT id, presentation_id, slide_index, title, text_content,
                      source, metadata_json
               FROM slides
               WHERE text_content LIKE ?
               ORDER BY id
               LIMIT ?""",
            (f"%{query}%", limit),
        )
        return [SlideRow(*row) for row in cursor.fetchall()]


class SqlitePresentationRepository:
    """SQLite implementation of PresentationRepository."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_by_id(self, pres_id: int) -> PresentationRow | None:
        cursor = self._conn.cursor()
        cursor.execute(
            """SELECT id, path, filename, project_name, slide_count, content_hash
               FROM presentations WHERE id = ?""",
            (pres_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return PresentationRow(*row)

    def list_presentations(
        self,
        *,
        pagination: PaginationParams | None = None,
    ) -> PaginatedResult:
        cursor = self._conn.cursor()
        pagination = pagination or PaginationParams()

        cursor.execute("SELECT COUNT(*) FROM presentations")
        total = cursor.fetchone()[0]

        cursor.execute(
            """SELECT id, path, filename, project_name, slide_count, content_hash
               FROM presentations
               ORDER BY id
               LIMIT ? OFFSET ?""",
            (pagination.limit, pagination.offset),
        )
        items = [PresentationRow(*row) for row in cursor.fetchall()]

        return PaginatedResult(
            items=items,
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
        )

    def count(self) -> int:
        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM presentations")
        return cursor.fetchone()[0]


class RepositoryFactory:
    """Factory for creating repository instances."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def slides(self) -> SqliteSlideRepository:
        return SqliteSlideRepository(self._conn)

    def presentations(self) -> SqlitePresentationRepository:
        return SqlitePresentationRepository(self._conn)
