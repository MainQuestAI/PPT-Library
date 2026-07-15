"""Schema v6 migration: explicit asset roles and deletion lifecycles."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial

from ppt_lib.asset_schema import SlideRevision, create_asset_schema_tables, insert_slide_revision, upsert_slide_asset
from ppt_lib.identity.fingerprint import FINGERPRINT_VERSION

TARGET_SCHEMA_VERSION = 6

_ARTIFACT_COLUMNS = (
    "id",
    "slide_id",
    "workspace_profile_id",
    "source_id",
    "asset_type",
    "asset_uri",
    "asset_hash",
    "metadata_json",
    "created_at",
    "updated_at",
)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info([{table}])")}


def migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    """Migrate one connection to schema v6 atomically and idempotently.

    The caller owns the pre-migration backup. Foreign keys are disabled only
    for the table-copy window and are validated before this function returns.
    """
    caller_transaction = conn.in_transaction
    current = _schema_version(conn)
    slide_assets_columns = table_columns(conn, "slide_assets")
    already_v6 = (
        current >= TARGET_SCHEMA_VERSION
        and {"canonical_asset_id", "labels_json"} <= slide_assets_columns
        and {"id", "slide_id", "asset_uri"} <= table_columns(conn, "slide_artifacts")
    )
    if already_v6:
        create_asset_schema_tables(conn, commit=False)
        if not caller_transaction:
            conn.commit()
        return

    if caller_transaction:
        raise sqlite3.OperationalError("schema v6 migration requires no active transaction")
    foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        _validate_revision_ownership(conn)
        _separate_legacy_slide_assets(conn)
        _rebuild_lifecycle_tables(conn)
        _rebuild_identity_map(conn)
        create_asset_schema_tables(conn, commit=False)
        _backfill_current_identities(conn)
        _backfill_canonical_asset_rows(conn)
        _verify_revision_materialization(conn)
        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
            (str(TARGET_SCHEMA_VERSION),),
        )
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(f"schema v6 foreign key check failed: {violations[:5]}")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute(f"PRAGMA foreign_keys = {1 if foreign_keys_enabled else 0}")

    committed_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if committed_violations:
        raise sqlite3.IntegrityError(f"schema v6 post-commit foreign key check failed: {committed_violations[:5]}")


def _validate_revision_ownership(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "asset_identity_map"):
        return
    collision = conn.execute(
        """SELECT slide_revision_id, GROUP_CONCAT(DISTINCT canonical_asset_id)
           FROM asset_identity_map
           GROUP BY slide_revision_id
           HAVING COUNT(DISTINCT canonical_asset_id) > 1
           ORDER BY slide_revision_id
           LIMIT 1"""
    ).fetchone()
    if collision is not None:
        raise sqlite3.IntegrityError(
            f"slide revision {collision[0]} belongs to multiple canonical assets: {collision[1]}"
        )
    if not _table_exists(conn, "slide_revisions"):
        return
    conflict = conn.execute(
        """SELECT aim.slide_revision_id, aim.canonical_asset_id, sr.canonical_asset_id
           FROM asset_identity_map aim
           JOIN slide_revisions sr ON sr.slide_revision_id = aim.slide_revision_id
           WHERE sr.canonical_asset_id <> aim.canonical_asset_id
           ORDER BY aim.slide_revision_id
           LIMIT 1"""
    ).fetchone()
    if conflict is not None:
        raise sqlite3.IntegrityError(
            f"slide revision {conflict[0]} maps to canonical asset {conflict[1]} "
            f"but existing revision owner is {conflict[2]}"
        )


def _verify_revision_materialization(conn: sqlite3.Connection) -> None:
    missing = conn.execute(
        """SELECT aim.slide_revision_id, aim.canonical_asset_id
           FROM asset_identity_map aim
           LEFT JOIN slide_revisions sr
             ON sr.slide_revision_id = aim.slide_revision_id
            AND sr.canonical_asset_id = aim.canonical_asset_id
           WHERE sr.slide_revision_id IS NULL
           ORDER BY aim.slide_revision_id
           LIMIT 1"""
    ).fetchone()
    if missing is not None:
        raise sqlite3.IntegrityError(
            f"slide revision {missing[0]} for canonical asset {missing[1]} was not materialized"
        )


def _separate_legacy_slide_assets(conn: sqlite3.Connection) -> None:
    columns = table_columns(conn, "slide_assets")
    legacy_shape = {"id", "slide_id", "asset_uri"} <= columns
    canonical_shape = {"canonical_asset_id", "labels_json"} <= columns
    if columns and not legacy_shape and not canonical_shape:
        raise sqlite3.DatabaseError(f"unrecognized slide_assets schema: {sorted(columns)}")

    _create_slide_artifacts(conn, "slide_artifacts")
    if legacy_shape:
        names = ", ".join(_ARTIFACT_COLUMNS)
        conn.execute(
            f"INSERT OR IGNORE INTO slide_artifacts ({names}) SELECT {names} FROM slide_assets"
        )
        conn.execute("DROP TABLE slide_assets")


def _rebuild_lifecycle_tables(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "slide_artifacts"):
        _rebuild_table(
            conn,
            "slide_artifacts",
            _ARTIFACT_COLUMNS,
            _create_slide_artifacts,
        )

    specs: tuple[tuple[str, tuple[str, ...], str], ...] = (
        (
            "assemble_runs",
            ("id", "run_name", "manifest_hash", "output_presentation_id", "slide_count", "created_at", "status"),
            """CREATE TABLE [{name}] (
                id INTEGER PRIMARY KEY,
                run_name TEXT NOT NULL,
                manifest_hash TEXT,
                output_presentation_id INTEGER REFERENCES presentations(id) ON DELETE SET NULL,
                slide_count INTEGER,
                created_at TEXT,
                status TEXT CHECK(status IN ('completed','completed_pending_ingest','failed','partial'))
            )""",
        ),
        (
            "duplicate_groups",
            ("id", "canonical_slide_id", "workspace_profile_id", "created_at", "updated_at"),
            """CREATE TABLE [{name}] (
                id INTEGER PRIMARY KEY,
                canonical_slide_id INTEGER NOT NULL REFERENCES slides(id) ON DELETE CASCADE,
                workspace_profile_id INTEGER REFERENCES workspace_profiles(id) ON DELETE SET NULL,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(canonical_slide_id)
            )""",
        ),
        (
            "slide_duplicate_members",
            ("id", "duplicate_group_id", "slide_id", "canonical_slide_id", "is_canonical", "created_at"),
            """CREATE TABLE [{name}] (
                id INTEGER PRIMARY KEY,
                duplicate_group_id INTEGER NOT NULL REFERENCES duplicate_groups(id) ON DELETE CASCADE,
                slide_id INTEGER NOT NULL REFERENCES slides(id) ON DELETE CASCADE,
                canonical_slide_id INTEGER REFERENCES slides(id) ON DELETE SET NULL,
                is_canonical INTEGER DEFAULT 0,
                created_at TEXT,
                UNIQUE(duplicate_group_id, slide_id)
            )""",
        ),
        (
            "deck_families",
            (
                "id",
                "family_key",
                "project_name",
                "title",
                "representative_presentation_id",
                "presentation_count",
                "created_at",
                "updated_at",
            ),
            """CREATE TABLE [{name}] (
                id INTEGER PRIMARY KEY,
                family_key TEXT NOT NULL UNIQUE,
                project_name TEXT,
                title TEXT,
                representative_presentation_id INTEGER REFERENCES presentations(id) ON DELETE SET NULL,
                presentation_count INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            )""",
        ),
        (
            "presentation_versions",
            (
                "id", "presentation_id", "deck_family_id", "version_key", "version_role",
                "version_rank", "version_date", "is_representative", "confidence", "signals_json",
                "created_at", "updated_at",
            ),
            """CREATE TABLE [{name}] (
                id INTEGER PRIMARY KEY,
                presentation_id INTEGER NOT NULL UNIQUE REFERENCES presentations(id) ON DELETE CASCADE,
                deck_family_id INTEGER NOT NULL REFERENCES deck_families(id) ON DELETE CASCADE,
                version_key TEXT,
                version_role TEXT,
                version_rank INTEGER DEFAULT 0,
                version_date TEXT,
                is_representative INTEGER DEFAULT 0,
                confidence REAL,
                signals_json TEXT,
                created_at TEXT,
                updated_at TEXT
            )""",
        ),
        (
            "deck_insights",
            ("id", "presentation_id", "status", "summary_json", "warnings_json", "generated_at"),
            """CREATE TABLE [{name}] (
                id INTEGER PRIMARY KEY,
                presentation_id INTEGER NOT NULL UNIQUE REFERENCES presentations(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                summary_json TEXT,
                warnings_json TEXT,
                generated_at TEXT
            )""",
        ),
        (
            "slide_importance",
            (
                "id", "slide_id", "importance_score", "importance_reason", "page_role",
                "needs_visual", "status", "updated_at",
            ),
            """CREATE TABLE [{name}] (
                id INTEGER PRIMARY KEY,
                slide_id INTEGER NOT NULL UNIQUE REFERENCES slides(id) ON DELETE CASCADE,
                importance_score REAL,
                importance_reason TEXT,
                page_role TEXT,
                needs_visual INTEGER DEFAULT 0,
                status TEXT,
                updated_at TEXT
            )""",
        ),
    )
    for table, columns, create_template in specs:
        if _table_exists(conn, table):
            _rebuild_table(
                conn,
                table,
                columns,
                partial(_create_table_from_template, template=create_template),
            )

    index_statements = (
        "CREATE INDEX IF NOT EXISTS idx_slide_artifacts_slide_id ON slide_artifacts(slide_id)",
        "CREATE INDEX IF NOT EXISTS idx_slide_artifacts_profile_id ON slide_artifacts(workspace_profile_id)",
        "CREATE INDEX IF NOT EXISTS idx_duplicate_groups_canonical ON duplicate_groups(canonical_slide_id)",
        "CREATE INDEX IF NOT EXISTS idx_slide_duplicate_members_group ON slide_duplicate_members(duplicate_group_id)",
        "CREATE INDEX IF NOT EXISTS idx_slide_duplicate_members_slide ON slide_duplicate_members(slide_id)",
        "CREATE INDEX IF NOT EXISTS idx_presentation_versions_family ON presentation_versions(deck_family_id)",
        "CREATE INDEX IF NOT EXISTS idx_presentation_versions_representative ON presentation_versions(is_representative)",
        "CREATE INDEX IF NOT EXISTS idx_deck_families_representative ON deck_families(representative_presentation_id)",
        "CREATE INDEX IF NOT EXISTS idx_deck_insights_presentation ON deck_insights(presentation_id)",
        "CREATE INDEX IF NOT EXISTS idx_slide_importance_slide ON slide_importance(slide_id)",
    )
    for statement in index_statements:
        table = statement.rsplit(" ON ", 1)[1].split("(", 1)[0]
        if _table_exists(conn, table):
            conn.execute(statement)


def _rebuild_identity_map(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "asset_identity_map"):
        conn.execute(
            """CREATE TABLE asset_identity_map (
                canonical_asset_id TEXT NOT NULL,
                slide_revision_id TEXT NOT NULL,
                legacy_slide_id INTEGER REFERENCES slides(id) ON DELETE SET NULL,
                identity_status TEXT NOT NULL DEFAULT 'legacy_unresolved',
                algorithm_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(canonical_asset_id, slide_revision_id)
            )"""
        )
    else:
        conn.execute("DROP TABLE IF EXISTS asset_identity_map__v6")
        conn.execute(
            """CREATE TABLE asset_identity_map__v6 (
                canonical_asset_id TEXT NOT NULL,
                slide_revision_id TEXT NOT NULL,
                legacy_slide_id INTEGER REFERENCES slides(id) ON DELETE SET NULL,
                identity_status TEXT NOT NULL DEFAULT 'legacy_unresolved',
                algorithm_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(canonical_asset_id, slide_revision_id)
            )"""
        )
        conn.execute(
            """INSERT INTO asset_identity_map__v6
               (canonical_asset_id, slide_revision_id, legacy_slide_id, identity_status,
                algorithm_version, created_at, updated_at)
               WITH ranked AS (
                 SELECT aim.*,
                        ROW_NUMBER() OVER (
                          PARTITION BY legacy_slide_id
                          ORDER BY updated_at DESC, rowid DESC
                        ) AS current_rank
                 FROM asset_identity_map aim
               )
               SELECT canonical_asset_id, slide_revision_id,
                      CASE WHEN legacy_slide_id IS NOT NULL
                                AND current_rank = 1
                                AND EXISTS (SELECT 1 FROM slides s WHERE s.id = legacy_slide_id)
                           THEN legacy_slide_id ELSE NULL END,
                      identity_status, algorithm_version, created_at, updated_at
               FROM ranked"""
        )
        conn.execute("DROP TABLE asset_identity_map")
        conn.execute("ALTER TABLE asset_identity_map__v6 RENAME TO asset_identity_map")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_identity_revision ON asset_identity_map(slide_revision_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_identity_canonical ON asset_identity_map(canonical_asset_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_identity_status ON asset_identity_map(identity_status)")
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_identity_current_slide
           ON asset_identity_map(legacy_slide_id) WHERE legacy_slide_id IS NOT NULL"""
    )


