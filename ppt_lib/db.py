from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import numpy as np

SCHEMA_VERSION = 4


class DatabaseError(RuntimeError):
    pass


SlideSource = Literal["vision_model", "text_extraction", "hybrid"]


@dataclass(frozen=True)
class PresentationRecord:
    path: Path
    filename: str
    project_name: str | None
    slide_count: int
    content_hash: str
    file_size: int
    file_mtime: float


@dataclass(frozen=True)
class SlideRecord:
    presentation_id: int
    slide_index: int
    title: str | None
    text_content: str
    embedding: np.ndarray | None
    screenshot_hash: str | None
    source: str
    extraction_warnings: list[str]
    metadata_json: dict[str, object]


@dataclass(frozen=True)
class ScreenshotRecord:
    hash: str
    file_path: Path
    width: int
    height: int


@dataclass(frozen=True)
class EmbeddingRow:
    slide_id: int
    presentation_id: int
    embedding: np.ndarray


@dataclass(frozen=True)
class IndexJobRecord:
    id: int
    file_path: Path
    status: str
    slide_index: int | None
    error_msg: str | None
    retry_count: int
    last_error_at: str | None
    updated_at: str | None


@dataclass(frozen=True)
class LibraryStats:
    presentation_count: int
    slide_count: int
    screenshot_count: int
    failed_job_count: int
    orphan_presentation_count: int


@dataclass(frozen=True)
class OrphanPresentationRecord:
    id: int
    path: Path
    filename: str
    project_name: str | None
    slide_count: int


@dataclass(frozen=True)
class LibrarySourceRecord:
    id: int
    name: str
    source_type: str | None
    is_active: bool


@dataclass(frozen=True)
class WorkspaceProfileRecord:
    id: int
    library_source_id: int | None
    name: str
    is_active: bool


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(
    conn: sqlite3.Connection,
    *,
    backups_dir: Path | None = None,
) -> None:
    """Initialize or migrate the database schema.

    Creates all tables (existing and new), checks schema version,
    and triggers migration if the database is from an older version.

    If *backups_dir* is provided, a pre-migration backup is created
    automatically before schema changes.
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS _meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS library_sources (
          id INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          source_type TEXT NOT NULL DEFAULT '',
          metadata_json TEXT,
          is_active INTEGER DEFAULT 1,
          created_at TEXT,
          updated_at TEXT,
          UNIQUE (name, source_type)
        );

        CREATE TABLE IF NOT EXISTS workspace_profiles (
          id INTEGER PRIMARY KEY,
          library_source_id INTEGER REFERENCES library_sources(id),
          name TEXT NOT NULL,
          metadata_json TEXT,
          is_active INTEGER DEFAULT 1,
          created_at TEXT,
          updated_at TEXT,
          UNIQUE (library_source_id, name)
        );

        CREATE TABLE IF NOT EXISTS presentations (
          id INTEGER PRIMARY KEY,
          path TEXT NOT NULL UNIQUE,
          filename TEXT NOT NULL,
          project_name TEXT,
          slide_count INTEGER,
          content_hash TEXT,
          file_size INTEGER,
          file_mtime REAL,
          indexed_at TEXT,
          last_validated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS slides (
          id INTEGER PRIMARY KEY,
          presentation_id INTEGER REFERENCES presentations(id),
          slide_index INTEGER NOT NULL,
          title TEXT,
          text_content TEXT,
          embedding BLOB,
          screenshot_hash TEXT,
          source TEXT NOT NULL CHECK(source IN ('vision_model','text_extraction','hybrid')),
          extraction_warnings TEXT,
          metadata_json TEXT,
          raw_text TEXT,
          ai_summary TEXT,
          visual_summary TEXT,
          summary_status TEXT,
          profile_id INTEGER REFERENCES workspace_profiles(id),
          text_hash TEXT,
          content_hash TEXT,
          canonical_slide_id INTEGER REFERENCES slides(id),
          industry TEXT,
          scenario TEXT,
          narrative_role TEXT,
          win_rate REAL,
          won_count INTEGER DEFAULT 0,
          lost_count INTEGER DEFAULT 0,
          reuse_count INTEGER DEFAULT 0,
          last_deal_outcome TEXT,
          quality_rating INTEGER,
          origin_type TEXT DEFAULT 'original'
            CHECK(origin_type IN ('original','assembled_output','imported')),
          UNIQUE(presentation_id, slide_index)
        );

        CREATE TABLE IF NOT EXISTS screenshots (
          hash TEXT PRIMARY KEY,
          file_path TEXT NOT NULL,
          width INTEGER,
          height INTEGER
        );

        CREATE TABLE IF NOT EXISTS index_jobs (
          id INTEGER PRIMARY KEY,
          file_path TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL CHECK(status IN ('pending','processing','completed','failed')),
          slide_index INTEGER,
          error_msg TEXT,
          retry_count INTEGER DEFAULT 0,
          last_error_at TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS deals (
          id INTEGER PRIMARY KEY,
          deal_name TEXT NOT NULL,
          client_type TEXT,
          deal_stage TEXT,
          outcome TEXT CHECK(outcome IN ('won','lost','pending','unknown')),
          created_at TEXT,
          closed_at TEXT,
          notes TEXT
        );

        CREATE TABLE IF NOT EXISTS assemble_runs (
          id INTEGER PRIMARY KEY,
          run_name TEXT NOT NULL,
          manifest_hash TEXT,
          output_presentation_id INTEGER REFERENCES presentations(id),
          slide_count INTEGER,
          created_at TEXT,
          status TEXT CHECK(status IN ('completed','completed_pending_ingest','failed','partial'))
        );

        CREATE TABLE IF NOT EXISTS slide_usage (
          id INTEGER PRIMARY KEY,
          slide_id INTEGER NOT NULL REFERENCES slides(id),
          deal_id INTEGER NOT NULL REFERENCES deals(id),
          assemble_run_id INTEGER REFERENCES assemble_runs(id),
          deck_presentation_id INTEGER NOT NULL REFERENCES presentations(id),
          position INTEGER,
          is_original INTEGER DEFAULT 1,
          used_at TEXT,
          UNIQUE(slide_id, deal_id, deck_presentation_id, position)
        );

        CREATE TABLE IF NOT EXISTS slide_lineage (
          id INTEGER PRIMARY KEY,
          derived_slide_id INTEGER NOT NULL REFERENCES slides(id),
          source_slide_id INTEGER NOT NULL REFERENCES slides(id),
          assemble_run_id INTEGER NOT NULL REFERENCES assemble_runs(id),
          derivation_type TEXT CHECK(derivation_type IN ('copied','modified')),
          created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS slide_assets (
          id INTEGER PRIMARY KEY,
          slide_id INTEGER NOT NULL REFERENCES slides(id),
          workspace_profile_id INTEGER REFERENCES workspace_profiles(id),
          source_id INTEGER REFERENCES library_sources(id),
          asset_type TEXT NOT NULL,
          asset_uri TEXT NOT NULL,
          asset_hash TEXT,
          metadata_json TEXT,
          created_at TEXT,
          updated_at TEXT,
          UNIQUE (slide_id, asset_type, asset_uri)
        );

        CREATE TABLE IF NOT EXISTS duplicate_groups (
          id INTEGER PRIMARY KEY,
          canonical_slide_id INTEGER NOT NULL REFERENCES slides(id),
          workspace_profile_id INTEGER REFERENCES workspace_profiles(id),
          created_at TEXT,
          updated_at TEXT,
          UNIQUE (canonical_slide_id)
        );

        CREATE TABLE IF NOT EXISTS slide_duplicate_members (
          id INTEGER PRIMARY KEY,
          duplicate_group_id INTEGER NOT NULL REFERENCES duplicate_groups(id),
          slide_id INTEGER NOT NULL REFERENCES slides(id),
          canonical_slide_id INTEGER REFERENCES slides(id),
          is_canonical INTEGER DEFAULT 0,
          created_at TEXT,
          UNIQUE (duplicate_group_id, slide_id)
        );

        CREATE TABLE IF NOT EXISTS deck_families (
          id INTEGER PRIMARY KEY,
          family_key TEXT NOT NULL UNIQUE,
          project_name TEXT,
          title TEXT,
          representative_presentation_id INTEGER REFERENCES presentations(id),
          presentation_count INTEGER DEFAULT 0,
          created_at TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS presentation_versions (
          id INTEGER PRIMARY KEY,
          presentation_id INTEGER NOT NULL UNIQUE REFERENCES presentations(id),
          deck_family_id INTEGER NOT NULL REFERENCES deck_families(id),
          version_key TEXT,
          version_role TEXT,
          version_rank INTEGER DEFAULT 0,
          version_date TEXT,
          is_representative INTEGER DEFAULT 0,
          confidence REAL,
          signals_json TEXT,
          created_at TEXT,
          updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS deck_insights (
          id INTEGER PRIMARY KEY,
          presentation_id INTEGER NOT NULL UNIQUE REFERENCES presentations(id),
          status TEXT NOT NULL,
          summary_json TEXT,
          warnings_json TEXT,
          generated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS slide_importance (
          id INTEGER PRIMARY KEY,
          slide_id INTEGER NOT NULL UNIQUE REFERENCES slides(id),
          importance_score REAL,
          importance_reason TEXT,
          page_role TEXT,
          needs_visual INTEGER DEFAULT 0,
          status TEXT,
          updated_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_presentations_path ON presentations(path);
        CREATE INDEX IF NOT EXISTS idx_slides_presentation ON slides(presentation_id);
        CREATE INDEX IF NOT EXISTS idx_slides_screenshot_hash ON slides(screenshot_hash);
        CREATE INDEX IF NOT EXISTS idx_index_jobs_file_status ON index_jobs(file_path, status);
        CREATE INDEX IF NOT EXISTS idx_slide_assets_slide_id ON slide_assets(slide_id);
        CREATE INDEX IF NOT EXISTS idx_slide_assets_profile_id ON slide_assets(workspace_profile_id);
        CREATE INDEX IF NOT EXISTS idx_duplicate_groups_canonical ON duplicate_groups(canonical_slide_id);
        CREATE INDEX IF NOT EXISTS idx_slide_duplicate_members_group ON slide_duplicate_members(duplicate_group_id);
        CREATE INDEX IF NOT EXISTS idx_slide_duplicate_members_slide ON slide_duplicate_members(slide_id);
        CREATE INDEX IF NOT EXISTS idx_presentation_versions_family ON presentation_versions(deck_family_id);
        CREATE INDEX IF NOT EXISTS idx_presentation_versions_representative ON presentation_versions(is_representative);
        CREATE INDEX IF NOT EXISTS idx_deck_families_representative ON deck_families(representative_presentation_id);
        CREATE INDEX IF NOT EXISTS idx_deck_insights_presentation ON deck_insights(presentation_id);
        CREATE INDEX IF NOT EXISTS idx_slide_importance_slide ON slide_importance(slide_id);
        """
    )
    _ensure_schema_version(conn, backups_dir=backups_dir)
    _ensure_extended_indexes(conn)
    conn.commit()


