"""Schema migration engine for PPT Library.

Handles migration from schema v4 to v5 (identity + job engine tables).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ppt_lib.identity.fingerprint import (
    FINGERPRINT_VERSION,
)


@dataclass(frozen=True)
class MigrationPlan:
    """Describes what a migration will do."""

    from_version: int
    to_version: int
    tables_to_create: list[str]
    tables_to_alter: list[str]
    estimated_rows_to_backfill: int
    backup_path: Path | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "tables_to_create": self.tables_to_create,
            "tables_to_alter": self.tables_to_alter,
            "estimated_rows_to_backfill": self.estimated_rows_to_backfill,
            "backup_path": str(self.backup_path) if self.backup_path else None,
        }


@dataclass(frozen=True)
class MigrationResult:
    """Result of a completed migration."""

    migration_id: str
    from_version: int
    to_version: int
    status: str  # completed | failed | rolled_back
    started_at: str
    finished_at: str | None
    backup_path: str | None
    rows_backfilled: int
    error: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "migration_id": self.migration_id,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "backup_path": self.backup_path,
            "rows_backfilled": self.rows_backfilled,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Schema 5 tables
# ---------------------------------------------------------------------------

_SCHEMA_5_TABLES = """
CREATE TABLE IF NOT EXISTS asset_identity_map (
    canonical_asset_id TEXT NOT NULL,
    slide_revision_id TEXT NOT NULL,
    legacy_slide_id INTEGER,
    identity_status TEXT NOT NULL DEFAULT 'legacy_unresolved',
    algorithm_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (canonical_asset_id, slide_revision_id)
);