def _backfill_current_identities(conn: sqlite3.Connection) -> None:
    now = datetime.now(UTC).isoformat()
    rows = conn.execute(
        """SELECT s.id
           FROM slides s
           LEFT JOIN asset_identity_map aim ON aim.legacy_slide_id = s.id
           WHERE aim.legacy_slide_id IS NULL
           ORDER BY s.id"""
    ).fetchall()
    for (slide_id_raw,) in rows:
        slide_id = int(slide_id_raw)
        canonical_id = f"asset_{uuid.uuid5(uuid.NAMESPACE_URL, f'slide:{slide_id}')}"
        conn.execute(
            """INSERT INTO asset_identity_map
               (canonical_asset_id, slide_revision_id, legacy_slide_id, identity_status,
                algorithm_version, created_at, updated_at)
               VALUES (?, ?, ?, 'legacy_unresolved', ?, ?, ?)""",
            (canonical_id, f"srev_legacy_{slide_id}", slide_id, FINGERPRINT_VERSION, now, now),
        )


def _backfill_canonical_asset_rows(conn: sqlite3.Connection) -> None:
    now = datetime.now(UTC).isoformat()
    rows = conn.execute(
        """SELECT aim.canonical_asset_id, aim.slide_revision_id,
                  COALESCE(s.text_hash, ''), s.screenshot_hash
           FROM asset_identity_map aim
           LEFT JOIN slides s ON s.id = aim.legacy_slide_id
           ORDER BY aim.canonical_asset_id, aim.slide_revision_id"""
    ).fetchall()
    for canonical_id, revision_id, text_hash, visual_hash in rows:
        upsert_slide_asset(conn, str(canonical_id), commit=False)
        insert_slide_revision(
            conn,
            SlideRevision(
                slide_revision_id=str(revision_id),
                canonical_asset_id=str(canonical_id),
                fingerprint=str(revision_id),
                algorithm_version=FINGERPRINT_VERSION,
                text_hash=str(text_hash or ""),
                visual_hash=str(visual_hash) if visual_hash else None,
                layout_hash=None,
                created_at=now,
            ),
            commit=False,
        )


