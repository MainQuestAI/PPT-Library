"""Tests for schema v4 → v5 migration (1.5-D)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ppt_lib.migrations import (
    apply_migration,
    plan_migration,
    restore_from_backup,
    verify_migration,
)


def _create_v4_db(path: Path, *, slide_count: int = 5) -> sqlite3.Connection:
    """Create a minimal schema v4 database for testing."""
    conn = sqlite3.connect(str(path))

    # Core tables
    conn.execute(
        """CREATE TABLE _meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )
    conn.execute("INSERT INTO _meta (key, value) VALUES ('schema_version', '4')")

    conn.execute(
        """CREATE TABLE presentations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            filename TEXT NOT NULL,
            project_name TEXT,
            slide_count INTEGER DEFAULT 0,
            content_hash TEXT,
            file_size INTEGER DEFAULT 0,
            file_mtime REAL DEFAULT 0
        )"""
    )

    conn.execute(
        """CREATE TABLE slides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            presentation_id INTEGER NOT NULL REFERENCES presentations(id),
            slide_index INTEGER NOT NULL,
            title TEXT,
            text_content TEXT NOT NULL DEFAULT '',
            screenshot_hash TEXT,
            source TEXT NOT NULL DEFAULT 'text_extraction',
            extraction_warnings TEXT DEFAULT '[]',
            metadata_json TEXT DEFAULT '{}'
        )"""
    )

    # Insert test data
    conn.execute(
        "INSERT INTO presentations (path, filename, slide_count) VALUES (?, ?, ?)",
        ("/test/deck.pptx", "deck.pptx", slide_count),
    )
    for i in range(1, slide_count + 1):
        conn.execute(
            "INSERT INTO slides (presentation_id, slide_index, text_content) VALUES (1, ?, ?)",
            (i, f"Slide {i} text"),
        )

    conn.commit()
    return conn


class TestMigrationPlan:
    def test_plan_from_v4(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path, slide_count=10)

        plan = plan_migration(conn, db_path)
        assert plan.from_version == 4
        assert plan.to_version == 5
        assert plan.estimated_rows_to_backfill == 10
        assert len(plan.tables_to_create) == 10
        assert plan.backup_path is not None
        conn.close()

    def test_plan_to_json(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path)
        plan = plan_migration(conn, db_path)
        j = plan.to_json()
        assert j["from_version"] == 4
        assert j["to_version"] == 5
        assert "backup_path" in j
        conn.close()


class TestMigrationApply:
    def test_apply_creates_tables(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path, slide_count=3)
        conn.close()

        conn = sqlite3.connect(str(db_path))
        result = apply_migration(conn, db_path)

        assert result.status == "completed"
        assert result.from_version == 4
        assert result.to_version == 5
        assert result.rows_backfilled == 3
        assert result.error is None

        # Verify tables exist
        cursor = conn.cursor()
        for table in ["asset_identity_map", "deck_asset_identity", "jobs", "migration_journal"]:
            cursor.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            assert cursor.fetchone()[0] > 0, f"Table {table} not created"

        conn.close()

    def test_apply_creates_backup(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path, slide_count=2)
        conn.close()

        conn = sqlite3.connect(str(db_path))
        result = apply_migration(conn, db_path)
        conn.close()

        assert result.backup_path is not None
        backup = Path(result.backup_path)
        assert backup.is_file()
        assert backup.stat().st_size > 0

    def test_apply_backfills_identities(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path, slide_count=5)
        conn.close()

        conn = sqlite3.connect(str(db_path))
        result = apply_migration(conn, db_path)

        assert result.rows_backfilled == 5

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM asset_identity_map")
        assert cursor.fetchone()[0] == 5

        # Check status is legacy_unresolved
        cursor.execute(
            "SELECT COUNT(*) FROM asset_identity_map WHERE identity_status = 'legacy_unresolved'"
        )
        assert cursor.fetchone()[0] == 5
        conn.close()

    def test_apply_updates_schema_version(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path)
        conn.close()

        conn = sqlite3.connect(str(db_path))
        apply_migration(conn, db_path)

        cursor = conn.cursor()
        cursor.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
        assert cursor.fetchone()[0] == "5"
        conn.close()

    def test_apply_writes_journal(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path)
        conn.close()

        conn = sqlite3.connect(str(db_path))
        result = apply_migration(conn, db_path)

        cursor = conn.cursor()
        cursor.execute("SELECT status FROM migration_journal WHERE migration_id = ?", (result.migration_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "completed"
        conn.close()

    def test_apply_without_backfill(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path, slide_count=3)
        conn.close()

        conn = sqlite3.connect(str(db_path))
        result = apply_migration(conn, db_path, backfill_identities=False)

        assert result.rows_backfilled == 0
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM asset_identity_map")
        assert cursor.fetchone()[0] == 0
        conn.close()

    def test_migration_result_to_json(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path)
        conn.close()

        conn = sqlite3.connect(str(db_path))
        result = apply_migration(conn, db_path)
        j = result.to_json()
        assert j["status"] == "completed"
        assert j["from_version"] == 4
        assert j["to_version"] == 5
        conn.close()


class TestRestore:
    def test_restore_from_backup(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path, slide_count=3)
        conn.close()

        # Migrate
        conn = sqlite3.connect(str(db_path))
        result = apply_migration(conn, db_path)
        conn.close()

        # Verify schema is 5
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
        assert cursor.fetchone()[0] == "5"
        conn.close()

        # Restore
        backup_path = Path(result.backup_path)
        assert restore_from_backup(db_path, backup_path)

        # Verify schema is back to 4
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
        assert cursor.fetchone()[0] == "4"
        conn.close()

    def test_restore_missing_backup(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        _create_v4_db(db_path).close()
        missing = tmp_path / "nonexistent.db"
        assert restore_from_backup(db_path, missing) is False


class TestVerify:
    def test_verify_after_migration(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path, slide_count=5)
        conn.close()

        conn = sqlite3.connect(str(db_path))
        apply_migration(conn, db_path)
        result = verify_migration(conn)

        assert result["schema_version"] == 5
        tables_exist = result["tables_exist"]
        assert isinstance(tables_exist, dict)
        assert all(tables_exist.values()), f"Some tables missing: {tables_exist}"
        conn.close()

    def test_verify_before_migration(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        conn = _create_v4_db(db_path)

        result = verify_migration(conn)
        assert result["schema_version"] == 4
        conn.close()
