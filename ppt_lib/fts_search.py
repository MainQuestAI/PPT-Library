"""FTS5 search documents for hybrid retrieval (v1.6-A).

Establishes a Search Document model and FTS5 tables for lexical recall.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

# FTS5 table name
FTS_TABLE = "slides_fts"

# Tokenizer: supports Chinese and English
FTS_TOKENIZER = "unicode61"


@dataclass(frozen=True)
class SearchDocument:
    """A search document for a single slide revision."""

    search_document_id: str
    canonical_asset_id: str
    slide_revision_id: str
    legacy_slide_id: int | None
    title: str
    body_text: str
    ocr_markdown: str
    ai_summary: str
    deck_summary: str
    narrative_role: str
    page_role: str
    page_archetype: str
    industry: str
    scenario: str

    def to_fts_text(self) -> str:
        """Concatenate all text fields for FTS indexing."""
        parts = [
            self.title,
            self.body_text,
            self.ocr_markdown,
            self.ai_summary,
            self.deck_summary,
            self.narrative_role,
            self.page_role,
            self.page_archetype,
            self.industry,
            self.scenario,
        ]
        return " ".join(p for p in parts if p)


@dataclass(frozen=True)
class LexicalSearchResult:
    """A result from FTS5 lexical search."""

    slide_id: int
    score: float
    title: str | None
    snippet: str
    matched_fields: list[str]

    def to_json(self) -> dict[str, object]:
        return {
            "slide_id": self.slide_id,
            "score": round(self.score, 4),
            "title": self.title,
            "snippet": self.snippet,
            "matched_fields": self.matched_fields,
        }


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------


def create_fts_tables(conn: sqlite3.Connection) -> None:
    """Create FTS5 tables if they don't exist."""
    conn.execute(
        f"""CREATE VIRTUAL TABLE IF NOT EXISTS [{FTS_TABLE}]
            USING fts5(
                search_document_id UNINDEXED,
                canonical_asset_id UNINDEXED,
                slide_revision_id UNINDEXED,
                legacy_slide_id UNINDEXED,
                title,
                body_text,
                ocr_markdown,
                ai_summary,
                deck_summary,
                narrative_role,
                page_role,
                page_archetype,
                industry,
                scenario,
                tokenize='{FTS_TOKENIZER}'
            )"""
    )
    conn.commit()


def fts_tables_exist(conn: sqlite3.Connection) -> bool:
    """Check if FTS5 tables exist."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
        (FTS_TABLE,),
    )
    return cursor.fetchone()[0] > 0


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


def index_search_document(conn: sqlite3.Connection, doc: SearchDocument) -> None:
    """Insert or replace a search document in FTS5."""
    # FTS5 requires delete + insert for replace semantics
    conn.execute(
        f"DELETE FROM [{FTS_TABLE}] WHERE search_document_id = ?",
        (doc.search_document_id,),
    )
    conn.execute(
        f"""INSERT INTO [{FTS_TABLE}]
            (search_document_id, canonical_asset_id, slide_revision_id,
             legacy_slide_id, title, body_text, ocr_markdown, ai_summary,
             deck_summary, narrative_role, page_role, page_archetype,
             industry, scenario)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            doc.search_document_id,
            doc.canonical_asset_id,
            doc.slide_revision_id,
            str(doc.legacy_slide_id) if doc.legacy_slide_id else "",
            doc.title,
            doc.body_text,
            doc.ocr_markdown,
            doc.ai_summary,
            doc.deck_summary,
            doc.narrative_role,
            doc.page_role,
            doc.page_archetype,
            doc.industry,
            doc.scenario,
        ),
    )
    conn.commit()