def _create_slide_artifacts(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS [{name}] (
            id INTEGER PRIMARY KEY,
            slide_id INTEGER NOT NULL REFERENCES slides(id) ON DELETE CASCADE,
            workspace_profile_id INTEGER REFERENCES workspace_profiles(id) ON DELETE SET NULL,
            source_id INTEGER REFERENCES library_sources(id) ON DELETE SET NULL,
            asset_type TEXT NOT NULL,
            asset_uri TEXT NOT NULL,
            asset_hash TEXT,
            metadata_json TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(slide_id, asset_type, asset_uri)
        )"""
    )


def _create_table_from_template(conn: sqlite3.Connection, name: str, *, template: str) -> None:
    conn.execute(template.format(name=name))


def _rebuild_table(
    conn: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    create: Callable[[sqlite3.Connection, str], object],
) -> None:
    new_table = f"{table}__v6"
    conn.execute(f"DROP TABLE IF EXISTS [{new_table}]")
    create(conn, new_table)
    names = ", ".join(columns)
    conn.execute(f"INSERT INTO [{new_table}] ({names}) SELECT {names} FROM [{table}]")
    conn.execute(f"DROP TABLE [{table}]")
    conn.execute(f"ALTER TABLE [{new_table}] RENAME TO [{table}]")


def _schema_version(conn: sqlite3.Connection) -> int:
    if not _table_exists(conn, "_meta"):
        return 0
    row = conn.execute("SELECT value FROM _meta WHERE key = 'schema_version'").fetchone()
    return int(row[0]) if row else 0


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()[0] > 0
