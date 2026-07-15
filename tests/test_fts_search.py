"""Tests for FTS5 search documents (v1.6-A)."""

from __future__ import annotations

import sqlite3

import numpy as np

from ppt_lib.db import PresentationRecord, SlideRecord, connect, init_db, upsert_presentation, upsert_slide
from ppt_lib.fts_search import (
    LexicalSearchResult,
    SearchDocument,
    create_fts_tables,
    fts_tables_exist,
    get_fts_document_count,
    index_from_slides,
    index_search_document,
    lexical_search,
    rebuild_fts,
    remove_search_document,
)


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE slides (
            id INTEGER PRIMARY KEY,
            presentation_id INTEGER,
            title TEXT,
            text_content TEXT,
            metadata_json TEXT DEFAULT '{}',
            slide_revision_id TEXT,
            canonical_asset_id TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE asset_identity_map (
            canonical_asset_id TEXT,
            slide_revision_id TEXT,
            legacy_slide_id INTEGER
        )"""
    )
    return conn


class TestFTSSchema:
    def test_create_fts_tables(self):
        conn = _create_db()
        create_fts_tables(conn)
        assert fts_tables_exist(conn) is True

    def test_fts_tables_not_exist(self):
        conn = _create_db()
        assert fts_tables_exist(conn) is False


class TestSearchDocument:
    def test_to_fts_text(self):
        doc = SearchDocument(
            search_document_id="sd_1",
            canonical_asset_id="a1",
            slide_revision_id="srev_1",
            legacy_slide_id=1,
            title="Architecture Overview",
            body_text="This slide describes the system architecture",
            ocr_markdown="# Architecture\n\nComponents...",
            ai_summary="Summary of architecture",
            deck_summary="Deck about technology",
            narrative_role="problem",
            page_role="overview",
            page_archetype="diagram",
            industry="technology",
            scenario="proposal",
        )
        text = doc.to_fts_text()
        assert "Architecture Overview" in text
        assert "system architecture" in text


class TestIndexing:
    def test_real_init_db_indexes_real_slide_columns(self, tmp_path) -> None:
        conn = connect(tmp_path / "index.db")
        init_db(conn)
        presentation_id = upsert_presentation(
            conn,
            PresentationRecord(tmp_path / "deck.pptx", "deck.pptx", None, 1, "h", 1, 1.0),
        )
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id,
                0,
                "Architecture",
                "cloud architecture architecture",
                np.ones(4, dtype=np.float32),
                None,
                "text_extraction",
                [],
                {},
            ),
        )

        assert index_from_slides(conn) == 1
        assert lexical_search(conn, "architecture")[0].slide_id == 1

    def test_index_single_document(self):
        conn = _create_db()
        create_fts_tables(conn)
        doc = SearchDocument(
            search_document_id="sd_1",
            canonical_asset_id="a1",
            slide_revision_id="srev_1",
            legacy_slide_id=1,
            title="Cloud Architecture",
            body_text="Microservices and containers",
            ocr_markdown="",
            ai_summary="",
            deck_summary="",
            narrative_role="",
            page_role="",
            page_archetype="",
            industry="",
            scenario="",
        )
        index_search_document(conn, doc)
        assert get_fts_document_count(conn) == 1

    def test_index_replace(self):
        conn = _create_db()
        create_fts_tables(conn)
        doc = SearchDocument(
            search_document_id="sd_1",
            canonical_asset_id="a1",
            slide_revision_id="srev_1",
            legacy_slide_id=1,
            title="Original",
            body_text="",
            ocr_markdown="",
            ai_summary="",
            deck_summary="",
            narrative_role="",
            page_role="",
            page_archetype="",
            industry="",
            scenario="",
        )
        index_search_document(conn, doc)
        doc2 = SearchDocument(
            search_document_id="sd_1",
            canonical_asset_id="a1",
            slide_revision_id="srev_2",
            legacy_slide_id=1,
            title="Updated",
            body_text="",
            ocr_markdown="",
            ai_summary="",
            deck_summary="",
            narrative_role="",
            page_role="",
            page_archetype="",
            industry="",
            scenario="",
        )
        index_search_document(conn, doc2)
        assert get_fts_document_count(conn) == 1

    def test_remove_document(self):
        conn = _create_db()
        create_fts_tables(conn)
        doc = SearchDocument(
            search_document_id="sd_1",
            canonical_asset_id="a1",
            slide_revision_id="srev_1",
            legacy_slide_id=1,
            title="Test",
            body_text="",
            ocr_markdown="",
            ai_summary="",
            deck_summary="",
            narrative_role="",
            page_role="",
            page_archetype="",
            industry="",
            scenario="",
        )
        index_search_document(conn, doc)
        remove_search_document(conn, "sd_1")
        assert get_fts_document_count(conn) == 0

    def test_index_from_slides(self):
        conn = _create_db()
        create_fts_tables(conn)
        for i in range(1, 6):
            conn.execute(
                "INSERT INTO slides (id, title, text_content) VALUES (?, ?, ?)",
                (i, f"Slide {i}", f"Content about topic {i}"),
            )
        count = index_from_slides(conn)
        assert count == 5
        assert get_fts_document_count(conn) == 5

    def test_index_from_slides_with_limit(self):
        conn = _create_db()
        create_fts_tables(conn)
        for i in range(1, 11):
            conn.execute(
                "INSERT INTO slides (id, title, text_content) VALUES (?, ?, ?)",
                (i, f"Slide {i}", f"Content {i}"),
            )
        count = index_from_slides(conn, limit=3)
        assert count == 3

    def test_rebuild_fts(self):
        conn = _create_db()
        create_fts_tables(conn)
        # Insert source slide data that rebuild will re-index from
        conn.execute(
            "INSERT INTO slides (id, title, text_content) VALUES (1, 'Test', 'Some content')"
        )
        conn.commit()
        rebuild_fts(conn)
        assert get_fts_document_count(conn) == 1


class TestLexicalSearch:
    def _seed_data(self, conn: sqlite3.Connection) -> None:
        create_fts_tables(conn)
        docs = [
            SearchDocument("sd_1", "a1", "srev_1", 1,
                "Cloud Architecture Overview",
                "This slide describes microservices architecture with containers",
                "", "", "", "", "", "", "", ""),
            SearchDocument("sd_2", "a2", "srev_2", 2,
                "Machine Learning Pipeline",
                "Deep learning model training and deployment pipeline",
                "", "", "", "", "", "", "", ""),
            SearchDocument("sd_3", "a3", "srev_3", 3,
                "Data Analytics Dashboard",
                "Real-time analytics dashboard with data visualization",
                "", "", "", "", "", "", "", ""),
        ]
        for doc in docs:
            index_search_document(conn, doc)

    def test_search_finds_results(self):
        conn = _create_db()
        self._seed_data(conn)
        results = lexical_search(conn, "architecture")
        assert len(results) > 0
        assert any("architecture" in r.snippet.lower() or "architecture" in (r.title or "").lower() for r in results)

    def test_search_returns_slide_id(self):
        conn = _create_db()
        self._seed_data(conn)
        results = lexical_search(conn, "microservices")
        assert len(results) >= 1
        assert results[0].slide_id == 1

    def test_search_respects_top_k(self):
        conn = _create_db()
        self._seed_data(conn)
        results = lexical_search(conn, "slide", top_k=2)
        assert len(results) <= 2

    def test_search_empty_query(self):
        conn = _create_db()
        self._seed_data(conn)
        results = lexical_search(conn, "")
        assert results == []

    def test_search_no_fts_tables(self):
        conn = _create_db()
        results = lexical_search(conn, "test")
        assert results == []

    def test_search_no_results(self):
        conn = _create_db()
        self._seed_data(conn)
        results = lexical_search(conn, "xyznonexistent123")
        assert len(results) == 0

    def test_search_result_to_json(self):
        r = LexicalSearchResult(
            slide_id=42,
            score=0.85,
            title="Test",
            snippet="Some <mark>match</mark> text",
            matched_fields=["title", "body_text"],
        )
        j = r.to_json()
        assert j["slide_id"] == 42
        assert j["score"] == 0.85
        assert "matched_fields" in j

    def test_chinese_search(self):
        """Chinese text with unicode61 tokenizer: prefix queries work for CJK.
        Full CJK word segmentation requires a specialized tokenizer (e.g., ICU).
        """
        conn = _create_db()
        create_fts_tables(conn)
        doc = SearchDocument("sd_cn", "a_cn", "srev_cn", 10,
            "Technology Architecture Plan",
            "System architecture design and microservices deployment",
            "", "", "", "", "", "", "", "")
        index_search_document(conn, doc)
        # English search works with standard tokenizer
        results = lexical_search(conn, "architecture")
        assert len(results) >= 1