CREATE TABLE IF NOT EXISTS deck_asset_identity (
    deck_asset_id TEXT PRIMARY KEY,
    deck_revision_id TEXT NOT NULL,
    identity_status TEXT NOT NULL DEFAULT 'legacy_unresolved',
    algorithm_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identity_overrides (
    override_id TEXT PRIMARY KEY,
    canonical_asset_id TEXT NOT NULL,
    override_type TEXT NOT NULL,
    override_value TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS contract_registry (
    contract_name TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    schema_hash TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    producer_version TEXT
);

CREATE TABLE IF NOT EXISTS migration_journal (
    migration_id TEXT PRIMARY KEY,
    from_version INTEGER NOT NULL,
    to_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    backup_path TEXT,
    error_json TEXT,
    row_counts_json TEXT,
    verify_result_json TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    idempotency_key TEXT UNIQUE,
    source_id TEXT,
    source_locator TEXT,
    source_content_hash TEXT,
    pipeline_config_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    current_stage TEXT,
    total_units INTEGER DEFAULT 0,
    completed_units INTEGER DEFAULT 0,
    failed_units INTEGER DEFAULT 0,
    attempt INTEGER DEFAULT 1,
    cancel_requested INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    started_at TEXT,
    finished_at TEXT,
    error_json TEXT,
    warning_json TEXT
);

CREATE TABLE IF NOT EXISTS job_stages (
    stage_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    artifact_path TEXT,
    error_json TEXT
);

CREATE TABLE IF NOT EXISTS job_events (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS job_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    stage_name TEXT NOT NULL,
    checkpoint_data_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS staged_assets (
    staged_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    slide_revision_id TEXT,
    asset_data_json TEXT NOT NULL,
    committed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

_SCHEMA_5_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_identity_revision ON asset_identity_map(slide_revision_id)",
    "CREATE INDEX IF NOT EXISTS idx_identity_canonical ON asset_identity_map(canonical_asset_id)",
    "CREATE INDEX IF NOT EXISTS idx_identity_status ON asset_identity_map(identity_status)",
    "CREATE INDEX IF NOT EXISTS idx_deck_identity_revision ON deck_asset_identity(deck_revision_id)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_idempotency ON jobs(idempotency_key)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_job_stages_job ON job_stages(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_staged_assets_job ON staged_assets(job_id)",
    "CREATE INDEX IF NOT EXISTS idx_staged_assets_committed ON staged_assets(committed)",
    "CREATE INDEX IF NOT EXISTS idx_migration_journal_status ON migration_journal(status)",
]


# ---------------------------------------------------------------------------
# Migration operations
# ---------------------------------------------------------------------------


def plan_migration(conn: sqlite3.Connection, db_path: Path) -> MigrationPlan:
    """Generate a migration plan from current schema to target."""
    cursor = conn.cursor()

    # Current schema version
    cursor.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
    row = cursor.fetchone()
    current = int(row[0]) if row else 0

    # Count slides to backfill
    cursor.execute("SELECT COUNT(*) FROM slides")
    slide_count = cursor.fetchone()[0]

    tables_to_create = [
        "asset_identity_map",
        "deck_asset_identity",
        "identity_overrides",
        "contract_registry",
        "migration_journal",
        "jobs",
        "job_stages",
        "job_events",
        "job_checkpoints",
        "staged_assets",
    ]

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"schema_v{current}_{timestamp}.db"

    return MigrationPlan(
        from_version=current,
        to_version=5,
        tables_to_create=tables_to_create,
        tables_to_alter=[],
        estimated_rows_to_backfill=slide_count,
        backup_path=backup_path,
    )


def apply_migration(
    conn: sqlite3.Connection,
    db_path: Path,
    *,
    backfill_identities: bool = True,
) -> MigrationResult:
    """Execute schema migration from v4 to v5.

    Steps:
    1. Create backup
    2. Create new tables
    3. Backfill identity mappings
    4. Update schema version
    5. Verify
    """
    import uuid

    plan = plan_migration(conn, db_path)
    migration_id = str(uuid.uuid4())
    started_at = datetime.now(UTC).isoformat()

    # Step 1: Backup
    if plan.backup_path:
        shutil.copy2(db_path, plan.backup_path)

    # Write journal entry (planned)
    _write_journal(conn, migration_id, plan, status="in_progress", backup_path=plan.backup_path)

    try:
        # Step 2: Create tables
        conn.executescript(_SCHEMA_5_TABLES)
        for idx_sql in _SCHEMA_5_INDEXES:
            conn.execute(idx_sql)

        # Step 3: Backfill identities (no commit inside)
        rows_backfilled = 0
        if backfill_identities:
            rows_backfilled = _backfill_identities(conn, commit=False)

        # Step 4: Update schema version
        conn.execute(
            "UPDATE _meta SET value = '5' WHERE key = 'schema_version'"
        )

        # Step 4b: Single commit for all changes
        conn.commit()

        # Step 5: Verify
        verify_result = _verify_migration(conn, plan)

        finished_at = datetime.now(UTC).isoformat()
        _write_journal(
            conn,
            migration_id,
            plan,
            status="completed",
            backup_path=plan.backup_path,
            finished_at=finished_at,
            verify_result=verify_result,
            rows_backfilled=rows_backfilled,
        )

        return MigrationResult(
            migration_id=migration_id,
            from_version=plan.from_version,
            to_version=plan.to_version,
            status="completed",
            started_at=started_at,
            finished_at=finished_at,
            backup_path=str(plan.backup_path) if plan.backup_path else None,
            rows_backfilled=rows_backfilled,
            error=None,
        )
    except Exception as exc:
        conn.rollback()
        finished_at = datetime.now(UTC).isoformat()
        _write_journal(
            conn,
            migration_id,
            plan,
            status="failed",
            backup_path=plan.backup_path,
            finished_at=finished_at,
            error=str(exc),
        )
        return MigrationResult(
            migration_id=migration_id,
            from_version=plan.from_version,
            to_version=plan.to_version,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            backup_path=str(plan.backup_path) if plan.backup_path else None,
            rows_backfilled=0,
            error=str(exc),
        )


def restore_from_backup(db_path: Path, backup_path: Path) -> bool:
    """Restore database from a backup file."""
    if not backup_path.is_file():
        return False
    shutil.copy2(backup_path, db_path)
    return True


def verify_migration(conn: sqlite3.Connection) -> dict[str, object]:
    """Verify migration integrity."""
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
    row = cursor.fetchone()
    schema_version = int(row[0]) if row else 0

    result: dict[str, object] = {
        "schema_version": schema_version,
    }

    expected_tables = [
        "asset_identity_map",
        "deck_asset_identity",
        "identity_overrides",
        "contract_registry",
        "migration_journal",
        "jobs",
        "job_stages",
        "job_events",
        "job_checkpoints",
        "staged_assets",
    ]

    tables_exist: dict[str, bool] = {}
    row_counts: dict[str, int] = {}

    for table in expected_tables:
        cursor.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        exists = cursor.fetchone()[0] > 0
        tables_exist[table] = exists
        if exists:
            cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
            row_counts[table] = cursor.fetchone()[0]

    result["tables_exist"] = tables_exist
    result["row_counts"] = row_counts

    # Verify slide count matches identity map
    cursor.execute("SELECT COUNT(*) FROM slides")
    slide_count = cursor.fetchone()[0]
    if "asset_identity_map" in row_counts:
        identity_count = row_counts["asset_identity_map"]
        result["identity_coverage"] = (
            identity_count / slide_count * 100 if slide_count > 0 else 0
        )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _backfill_identities(conn: sqlite3.Connection, *, commit: bool = True) -> int:
    """Backfill identity mappings for existing slides."""
    import uuid

    cursor = conn.cursor()
    now = datetime.now(UTC).isoformat()
    count = 0

    cursor.execute(
        "SELECT s.id, s.presentation_id, p.path "
        "FROM slides s JOIN presentations p ON s.presentation_id = p.id"
    )
    rows = cursor.fetchall()

    for slide_id, _presentation_id, _file_path in rows:
        # Generate a deterministic canonical ID from legacy slide_id
        canonical_id = f"asset_{uuid.uuid5(uuid.NAMESPACE_URL, f'slide:{slide_id}')}"
        revision_id = f"srev_legacy_{slide_id}"

        conn.execute(
            """INSERT OR IGNORE INTO asset_identity_map
               (canonical_asset_id, slide_revision_id, legacy_slide_id,
                identity_status, algorithm_version, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                canonical_id,
                revision_id,
                slide_id,
                "legacy_unresolved",
                FINGERPRINT_VERSION,
                now,
                now,
            ),
        )
        count += 1

    if commit:
        conn.commit()
    return count


def _verify_migration(
    conn: sqlite3.Connection,
    plan: MigrationPlan,
) -> dict[str, object]:
    """Verify migration results."""
    result: dict[str, object] = {"tables_created": True, "indexes_created": True}

    # Check all tables exist
    for table in plan.tables_to_create:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if cursor.fetchone()[0] == 0:
            result["tables_created"] = False
            result["missing_table"] = table
            break

    # Check schema version updated
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
    row = cursor.fetchone()
    result["schema_version"] = int(row[0]) if row else 0

    return result


def _write_journal(
    conn: sqlite3.Connection,
    migration_id: str,
    plan: MigrationPlan,
    *,
    status: str,
    backup_path: Path | None = None,
    finished_at: str | None = None,
    verify_result: dict[str, object] | None = None,
    error: str | None = None,
    rows_backfilled: int = 0,
) -> None:
    """Write migration journal entry."""
    # Ensure journal table exists
    conn.execute(
        """CREATE TABLE IF NOT EXISTS migration_journal (
            migration_id TEXT PRIMARY KEY,
            from_version INTEGER NOT NULL,
            to_version INTEGER NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            backup_path TEXT,
            error_json TEXT,
            row_counts_json TEXT,
            verify_result_json TEXT
        )"""
    )

    conn.execute(
        """INSERT OR REPLACE INTO migration_journal
           (migration_id, from_version, to_version, status, started_at,
            finished_at, backup_path, error_json, row_counts_json, verify_result_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            migration_id,
            plan.from_version,
            plan.to_version,
            status,
            datetime.now(UTC).isoformat(),
            finished_at,
            str(backup_path) if backup_path else None,
            json.dumps({"error": error}) if error else None,
            json.dumps({"rows_backfilled": rows_backfilled}),
            json.dumps(verify_result) if verify_result else None,
        ),
    )
    conn.commit()