def backup_db(conn: sqlite3.Connection, backups_dir: Path) -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backups_dir / f"index-{_now_compact()}.db"
    try:
        target = sqlite3.connect(backup_path)
        with target:
            conn.backup(target)
    except sqlite3.Error as exc:
        if backup_path.exists():
            backup_path.unlink()
        raise DatabaseError(f"Failed to back up database: {exc}") from exc
    finally:
        try:
            target.close()
        except UnboundLocalError:
            pass
    return backup_path


def upsert_presentation(conn: sqlite3.Connection, record: PresentationRecord, *, commit: bool = True) -> int:
    now = _now_iso()
    try:
        conn.execute(
            """
            INSERT INTO presentations (
                path, filename, project_name, slide_count, content_hash,
                file_size, file_mtime, indexed_at, last_validated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                filename=excluded.filename,
                project_name=excluded.project_name,
                slide_count=excluded.slide_count,
                content_hash=excluded.content_hash,
                file_size=excluded.file_size,
                file_mtime=excluded.file_mtime,
                indexed_at=excluded.indexed_at,
                last_validated_at=excluded.last_validated_at
            """,
            (
                str(record.path),
                record.filename,
                record.project_name,
                record.slide_count,
                record.content_hash,
                record.file_size,
                record.file_mtime,
                now,
                now,
            ),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to upsert presentation: {exc}") from exc
    row = conn.execute("SELECT id FROM presentations WHERE path = ?", (str(record.path),)).fetchone()
    return int(row[0])


def upsert_slide(conn: sqlite3.Connection, record: SlideRecord, *, commit: bool = True) -> int:
    _validate_source(record.source)
    embedding_blob = _serialize_embedding(record.embedding)
    try:
        conn.execute(
            """
            INSERT INTO slides (
                presentation_id, slide_index, title, text_content, embedding,
                screenshot_hash, source, extraction_warnings, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(presentation_id, slide_index) DO UPDATE SET
                title=excluded.title,
                text_content=excluded.text_content,
                embedding=excluded.embedding,
                screenshot_hash=excluded.screenshot_hash,
                source=excluded.source,
                extraction_warnings=excluded.extraction_warnings,
                metadata_json=excluded.metadata_json
            """,
            (
                record.presentation_id,
                record.slide_index,
                record.title,
                record.text_content,
                embedding_blob,
                record.screenshot_hash,
                record.source,
                json.dumps(record.extraction_warnings, ensure_ascii=False),
                json.dumps(record.metadata_json, ensure_ascii=False),
            ),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to upsert slide: {exc}") from exc
    row = conn.execute(
        "SELECT id FROM slides WHERE presentation_id = ? AND slide_index = ?",
        (record.presentation_id, record.slide_index),
    ).fetchone()
    return int(row[0])


def upsert_library_source(
    conn: sqlite3.Connection,
    name: str,
    *,
    source_type: str | None = None,
    metadata_json: dict[str, object] | None = None,
    is_active: bool = True,
    commit: bool = True,
) -> int:
    now = _now_iso()
    source_type_key = source_type or ""
    try:
        conn.execute(
            """
            INSERT INTO library_sources (
                name, source_type, metadata_json, is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(name, source_type) DO UPDATE SET
                source_type=excluded.source_type,
                metadata_json=excluded.metadata_json,
                is_active=excluded.is_active,
                updated_at=excluded.updated_at
            """,
            (
                name,
                source_type_key,
                json.dumps(metadata_json or {}, ensure_ascii=False),
                int(is_active),
                now,
                now,
            ),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to upsert library source: {exc}") from exc
    row = conn.execute(
        "SELECT id FROM library_sources WHERE name = ? AND source_type = ?",
        (name, source_type_key),
    ).fetchone()
    return int(row[0])


def list_library_sources(conn: sqlite3.Connection) -> list[LibrarySourceRecord]:
    rows = conn.execute(
        "SELECT id, name, source_type, is_active FROM library_sources ORDER BY name"
    ).fetchall()
    return [
        LibrarySourceRecord(
            id=int(row[0]),
            name=row[1],
            source_type=row[2],
            is_active=bool(row[3]),
        )
        for row in rows
    ]


def create_workspace_profile(
    conn: sqlite3.Connection,
    *,
    library_source_id: int | None,
    name: str,
    metadata_json: dict[str, object] | None = None,
    is_active: bool = True,
    commit: bool = True,
) -> int:
    now = _now_iso()
    try:
        if is_active and library_source_id is not None:
            conn.execute(
                "UPDATE workspace_profiles SET is_active = 0 WHERE library_source_id = ?",
                (library_source_id,),
            )
        conn.execute(
            """
            INSERT INTO workspace_profiles (
                library_source_id, name, metadata_json, is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(library_source_id, name) DO UPDATE SET
                metadata_json=excluded.metadata_json,
                is_active=excluded.is_active,
                updated_at=excluded.updated_at
            """,
            (
                library_source_id,
                name,
                json.dumps(metadata_json or {}, ensure_ascii=False),
                int(is_active),
                now,
                now,
            ),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to create workspace profile: {exc}") from exc
    row = conn.execute(
        "SELECT id FROM workspace_profiles WHERE library_source_id = ? AND name = ?",
        (library_source_id, name),
    ).fetchone()
    return int(row[0])


def get_active_workspace_profile(
    conn: sqlite3.Connection,
    *,
    library_source_id: int | None = None,
) -> WorkspaceProfileRecord | None:
    if library_source_id is None:
        row = conn.execute(
            "SELECT id, library_source_id, name, is_active "
            "FROM workspace_profiles WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT id, library_source_id, name, is_active
            FROM workspace_profiles
            WHERE library_source_id = ? AND is_active = 1
            ORDER BY id DESC
            LIMIT 1
            """,
            (library_source_id,),
        ).fetchone()
    if row is None:
        return None
    return WorkspaceProfileRecord(
        id=int(row[0]),
        library_source_id=row[1],
        name=row[2],
        is_active=bool(row[3]),
    )


def update_slide_summary_fields(
    conn: sqlite3.Connection,
    slide_id: int,
    *,
    raw_text: str | None = None,
    ai_summary: str | None = None,
    visual_summary: str | None = None,
    summary_status: str | None = None,
    profile_id: int | None = None,
    text_hash: str | None = None,
    content_hash: str | None = None,
    commit: bool = True,
) -> None:
    try:
        conn.execute(
            """
            UPDATE slides
            SET raw_text = ?,
                ai_summary = ?,
                visual_summary = ?,
                summary_status = ?,
                profile_id = ?,
                text_hash = ?,
                content_hash = ?
            WHERE id = ?
            """,
            (raw_text, ai_summary, visual_summary, summary_status, profile_id, text_hash, content_hash, slide_id),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to update slide summary fields: {exc}") from exc


def upsert_slide_asset(
    conn: sqlite3.Connection,
    *,
    slide_id: int,
    asset_type: str,
    asset_uri: str,
    workspace_profile_id: int | None = None,
    source_id: int | None = None,
    asset_hash: str | None = None,
    metadata_json: dict[str, object] | None = None,
    commit: bool = True,
) -> int:
    now = _now_iso()
    try:
        conn.execute(
            """
            INSERT INTO slide_assets (
                slide_id, workspace_profile_id, source_id, asset_type, asset_uri,
                asset_hash, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slide_id, asset_type, asset_uri) DO UPDATE SET
                workspace_profile_id=excluded.workspace_profile_id,
                source_id=excluded.source_id,
                asset_hash=excluded.asset_hash,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at
            """,
            (
                slide_id,
                workspace_profile_id,
                source_id,
                asset_type,
                asset_uri,
                asset_hash,
                json.dumps(metadata_json or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to upsert slide asset: {exc}") from exc
    row = conn.execute(
        """
        SELECT id FROM slide_assets
        WHERE slide_id = ? AND asset_type = ? AND asset_uri = ?
        """,
        (slide_id, asset_type, asset_uri),
    ).fetchone()
    return int(row[0])


def upsert_duplicate_group(
    conn: sqlite3.Connection,
    *,
    canonical_slide_id: int,
    workspace_profile_id: int | None = None,
    commit: bool = True,
) -> int:
    now = _now_iso()
    try:
        conn.execute(
            """
            INSERT INTO duplicate_groups (
                canonical_slide_id, workspace_profile_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(canonical_slide_id) DO UPDATE SET
                workspace_profile_id=excluded.workspace_profile_id,
                updated_at=excluded.updated_at
            """,
            (canonical_slide_id, workspace_profile_id, now, now),
        )
        conn.execute(
            "UPDATE slides SET canonical_slide_id = id WHERE id = ?",
            (canonical_slide_id,),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to upsert duplicate group: {exc}") from exc
    row = conn.execute(
        "SELECT id FROM duplicate_groups WHERE canonical_slide_id = ?",
        (canonical_slide_id,),
    ).fetchone()
    if row is None:
        raise DatabaseError(
            "Failed to locate duplicate group after upsert. "
            "Schema or upsert condition may have drifted."
        )
    return int(row[0])


def upsert_duplicate_member(
    conn: sqlite3.Connection,
    *,
    duplicate_group_id: int,
    slide_id: int,
    is_canonical: bool = False,
    commit: bool = True,
) -> int:
    now = _now_iso()
    row = conn.execute(
        "SELECT canonical_slide_id FROM duplicate_groups WHERE id = ?",
        (duplicate_group_id,),
    ).fetchone()
    if row is None:
        raise DatabaseError(f"Duplicate group {duplicate_group_id} does not exist")
    previous_canonical_slide_id = int(row[0])
    canonical_slide_id = previous_canonical_slide_id
    if is_canonical:
        canonical_slide_id = slide_id

    try:
        if is_canonical:
            conn.execute(
                "UPDATE duplicate_groups SET canonical_slide_id = ?, updated_at = ? WHERE id = ?",
                (canonical_slide_id, now, duplicate_group_id),
            )
            conn.execute(
                """
                UPDATE slide_duplicate_members
                SET canonical_slide_id = ?, is_canonical = 0
                WHERE duplicate_group_id = ?
                """,
                (canonical_slide_id, duplicate_group_id),
            )
        conn.execute(
            """
            INSERT INTO slide_duplicate_members (
                duplicate_group_id, slide_id, canonical_slide_id, is_canonical, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(duplicate_group_id, slide_id) DO UPDATE SET
                canonical_slide_id=excluded.canonical_slide_id,
                is_canonical=excluded.is_canonical
            """,
            (
                duplicate_group_id,
                slide_id,
                canonical_slide_id,
                int(is_canonical),
                now,
            ),
        )
        conn.execute(
            """
            UPDATE slides
            SET canonical_slide_id = ?
            WHERE id = ?
               OR id = ?
               OR id IN (
                   SELECT slide_id
                   FROM slide_duplicate_members
                   WHERE duplicate_group_id = ?
               )
            """,
            (canonical_slide_id, slide_id, previous_canonical_slide_id, duplicate_group_id),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to upsert duplicate member: {exc}") from exc
    row = conn.execute(
        "SELECT id FROM slide_duplicate_members WHERE duplicate_group_id = ? AND slide_id = ?",
        (duplicate_group_id, slide_id),
    ).fetchone()
    return int(row[0])


def insert_screenshot(conn: sqlite3.Connection, record: ScreenshotRecord, *, commit: bool = True) -> None:
    try:
        conn.execute(
            """
            INSERT INTO screenshots (hash, file_path, width, height)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(hash) DO NOTHING
            """,
            (record.hash, str(record.file_path), record.width, record.height),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to insert screenshot: {exc}") from exc


def get_all_embeddings(conn: sqlite3.Connection) -> list[EmbeddingRow]:
    rows = conn.execute(
        "SELECT id, presentation_id, embedding FROM slides WHERE embedding IS NOT NULL"
    ).fetchall()
    return [
        EmbeddingRow(
            slide_id=int(row[0]),
            presentation_id=int(row[1]),
            embedding=np.frombuffer(row[2], dtype=np.float32).copy(),
        )
        for row in rows
    ]


def get_stats(conn: sqlite3.Connection) -> LibraryStats:
    presentation_count = _count(conn, "presentations")
    slide_count = _count(conn, "slides")
    screenshot_count = _count(conn, "screenshots")
    failed_job_count = conn.execute(
        "SELECT COUNT(*) FROM index_jobs WHERE status = 'failed'"
    ).fetchone()[0]
    paths = [Path(row[0]) for row in conn.execute("SELECT path FROM presentations").fetchall()]
    orphan_count = sum(1 for path in paths if not path.exists())
    return LibraryStats(
        presentation_count=presentation_count,
        slide_count=slide_count,
        screenshot_count=screenshot_count,
        failed_job_count=int(failed_job_count),
        orphan_presentation_count=orphan_count,
    )


def create_or_update_job(
    conn: sqlite3.Connection,
    file_path: Path,
    status: str,
    *,
    commit: bool = True,
    **fields: object,
) -> int:
    _validate_job_status(status)
    now = _now_iso()
    slide_index = fields.get("slide_index")
    error_msg = fields.get("error_msg")
    last_error_at = now if status == "failed" and error_msg else fields.get("last_error_at")
    retry_count = int(cast(int | str, fields.get("retry_count", 0)))
    if status == "failed":
        existing = conn.execute(
            "SELECT retry_count FROM index_jobs WHERE file_path = ?",
            (str(file_path),),
        ).fetchone()
        retry_count = (int(existing[0]) + 1) if existing else 1
    try:
        conn.execute(
            """
            INSERT INTO index_jobs (
                file_path, status, slide_index, error_msg, retry_count,
                last_error_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                status=excluded.status,
                slide_index=excluded.slide_index,
                error_msg=excluded.error_msg,
                retry_count=excluded.retry_count,
                last_error_at=excluded.last_error_at,
                updated_at=excluded.updated_at
            """,
            (str(file_path), status, slide_index, error_msg, retry_count, last_error_at, now),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to update index job: {exc}") from exc
    row = conn.execute(
        "SELECT id FROM index_jobs WHERE file_path = ?",
        (str(file_path),),
    ).fetchone()
    return int(row[0])


def mark_job_completed(conn: sqlite3.Connection, job_id: int, *, commit: bool = True) -> None:
    conn.execute(
        """
        UPDATE index_jobs
        SET status = 'completed', error_msg = NULL, slide_index = NULL, updated_at = ?
        WHERE id = ?
        """,
        (_now_iso(), job_id),
    )
    if commit:
        conn.commit()


def mark_job_failed(conn: sqlite3.Connection, job_id: int, error_msg: str, *, commit: bool = True) -> None:
    conn.execute(
        """
        UPDATE index_jobs
        SET status = 'failed',
            error_msg = ?,
            retry_count = retry_count + 1,
            last_error_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (error_msg, _now_iso(), _now_iso(), job_id),
    )
    if commit:
        conn.commit()


def delete_slides_for_presentations(conn: sqlite3.Connection, presentation_ids: list[int], *, commit: bool = True) -> int:
    deleted = 0
    for chunk in _chunks(presentation_ids):
        placeholders = ",".join("?" for _ in chunk)
        cursor = conn.execute(f"DELETE FROM slides WHERE presentation_id IN ({placeholders})", chunk)
        deleted += int(cursor.rowcount if cursor.rowcount != -1 else 0)
    if commit:
        conn.commit()
    return deleted


def delete_presentations(conn: sqlite3.Connection, presentation_ids: list[int], *, commit: bool = True) -> int:
    deleted = 0
    for chunk in _chunks(presentation_ids):
        placeholders = ",".join("?" for _ in chunk)
        cursor = conn.execute(f"DELETE FROM presentations WHERE id IN ({placeholders})", chunk)
        deleted += int(cursor.rowcount if cursor.rowcount != -1 else 0)
    if commit:
        conn.commit()
    return deleted


def list_missing_job_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT id, file_path FROM index_jobs").fetchall()
    return [int(row[0]) for row in rows if not Path(row[1]).exists()]


def delete_jobs(conn: sqlite3.Connection, job_ids: list[int], *, commit: bool = True) -> int:
    deleted = 0
    for chunk in _chunks(job_ids):
        placeholders = ",".join("?" for _ in chunk)
        cursor = conn.execute(f"DELETE FROM index_jobs WHERE id IN ({placeholders})", chunk)
        deleted += int(cursor.rowcount if cursor.rowcount != -1 else 0)
    if commit:
        conn.commit()
    return deleted


def list_unreferenced_screenshots(conn: sqlite3.Connection) -> list[ScreenshotRecord]:
    rows = conn.execute(
        """
        SELECT sc.hash, sc.file_path, sc.width, sc.height
        FROM screenshots sc
        LEFT JOIN slides s ON s.screenshot_hash = sc.hash
        WHERE s.id IS NULL
        ORDER BY sc.hash
        """
    ).fetchall()
    return [
        ScreenshotRecord(
            hash=row[0],
            file_path=Path(row[1]),
            width=int(row[2] or 0),
            height=int(row[3] or 0),
        )
        for row in rows
    ]


def delete_screenshots(conn: sqlite3.Connection, hashes: list[str], *, commit: bool = True) -> int:
    deleted = 0
    for chunk in _chunks(hashes):
        placeholders = ",".join("?" for _ in chunk)
        cursor = conn.execute(f"DELETE FROM screenshots WHERE hash IN ({placeholders})", chunk)
        deleted += int(cursor.rowcount if cursor.rowcount != -1 else 0)
    if commit:
        conn.commit()
    return deleted


def replace_presentation_slides(
    conn: sqlite3.Connection,
    presentation_id: int,
    slides: list[SlideRecord],
    *,
    commit: bool = True,
) -> None:
    """Replace all slides for a presentation, preserving IDs of existing slides.

    Uses the ``UNIQUE(presentation_id, slide_index)`` constraint:
    existing slides are UPDATE'd in place (preserving their id),
    genuinely new slides are INSERT'd, and slides whose slide_index
    no longer appears are DELETE'd.
    """
    try:
        incoming_indices = {s.slide_index for s in slides}

        for slide in slides:
            upsert_slide(conn, slide, commit=False)

        if incoming_indices:
            placeholders = ",".join("?" for _ in incoming_indices)
            conn.execute(
                f"DELETE FROM slides WHERE presentation_id = ? AND slide_index NOT IN ({placeholders})",
                [presentation_id] + list(incoming_indices),
            )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to replace slides: {exc}") from exc


def list_orphan_presentations(conn: sqlite3.Connection) -> list[OrphanPresentationRecord]:
    rows = conn.execute(
        """
        SELECT id, path, filename, project_name, slide_count
        FROM presentations
        ORDER BY path
        """
    ).fetchall()
    return [
        OrphanPresentationRecord(
            id=int(row[0]),
            path=Path(row[1]),
            filename=row[2],
            project_name=row[3],
            slide_count=int(row[4] or 0),
        )
        for row in rows
        if not Path(row[1]).exists()
    ]


def list_failed_jobs(conn: sqlite3.Connection) -> list[IndexJobRecord]:
    rows = conn.execute(
        """
        SELECT id, file_path, status, slide_index, error_msg, retry_count, last_error_at, updated_at
        FROM index_jobs
        WHERE status = 'failed'
        ORDER BY updated_at DESC
        """
    ).fetchall()
    return [_job_from_row(row) for row in rows]


# ── Schema version & migration ──────────────────────────────────────────────


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version from _meta, or 1 if not found."""
    row = conn.execute(
        "SELECT value FROM _meta WHERE key = 'schema_version'"
    ).fetchone()
    return int(row[0]) if row else 1


def _ensure_schema_version(
    conn: sqlite3.Connection,
    *,
    backups_dir: Path | None = None,
) -> None:
    """Check schema version and trigger migration if needed."""
    current = get_schema_version(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(slides)").fetchall()}
    has_v2_slide_columns = {"industry", "scenario", "origin_type"} <= cols
    has_v3_slide_columns = {"raw_text", "ai_summary", "visual_summary", "canonical_slide_id"} <= cols
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    has_v3_tables = {"library_sources", "workspace_profiles", "slide_assets", "duplicate_groups", "slide_duplicate_members"} <= tables
    has_v4_tables = {"deck_families", "presentation_versions", "deck_insights", "slide_importance"} <= tables
    needs_v2_migration = current < 2 or not has_v2_slide_columns
    needs_v3_migration = current < 3 or not has_v3_slide_columns or not has_v3_tables
    needs_v4_migration = current < 4 or not has_v4_tables

    if needs_v2_migration:
        _migrate_v1_to_v2(conn, backups_dir=backups_dir)
    if needs_v3_migration:
        _migrate_v2_to_v3(conn, backups_dir=backups_dir)
    if needs_v4_migration:
        _migrate_v3_to_v4(conn, backups_dir=backups_dir)

    conn.execute(
        "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


def _migrate_v3_to_v4(
    conn: sqlite3.Connection,
    *,
    backups_dir: Path | None = None,
) -> None:
    """Migrate schema from v3 to v4.

    Adds deck family, presentation version, deck insight, and slide
    importance tables. Existing presentations, slides, screenshots, and
    embeddings are left untouched.
    """
    if backups_dir:
        try:
            backup_db(conn, backups_dir)
        except DatabaseError as exc:
            raise DatabaseError(
                "Migration v3→v4 aborted: pre-migration backup failed. "
                f"Manual recovery may be needed. Error: {exc}"
            ) from exc

    try:
        conn.execute("BEGIN")
        _create_deck_intelligence_tables(conn)
        _create_deck_intelligence_indexes(conn)
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise DatabaseError(
            f"Migration v3→v4 failed (transaction rolled back): {exc}"
        ) from exc


def _migrate_v1_to_v2(
    conn: sqlite3.Connection,
    *,
    backups_dir: Path | None = None,
) -> None:
    """Migrate schema from v1 to v2.

    Adds 10 new columns to the *slides* table and 4 new tables for deal
    tracking, assembly lineage, and slide usage.

    The migration runs inside a transaction.  Before any changes it
    optionally creates a backup via *backups_dir*.
    """
    if backups_dir:
        try:
            backup_db(conn, backups_dir)
        except DatabaseError as exc:
            raise DatabaseError(
                "Migration v1→v2 aborted: pre-migration backup failed. "
                f"Manual recovery may be needed. Error: {exc}"
            ) from exc

    new_slides_columns: list[tuple[str, str]] = [
        ("industry", "TEXT"),
        ("scenario", "TEXT"),
        ("narrative_role", "TEXT"),
        ("win_rate", "REAL"),
        ("won_count", "INTEGER DEFAULT 0"),
        ("lost_count", "INTEGER DEFAULT 0"),
        ("reuse_count", "INTEGER DEFAULT 0"),
        ("last_deal_outcome", "TEXT"),
        ("quality_rating", "INTEGER"),
        (
            "origin_type",
            "TEXT DEFAULT 'original' "
            "CHECK(origin_type IN ('original','assembled_output','imported'))",
        ),
    ]

    new_indexes: list[str] = [
        "CREATE INDEX IF NOT EXISTS idx_slides_origin_type ON slides(origin_type);",
        "CREATE INDEX IF NOT EXISTS idx_slides_narrative_role ON slides(narrative_role);",
        "CREATE INDEX IF NOT EXISTS idx_slides_industry ON slides(industry);",
    ]

    try:
        conn.execute("BEGIN")
        existing_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(slides)").fetchall()
        }

        for col_name, col_type in new_slides_columns:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE slides ADD COLUMN {col_name} {col_type}")

        _create_new_tables(conn)
        for index_sql in new_indexes:
            conn.execute(index_sql)

        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise DatabaseError(
            f"Migration v1→v2 failed (transaction rolled back): {exc}"
        ) from exc


def _migrate_v2_to_v3(
    conn: sqlite3.Connection,
    *,
    backups_dir: Path | None = None,
) -> None:
    """Migrate schema from v2 to v3.

    Adds new asset/profile/duplicate tables and slide summary columns.
    The migration runs inside a transaction and restores backup when configured.
    """
    if backups_dir:
        try:
            backup_db(conn, backups_dir)
        except DatabaseError as exc:
            raise DatabaseError(
                "Migration v2→v3 aborted: pre-migration backup failed. "
                f"Manual recovery may be needed. Error: {exc}"
            ) from exc

    new_slides_columns: list[tuple[str, str]] = [
        ("raw_text", "TEXT"),
        ("ai_summary", "TEXT"),
        ("visual_summary", "TEXT"),
        ("summary_status", "TEXT"),
        ("profile_id", "INTEGER REFERENCES workspace_profiles(id)"),
        ("text_hash", "TEXT"),
        ("content_hash", "TEXT"),
        ("canonical_slide_id", "INTEGER REFERENCES slides(id)"),
    ]
    new_indexes: list[str] = [
        "CREATE INDEX IF NOT EXISTS idx_library_sources_name ON library_sources(name);",
        "CREATE INDEX IF NOT EXISTS idx_library_sources_active ON library_sources(is_active);",
        "CREATE INDEX IF NOT EXISTS idx_workspace_profiles_source ON workspace_profiles(library_source_id);",
        "CREATE INDEX IF NOT EXISTS idx_workspace_profiles_active ON workspace_profiles(is_active);",
        "CREATE INDEX IF NOT EXISTS idx_slides_profile_id ON slides(profile_id);",
        "CREATE INDEX IF NOT EXISTS idx_slides_canonical_slide_id ON slides(canonical_slide_id);",
        "CREATE INDEX IF NOT EXISTS idx_slide_assets_slide_id ON slide_assets(slide_id);",
        "CREATE INDEX IF NOT EXISTS idx_slide_assets_profile_id ON slide_assets(workspace_profile_id);",
        "CREATE INDEX IF NOT EXISTS idx_duplicate_groups_canonical ON duplicate_groups(canonical_slide_id);",
        "CREATE INDEX IF NOT EXISTS idx_slide_duplicate_members_group ON slide_duplicate_members(duplicate_group_id);",
        "CREATE INDEX IF NOT EXISTS idx_slide_duplicate_members_slide ON slide_duplicate_members(slide_id);",
    ]

    try:
        conn.execute("BEGIN")
        existing_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(slides)").fetchall()
        }
        for col_name, col_type in new_slides_columns:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE slides ADD COLUMN {col_name} {col_type}")

        _create_full_asset_tables(conn)
        for index_sql in new_indexes:
            conn.execute(index_sql)

        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise DatabaseError(
            f"Migration v2→v3 failed (transaction rolled back): {exc}"
        ) from exc


# ── Recompute cache fields ──────────────────────────────────────────────────


def recompute_slide_stats(
    conn: sqlite3.Connection,
    slide_id: int | None = None,
    *,
    commit: bool = True,
) -> dict[str, int]:
    """Recompute cache fields from fact sources (slide_usage + deals).

    Refreshes win_rate, won_count, lost_count, reuse_count, and
    last_deal_outcome on the *slides* table.

    When *slide_id* is None, recompute for all slides.
    Returns ``{"updated": <int>}``.
    """
    if slide_id is not None:
        slide_ids = [slide_id]
    else:
        rows = conn.execute("SELECT id FROM slides").fetchall()
        slide_ids = [int(row[0]) for row in rows]

    updated = 0
    for sid in slide_ids:
        outcome_counts: dict[str, int] = {}
        usage_rows = conn.execute(
            """
            SELECT d.outcome, COUNT(*) as cnt
            FROM slide_usage su
            JOIN deals d ON d.id = su.deal_id
            WHERE su.slide_id = ?
            GROUP BY d.outcome
            """,
            (sid,),
        ).fetchall()
        for outcome, cnt in usage_rows:
            outcome_counts[str(outcome)] = int(cnt)

        won = outcome_counts.get("won", 0)
        lost = outcome_counts.get("lost", 0)
        total = sum(outcome_counts.values())

        last_row = conn.execute(
            """
            SELECT d.outcome
            FROM slide_usage su
            JOIN deals d ON d.id = su.deal_id
            WHERE su.slide_id = ? AND d.outcome IN ('won', 'lost')
            ORDER BY su.used_at DESC
            LIMIT 1
            """,
            (sid,),
        ).fetchone()
        last_deal_outcome: str | None = last_row[0] if last_row else None
        win_rate = round(won / (won + lost), 4) if (won + lost) > 0 else None

        conn.execute(
            """
            UPDATE slides SET
                win_rate = ?,
                won_count = ?,
                lost_count = ?,
                reuse_count = ?,
                last_deal_outcome = ?
            WHERE id = ?
            """,
            (win_rate, won, lost, total, last_deal_outcome, sid),
        )
        updated += 1

    if commit:
        conn.commit()
    return {"updated": updated}


# ── Deal CRUD helpers ──────────────────────────────────────────────────────


def insert_deal(
    conn: sqlite3.Connection,
    deal_name: str,
    *,
    client_type: str | None = None,
    deal_stage: str | None = None,
    outcome: str = "unknown",
    notes: str | None = None,
    commit: bool = True,
) -> int:
    """Insert a new deal and return its id."""
    now = _now_iso()
    try:
        conn.execute(
            """
            INSERT INTO deals (deal_name, client_type, deal_stage, outcome, created_at, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (deal_name, client_type, deal_stage, outcome, now, notes),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to insert deal: {exc}") from exc
    return int(
        conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    )


def record_slide_usage(
    conn: sqlite3.Connection,
    *,
    slide_id: int,
    deal_id: int,
    deck_presentation_id: int,
    position: int | None = None,
    assemble_run_id: int | None = None,
    is_original: bool = True,
    commit: bool = True,
) -> int:
    """Record that a slide was used in a deal/deck and return usage id.

    Triggers a recompute of the affected slide's cache fields.
    """
    now = _now_iso()
    usage_position = 0 if position is None else position
    try:
        conn.execute(
            """
            INSERT INTO slide_usage
                (slide_id, deal_id, assemble_run_id, deck_presentation_id,
                 position, is_original, used_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slide_id, deal_id, deck_presentation_id, position)
            DO NOTHING
            """,
            (slide_id, deal_id, assemble_run_id, deck_presentation_id, usage_position, int(is_original), now),
        )
        if commit:
            conn.commit()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Failed to record slide usage: {exc}") from exc

    row_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    recompute_slide_stats(conn, slide_id=slide_id, commit=commit)
    return row_id


def _ensure_extended_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes for the new Phase-0 columns (post-migration safe)."""
    for index_sql in [
        "CREATE INDEX IF NOT EXISTS idx_slides_origin_type ON slides(origin_type)",
        "CREATE INDEX IF NOT EXISTS idx_slides_narrative_role ON slides(narrative_role)",
        "CREATE INDEX IF NOT EXISTS idx_slides_industry ON slides(industry)",
        "CREATE INDEX IF NOT EXISTS idx_library_sources_name ON library_sources(name)",
        "CREATE INDEX IF NOT EXISTS idx_library_sources_active ON library_sources(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_workspace_profiles_source ON workspace_profiles(library_source_id)",
        "CREATE INDEX IF NOT EXISTS idx_workspace_profiles_active ON workspace_profiles(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_slides_profile_id ON slides(profile_id)",
        "CREATE INDEX IF NOT EXISTS idx_slides_canonical_slide_id ON slides(canonical_slide_id)",
        "CREATE INDEX IF NOT EXISTS idx_slide_assets_slide_id ON slide_assets(slide_id)",
        "CREATE INDEX IF NOT EXISTS idx_slide_assets_profile_id ON slide_assets(workspace_profile_id)",
        "CREATE INDEX IF NOT EXISTS idx_duplicate_groups_canonical ON duplicate_groups(canonical_slide_id)",
        "CREATE INDEX IF NOT EXISTS idx_slide_duplicate_members_group ON slide_duplicate_members(duplicate_group_id)",
        "CREATE INDEX IF NOT EXISTS idx_slide_duplicate_members_slide ON slide_duplicate_members(slide_id)",
        "CREATE INDEX IF NOT EXISTS idx_presentation_versions_family ON presentation_versions(deck_family_id)",
        "CREATE INDEX IF NOT EXISTS idx_presentation_versions_representative ON presentation_versions(is_representative)",
        "CREATE INDEX IF NOT EXISTS idx_deck_families_representative ON deck_families(representative_presentation_id)",
        "CREATE INDEX IF NOT EXISTS idx_deck_insights_presentation ON deck_insights(presentation_id)",
        "CREATE INDEX IF NOT EXISTS idx_slide_importance_slide ON slide_importance(slide_id)",
    ]:
        try:
            conn.execute(index_sql)
        except sqlite3.OperationalError:
            pass


def _create_new_tables(conn: sqlite3.Connection) -> None:
    """Create the 4 Phase-0 tables inside an existing transaction."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS deals ("
        "  id INTEGER PRIMARY KEY,"
        "  deal_name TEXT NOT NULL,"
        "  client_type TEXT,"
        "  deal_stage TEXT,"
        "  outcome TEXT CHECK(outcome IN ('won','lost','pending','unknown')),"
        "  created_at TEXT,"
        "  closed_at TEXT,"
        "  notes TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS assemble_runs ("
        "  id INTEGER PRIMARY KEY,"
        "  run_name TEXT NOT NULL,"
        "  manifest_hash TEXT,"
        "  output_presentation_id INTEGER REFERENCES presentations(id),"
        "  slide_count INTEGER,"
        "  created_at TEXT,"
        "  status TEXT CHECK(status IN ('completed','completed_pending_ingest','failed','partial'))"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS slide_usage ("
        "  id INTEGER PRIMARY KEY,"
        "  slide_id INTEGER NOT NULL REFERENCES slides(id),"
        "  deal_id INTEGER NOT NULL REFERENCES deals(id),"
        "  assemble_run_id INTEGER REFERENCES assemble_runs(id),"
        "  deck_presentation_id INTEGER NOT NULL REFERENCES presentations(id),"
        "  position INTEGER,"
        "  is_original INTEGER DEFAULT 1,"
        "  used_at TEXT,"
        "  UNIQUE(slide_id, deal_id, deck_presentation_id, position)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS slide_lineage ("
        "  id INTEGER PRIMARY KEY,"
        "  derived_slide_id INTEGER NOT NULL REFERENCES slides(id),"
        "  source_slide_id INTEGER NOT NULL REFERENCES slides(id),"
        "  assemble_run_id INTEGER NOT NULL REFERENCES assemble_runs(id),"
        "  derivation_type TEXT CHECK(derivation_type IN ('copied','modified')),"
        "  created_at TEXT"
        ")"
    )


def _create_full_asset_tables(conn: sqlite3.Connection) -> None:
    """Create tables for library source/profile/asset/duplicate flows."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS library_sources ("
        "  id INTEGER PRIMARY KEY,"
        "  name TEXT NOT NULL,"
        "  source_type TEXT NOT NULL DEFAULT '',"
        "  metadata_json TEXT,"
        "  is_active INTEGER DEFAULT 1,"
        "  created_at TEXT,"
        "  updated_at TEXT,"
        "  UNIQUE (name, source_type)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS workspace_profiles ("
        "  id INTEGER PRIMARY KEY,"
        "  library_source_id INTEGER REFERENCES library_sources(id),"
        "  name TEXT NOT NULL,"
        "  metadata_json TEXT,"
        "  is_active INTEGER DEFAULT 1,"
        "  created_at TEXT,"
        "  updated_at TEXT,"
        "  UNIQUE (library_source_id, name)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS slide_assets ("
        "  id INTEGER PRIMARY KEY,"
        "  slide_id INTEGER NOT NULL REFERENCES slides(id),"
        "  workspace_profile_id INTEGER REFERENCES workspace_profiles(id),"
        "  source_id INTEGER REFERENCES library_sources(id),"
        "  asset_type TEXT NOT NULL,"
        "  asset_uri TEXT NOT NULL,"
        "  asset_hash TEXT,"
        "  metadata_json TEXT,"
        "  created_at TEXT,"
        "  updated_at TEXT,"
        "  UNIQUE (slide_id, asset_type, asset_uri)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS duplicate_groups ("
        "  id INTEGER PRIMARY KEY,"
        "  canonical_slide_id INTEGER NOT NULL REFERENCES slides(id),"
        "  workspace_profile_id INTEGER REFERENCES workspace_profiles(id),"
        "  created_at TEXT,"
        "  updated_at TEXT,"
        "  UNIQUE (canonical_slide_id)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS slide_duplicate_members ("
        "  id INTEGER PRIMARY KEY,"
        "  duplicate_group_id INTEGER NOT NULL REFERENCES duplicate_groups(id),"
        "  slide_id INTEGER NOT NULL REFERENCES slides(id),"
        "  canonical_slide_id INTEGER REFERENCES slides(id),"
        "  is_canonical INTEGER DEFAULT 0,"
        "  created_at TEXT,"
        "  UNIQUE (duplicate_group_id, slide_id)"
        ")"
    )


def _create_deck_intelligence_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS deck_families ("
        "  id INTEGER PRIMARY KEY,"
        "  family_key TEXT NOT NULL UNIQUE,"
        "  project_name TEXT,"
        "  title TEXT,"
        "  representative_presentation_id INTEGER REFERENCES presentations(id),"
        "  presentation_count INTEGER DEFAULT 0,"
        "  created_at TEXT,"
        "  updated_at TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS presentation_versions ("
        "  id INTEGER PRIMARY KEY,"
        "  presentation_id INTEGER NOT NULL UNIQUE REFERENCES presentations(id),"
        "  deck_family_id INTEGER NOT NULL REFERENCES deck_families(id),"
        "  version_key TEXT,"
        "  version_role TEXT,"
        "  version_rank INTEGER DEFAULT 0,"
        "  version_date TEXT,"
        "  is_representative INTEGER DEFAULT 0,"
        "  confidence REAL,"
        "  signals_json TEXT,"
        "  created_at TEXT,"
        "  updated_at TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS deck_insights ("
        "  id INTEGER PRIMARY KEY,"
        "  presentation_id INTEGER NOT NULL UNIQUE REFERENCES presentations(id),"
        "  status TEXT NOT NULL,"
        "  summary_json TEXT,"
        "  warnings_json TEXT,"
        "  generated_at TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS slide_importance ("
        "  id INTEGER PRIMARY KEY,"
        "  slide_id INTEGER NOT NULL UNIQUE REFERENCES slides(id),"
        "  importance_score REAL,"
        "  importance_reason TEXT,"
        "  page_role TEXT,"
        "  needs_visual INTEGER DEFAULT 0,"
        "  status TEXT,"
        "  updated_at TEXT"
        ")"
    )


def _create_deck_intelligence_indexes(conn: sqlite3.Connection) -> None:
    for index_sql in [
        "CREATE INDEX IF NOT EXISTS idx_presentation_versions_family ON presentation_versions(deck_family_id)",
        "CREATE INDEX IF NOT EXISTS idx_presentation_versions_representative ON presentation_versions(is_representative)",
        "CREATE INDEX IF NOT EXISTS idx_deck_families_representative ON deck_families(representative_presentation_id)",
        "CREATE INDEX IF NOT EXISTS idx_deck_insights_presentation ON deck_insights(presentation_id)",
        "CREATE INDEX IF NOT EXISTS idx_slide_importance_slide ON slide_importance(slide_id)",
    ]:
        conn.execute(index_sql)


def _serialize_embedding(embedding: np.ndarray | None) -> bytes | None:
    if embedding is None:
        return None
    vector = np.asarray(embedding, dtype=np.float32)
    if vector.ndim != 1 or vector.shape[0] <= 0:
        raise DatabaseError(f"Embedding must be a non-empty 1D float32 vector, got {vector.shape}")
    return np.ascontiguousarray(vector, dtype=np.float32).tobytes()


def _validate_source(source: str) -> None:
    if source not in {"vision_model", "text_extraction", "hybrid"}:
        raise DatabaseError(f"Invalid slide source: {source}")


def _validate_job_status(status: str) -> None:
    if status not in {"pending", "processing", "completed", "failed"}:
        raise DatabaseError(f"Invalid job status: {status}")


def _job_from_row(row: sqlite3.Row) -> IndexJobRecord:
    return IndexJobRecord(
        id=int(row[0]),
        file_path=Path(row[1]),
        status=row[2],
        slide_index=row[3],
        error_msg=row[4],
        retry_count=int(row[5]),
        last_error_at=row[6],
        updated_at=row[7],
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _chunks(items: list[int] | list[str], size: int = 900):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _now_compact() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
