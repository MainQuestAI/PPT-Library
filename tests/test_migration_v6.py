from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ppt_lib.db import SCHEMA_VERSION, connect, get_schema_version, init_db
from ppt_lib.migrations.schema_v6 import migrate_v5_to_v6


def _v5_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO _meta VALUES ('schema_version', '5');
        CREATE TABLE presentations (
          id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
          project_name TEXT, slide_count INTEGER, content_hash TEXT,
          file_size INTEGER, file_mtime REAL, indexed_at TEXT, last_validated_at TEXT
        );
        CREATE TABLE slides (
          id INTEGER PRIMARY KEY, presentation_id INTEGER REFERENCES presentations(id),
          slide_index INTEGER NOT NULL, title TEXT, text_content TEXT, embedding BLOB,
          screenshot_hash TEXT, source TEXT NOT NULL, extraction_warnings TEXT,
          metadata_json TEXT, raw_text TEXT, ai_summary TEXT, visual_summary TEXT,
          summary_status TEXT, profile_id INTEGER, text_hash TEXT, content_hash TEXT,
          canonical_slide_id INTEGER, industry TEXT, scenario TEXT, narrative_role TEXT,
          win_rate REAL, won_count INTEGER DEFAULT 0, lost_count INTEGER DEFAULT 0,
          reuse_count INTEGER DEFAULT 0, last_deal_outcome TEXT, quality_rating INTEGER,
          origin_type TEXT DEFAULT 'original', UNIQUE(presentation_id, slide_index)
        );
        CREATE TABLE library_sources (id INTEGER PRIMARY KEY);
        CREATE TABLE workspace_profiles (id INTEGER PRIMARY KEY);
        CREATE TABLE slide_assets (
          id INTEGER PRIMARY KEY, slide_id INTEGER NOT NULL REFERENCES slides(id),
          workspace_profile_id INTEGER, source_id INTEGER, asset_type TEXT NOT NULL,
          asset_uri TEXT NOT NULL, asset_hash TEXT, metadata_json TEXT,
          created_at TEXT, updated_at TEXT, UNIQUE(slide_id, asset_type, asset_uri)
        );
        CREATE TABLE asset_identity_map (
          canonical_asset_id TEXT NOT NULL, slide_revision_id TEXT NOT NULL,
          legacy_slide_id INTEGER, identity_status TEXT NOT NULL,
          algorithm_version TEXT NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, PRIMARY KEY(canonical_asset_id, slide_revision_id)
        );
        """
    )
    conn.execute(
        "INSERT INTO presentations VALUES (1, '/deck.pptx', 'deck.pptx', NULL, 1, 'h', 1, 1, NULL, NULL)"
    )
    conn.execute(
        """INSERT INTO slides
           (id, presentation_id, slide_index, title, text_content, source, ai_summary, summary_status)
           VALUES (10, 1, 0, 'Architecture', 'cloud architecture', 'text_extraction', 'old', 'ok')"""
    )
    conn.execute(
        "INSERT INTO slide_assets (id, slide_id, asset_type, asset_uri) VALUES (7, 10, 'thumbnail', '/tmp/10.png')"
    )
    conn.execute(
        """INSERT INTO asset_identity_map VALUES
           ('asset_10', 'srev_legacy_10', 10, 'legacy_unresolved', 'v1', 'now', 'now')"""
    )
    conn.commit()
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info([{table}])")}


def test_v5_migration_separates_artifacts_and_canonical_assets(tmp_path: Path) -> None:
    conn = _v5_connection(tmp_path / "v5.db")

    migrate_v5_to_v6(conn)

    assert get_schema_version(conn) == 6
    assert {"id", "slide_id", "asset_uri"} <= _columns(conn, "slide_artifacts")
    assert {"canonical_asset_id", "labels_json"} <= _columns(conn, "slide_assets")
    assert conn.execute("SELECT id, slide_id, asset_uri FROM slide_artifacts").fetchone() == (7, 10, "/tmp/10.png")
    assert conn.execute("SELECT canonical_asset_id FROM slide_assets").fetchone() == ("asset_10",)
    assert conn.execute("SELECT slide_revision_id FROM slide_revisions").fetchone() == ("srev_legacy_10",)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v5_migration_rolls_back_when_precommit_foreign_key_check_fails(tmp_path: Path) -> None:
    conn = _v5_connection(tmp_path / "invalid-v5.db")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO slide_assets (id, slide_id, asset_type, asset_uri) VALUES (8, 999, 'thumbnail', '/tmp/orphan.png')"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="foreign key check failed"):
        migrate_v5_to_v6(conn)

    assert get_schema_version(conn) == 5
    assert {"id", "slide_id", "asset_uri"} <= _columns(conn, "slide_assets")
    assert _columns(conn, "slide_artifacts") == set()


def test_v5_migration_rejects_revision_owned_by_multiple_canonical_assets(tmp_path: Path) -> None:
    conn = _v5_connection(tmp_path / "revision-collision.db")
    conn.execute(
        "INSERT INTO presentations VALUES (2, '/deck-2.pptx', 'deck-2.pptx', NULL, 1, 'h2', 1, 1, NULL, NULL)"
    )
    conn.execute(
        """INSERT INTO slides (id, presentation_id, slide_index, text_content, source)
           VALUES (20, 2, 0, 'second slide', 'text_extraction')"""
    )
    conn.execute(
        """INSERT INTO asset_identity_map VALUES
           ('asset_20', 'srev_legacy_10', 20, 'legacy_unresolved', 'v1', 'now', 'now')"""
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="multiple canonical assets"):
        migrate_v5_to_v6(conn)

    assert get_schema_version(conn) == 5
    assert {"id", "slide_id", "asset_uri"} <= _columns(conn, "slide_assets")
    assert _columns(conn, "slide_artifacts") == set()
    assert conn.execute("SELECT COUNT(*) FROM asset_identity_map").fetchone()[0] == 2


def test_idempotent_v6_migration_preserves_callers_outer_transaction(tmp_path: Path) -> None:
    conn = connect(tmp_path / "v6-transaction.db")
    init_db(conn)
    conn.execute(
        "INSERT INTO presentations (path, filename) VALUES ('/pending.pptx', 'pending.pptx')"
    )
    assert conn.in_transaction is True

    migrate_v5_to_v6(conn)

    assert conn.in_transaction is True
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM presentations WHERE path = '/pending.pptx'").fetchone()[0] == 0


def test_v6_identity_detaches_and_artifact_cascades_on_slide_delete(tmp_path: Path) -> None:
    conn = _v5_connection(tmp_path / "v5.db")
    migrate_v5_to_v6(conn)

    conn.execute("DELETE FROM slides WHERE id = 10")

    assert conn.execute("SELECT COUNT(*) FROM slide_artifacts").fetchone()[0] == 0
    assert conn.execute("SELECT legacy_slide_id FROM asset_identity_map").fetchone()[0] is None


def test_init_db_creates_real_v6_schema_idempotently(tmp_path: Path) -> None:
    conn = connect(tmp_path / "fresh.db")
    init_db(conn)
    init_db(conn)

    assert get_schema_version(conn) == SCHEMA_VERSION == 6
    assert {"canonical_asset_id", "labels_json"} <= _columns(conn, "slide_assets")
    assert {"id", "slide_id", "asset_uri"} <= _columns(conn, "slide_artifacts")
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'slides_fts'").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_usage_and_lineage_restrict_source_slide_deletion(tmp_path: Path) -> None:
    conn = connect(tmp_path / "index.db")
    init_db(conn)
    conn.execute("INSERT INTO presentations (id, path, filename) VALUES (1, '/a.pptx', 'a.pptx')")
    conn.execute("INSERT INTO presentations (id, path, filename) VALUES (2, '/b.pptx', 'b.pptx')")
    conn.execute(
        "INSERT INTO slides (id, presentation_id, slide_index, source) VALUES (1, 1, 0, 'text_extraction')"
    )
    conn.execute(
        "INSERT INTO slides (id, presentation_id, slide_index, source) VALUES (2, 2, 0, 'text_extraction')"
    )
    conn.execute("INSERT INTO deals (id, deal_name, outcome) VALUES (1, 'deal', 'won')")
    conn.execute(
        "INSERT INTO assemble_runs (id, run_name, status) VALUES (1, 'run', 'completed')"
    )
    conn.execute(
        "INSERT INTO slide_usage (slide_id, deal_id, deck_presentation_id) VALUES (1, 1, 2)"
    )
    conn.execute(
        """INSERT INTO slide_lineage
           (derived_slide_id, source_slide_id, assemble_run_id, derivation_type)
           VALUES (2, 1, 1, 'copied')"""
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM slides WHERE id = 1")
