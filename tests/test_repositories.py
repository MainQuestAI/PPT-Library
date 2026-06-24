"""Tests for repository interfaces (v1.9-A)."""

from __future__ import annotations

import sqlite3

from ppt_lib.repositories import (
    PaginatedResult,
    PaginationParams,
    PresentationRow,
    RepositoryFactory,
    SlideRepository,
    SlideRow,
    SqlitePresentationRepository,
    SqliteSlideRepository,
)


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE presentations (
            id INTEGER PRIMARY KEY,
            path TEXT,
            filename TEXT,
            project_name TEXT,
            slide_count INTEGER DEFAULT 0,
            content_hash TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE slides (
            id INTEGER PRIMARY KEY,
            presentation_id INTEGER,
            slide_index INTEGER,
            title TEXT,
            text_content TEXT DEFAULT '',
            source TEXT DEFAULT 'text_extraction',
            metadata_json TEXT DEFAULT '{}'
        )"""
    )
    # Seed data
    conn.execute("INSERT INTO presentations VALUES (1, '/test.pptx', 'test.pptx', 'Project A', 3, 'hash1')")
    conn.execute("INSERT INTO presentations VALUES (2, '/test2.pptx', 'test2.pptx', 'Project B', 2, 'hash2')")
    conn.execute("INSERT INTO slides VALUES (1, 1, 1, 'Title 1', 'Architecture overview', 'text', '{}')")
    conn.execute("INSERT INTO slides VALUES (2, 1, 2, 'Title 2', 'Data pipeline design', 'text', '{}')")
    conn.execute("INSERT INTO slides VALUES (3, 1, 3, 'Title 3', 'Summary and next steps', 'text', '{}')")
    conn.execute("INSERT INTO slides VALUES (4, 2, 1, 'Title 4', 'Architecture for retail', 'text', '{}')")
    conn.execute("INSERT INTO slides VALUES (5, 2, 2, 'Title 5', 'Implementation plan', 'text', '{}')")
    conn.commit()
    return conn


class TestSlideRow:
    def test_fields(self):
        r = SlideRow(1, 1, 1, "Title", "Content", "text", "{}")
        assert r.id == 1
        assert r.title == "Title"


class TestPresentationRow:
    def test_fields(self):
        r = PresentationRow(1, "/path", "file.pptx", "Project", 10, "hash")
        assert r.filename == "file.pptx"


class TestPaginationParams:
    def test_defaults(self):
        p = PaginationParams()
        assert p.limit == 50
        assert p.offset == 0


class TestPaginatedResult:
    def test_has_more(self):
        r = PaginatedResult(items=[1, 2], total=10, limit=5, offset=0)
        assert r.has_more is True

    def test_no_more(self):
        r = PaginatedResult(items=[1, 2], total=3, limit=5, offset=0)
        assert r.has_more is False

    def test_to_json(self):
        r = PaginatedResult(items=[1, 2, 3], total=10, limit=5, offset=0)
        j = r.to_json()
        assert j["total"] == 10
        assert j["count"] == 3
        assert j["has_more"] is True


class TestSqliteSlideRepository:
    def test_get_by_id(self):
        conn = _create_db()
        repo = SqliteSlideRepository(conn)
        slide = repo.get_by_id(1)
        assert slide is not None
        assert slide.title == "Title 1"

    def test_get_by_id_not_found(self):
        conn = _create_db()
        repo = SqliteSlideRepository(conn)
        assert repo.get_by_id(999) is None

    def test_list_all(self):
        conn = _create_db()
        repo = SqliteSlideRepository(conn)
        result = repo.list_slides()
        assert result.total == 5
        assert len(result.items) == 5

    def test_list_by_presentation(self):
        conn = _create_db()
        repo = SqliteSlideRepository(conn)
        result = repo.list_slides(presentation_id=1)
        assert result.total == 3

    def test_list_with_pagination(self):
        conn = _create_db()
        repo = SqliteSlideRepository(conn)
        result = repo.list_slides(pagination=PaginationParams(limit=2, offset=0))
        assert len(result.items) == 2
        assert result.has_more is True

    def test_count(self):
        conn = _create_db()
        repo = SqliteSlideRepository(conn)
        assert repo.count() == 5

    def test_count_by_presentation(self):
        conn = _create_db()
        repo = SqliteSlideRepository(conn)
        assert repo.count(presentation_id=2) == 2

    def test_search_text(self):
        conn = _create_db()
        repo = SqliteSlideRepository(conn)
        results = repo.search_text("Architecture")
        assert len(results) == 2  # slides 1 and 4

    def test_search_text_no_results(self):
        conn = _create_db()
        repo = SqliteSlideRepository(conn)
        results = repo.search_text("nonexistent")
        assert len(results) == 0

    def test_protocol_compliance(self):
        conn = _create_db()
        repo = SqliteSlideRepository(conn)
        assert isinstance(repo, SlideRepository)


class TestSqlitePresentationRepository:
    def test_get_by_id(self):
        conn = _create_db()
        repo = SqlitePresentationRepository(conn)
        pres = repo.get_by_id(1)
        assert pres is not None
        assert pres.filename == "test.pptx"

    def test_get_by_id_not_found(self):
        conn = _create_db()
        repo = SqlitePresentationRepository(conn)
        assert repo.get_by_id(999) is None

    def test_list_all(self):
        conn = _create_db()
        repo = SqlitePresentationRepository(conn)
        result = repo.list_presentations()
        assert result.total == 2

    def test_count(self):
        conn = _create_db()
        repo = SqlitePresentationRepository(conn)
        assert repo.count() == 2


class TestRepositoryFactory:
    def test_create_slides(self):
        conn = _create_db()
        factory = RepositoryFactory(conn)
        repo = factory.slides()
        assert repo.count() == 5

    def test_create_presentations(self):
        conn = _create_db()
        factory = RepositoryFactory(conn)
        repo = factory.presentations()
        assert repo.count() == 2