def index_from_slides(conn: sqlite3.Connection, *, limit: int | None = None) -> int:
    """Build FTS5 documents from existing slides table.

    Returns the number of documents indexed.
    """
    if not fts_tables_exist(conn):
        create_fts_tables(conn)

    cursor = conn.cursor()
    query = """
        SELECT s.id, s.title, s.text_content, s.metadata_json,
               s.slide_revision_id, s.canonical_asset_id
        FROM slides s
        LEFT JOIN asset_identity_map aim
            ON aim.legacy_slide_id = s.id
    """
    if limit:
        query += f" LIMIT {limit}"

    cursor.execute(query)
    count = 0

    for row in cursor.fetchall():
        slide_id, title, text_content, metadata_json, rev_id, canon_id = row

        metadata: dict[str, Any] = {}
        if metadata_json:
            try:
                import json
                metadata = json.loads(metadata_json)
            except Exception:
                pass

        doc = SearchDocument(
            search_document_id=f"sd_{slide_id}",
            canonical_asset_id=canon_id or f"legacy_{slide_id}",
            slide_revision_id=rev_id or f"srev_legacy_{slide_id}",
            legacy_slide_id=slide_id,
            title=title or "",
            body_text=text_content or "",
            ocr_markdown=metadata.get("ocr_markdown", "") or "",
            ai_summary=metadata.get("ai_summary", "") or "",
            deck_summary=metadata.get("deck_summary", "") or "",
            narrative_role=metadata.get("narrative_role", "") or "",
            page_role=metadata.get("page_role", "") or "",
            page_archetype=metadata.get("page_archetype", "") or "",
            industry=metadata.get("industry", "") or "",
            scenario=metadata.get("scenario", "") or "",
        )
        index_search_document(conn, doc)
        count += 1

    return count


def remove_search_document(conn: sqlite3.Connection, search_document_id: str) -> None:
    """Remove a search document from FTS5."""
    conn.execute(
        f"DELETE FROM [{FTS_TABLE}] WHERE search_document_id = ?",
        (search_document_id,),
    )
    conn.commit()


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS5 index from scratch by re-reading from the slides table.

    This deletes all existing FTS rows and re-indexes from the source slides
    table, so the index reflects current slide content (not just compacted).
    If the slides table is missing, only the delete is performed.
    """
    conn.execute(f"DELETE FROM [{FTS_TABLE}]")
    conn.commit()
    try:
        index_from_slides(conn)
    except sqlite3.OperationalError:
        # slides table missing — nothing to reindex
        pass


def get_fts_document_count(conn: sqlite3.Connection) -> int:
    """Get the number of documents in the FTS5 index."""
    cursor = conn.cursor()
    cursor.execute(f"SELECT COUNT(*) FROM [{FTS_TABLE}]")
    return cursor.fetchone()[0]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def lexical_search(
    conn: sqlite3.Connection,
    query: str,
    *,
    top_k: int = 10,
    snippet_size: int = 200,
) -> list[LexicalSearchResult]:
    """Perform FTS5 lexical search using BM25 ranking.

    Returns results sorted by BM25 score (lower is better, so negated).
    """
    if not fts_tables_exist(conn):
        return []

    # Sanitize query: escape special FTS characters
    safe_query = _sanitize_fts_query(query)
    if not safe_query:
        return []

    cursor = conn.cursor()
    cursor.execute(
        f"""SELECT
                CAST(legacy_slide_id AS INTEGER),
                -bm25([{FTS_TABLE}], 0, 0, 0, 0, 10, 5, 3, 3, 3, 3, 3, 3, 3, 3) AS score,
                title,
                snippet([{FTS_TABLE}], 5, '<mark>', '</mark>', '...', ?),
                ''
            FROM [{FTS_TABLE}]
            WHERE [{FTS_TABLE}] MATCH ?
            ORDER BY score
            LIMIT ?""",
        (snippet_size, safe_query, top_k),
    )

    results: list[LexicalSearchResult] = []
    for row in cursor.fetchall():
        slide_id = row[0]
        score = row[1] if row[1] is not None else 0.0
        title = row[2] if row[2] else None
        snippet = row[3] if row[3] else ""

        results.append(LexicalSearchResult(
            slide_id=slide_id,
            score=score,
            title=title,
            snippet=snippet,
            matched_fields=[],
        ))

    return results


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a query for FTS5 MATCH.

    - Remove special characters that could cause FTS syntax errors
    - Wrap terms in double quotes for phrase matching
    """
    # Remove FTS special chars and double quotes (prevent unterminated string)
    cleaned = re.sub(r'[*^~():"]+', '', query)
    cleaned = cleaned.strip()
    if not cleaned:
        return ""

    # Split into terms and quote each one
    terms = cleaned.split()
    quoted = " ".join(f'"{t}"' for t in terms if t.strip())
    return quoted
