import sqlite3
from pathlib import Path

import numpy as np
import pytest

from ppt_lib.db import (
    SCHEMA_VERSION,
    DatabaseError,
    PresentationRecord,
    ScreenshotRecord,
    SlideRecord,
    WorkspaceProfileRecord,
    backup_db,
    connect,
    create_or_update_job,
    create_workspace_profile,
    get_active_workspace_profile,
    get_all_embeddings,
    get_schema_version,
    get_stats,
    init_db,
    insert_deal,
    insert_screenshot,
    list_failed_jobs,
    list_library_sources,
    list_orphan_presentations,
    mark_job_completed,
    mark_job_failed,
    recompute_slide_stats,
    record_slide_usage,
    replace_presentation_slides,
    update_slide_summary_fields,
    upsert_duplicate_group,
    upsert_duplicate_member,
    upsert_library_source,
    upsert_presentation,
    upsert_slide,
    upsert_slide_asset,
)


def initialized_conn(tmp_path: Path, *, backups_dir: Path | None = None) -> sqlite3.Connection:
    conn = connect(tmp_path / "index.db")
    init_db(conn, backups_dir=backups_dir)
    return conn


def test_init_db_creates_schema(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    assert {"_meta", "presentations", "slides", "screenshots", "index_jobs",
            "deals", "assemble_runs", "slide_usage", "slide_lineage",
            "library_sources", "workspace_profiles", "slide_assets",
            "duplicate_groups", "slide_duplicate_members", "deck_families",
            "presentation_versions", "deck_insights", "slide_importance"} <= tables


def test_init_db_idempotent(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)

    init_db(conn)

    assert conn.execute("SELECT COUNT(*) FROM presentations").fetchone()[0] == 0


def test_wal_enabled(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)

    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert journal_mode.lower() == "wal"


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)

    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO slide_usage (slide_id, deal_id, deck_presentation_id, position)
            VALUES (?, ?, ?, ?)
            """,
            (999, 999, 999, 1),
        )


def test_upsert_presentation_updates_by_path(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    record = PresentationRecord(
        path=tmp_path / "deck.pptx",
        filename="deck.pptx",
        project_name="alpha",
        slide_count=3,
        content_hash="a",
        file_size=100,
        file_mtime=1.0,
    )

    first_id = upsert_presentation(conn, record)
    second_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name="alpha",
            slide_count=4,
            content_hash="b",
            file_size=100,
            file_mtime=1.0,
        ),
    )

    row = conn.execute("SELECT slide_count, content_hash FROM presentations").fetchone()
    assert second_id == first_id
    assert row == (4, "b")


def test_upsert_slide_unique_by_presentation_and_index(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="a",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    vector = np.ones(1536, dtype=np.float32)

    first_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title="Old",
            text_content="old text",
            embedding=vector,
            screenshot_hash="hash",
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={"a": 1},
        ),
    )
    second_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title="New",
            text_content="new text",
            embedding=vector,
            screenshot_hash="hash",
            source="hybrid",
            extraction_warnings=["fallback"],
            metadata_json={"b": 2},
        ),
    )

    row = conn.execute("SELECT title, source FROM slides").fetchone()
    assert second_id == first_id
    assert row == ("New", "hybrid")


def test_insert_screenshot_deduplicates_by_hash(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    screenshot = ScreenshotRecord(
        hash="abc",
        file_path=tmp_path / "abc.png",
        width=1600,
        height=900,
    )

    insert_screenshot(conn, screenshot)
    insert_screenshot(conn, screenshot)

    assert conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 1


def test_get_all_embeddings_shape(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="a",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    vector = np.arange(1536, dtype=np.float32)
    upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title="Title",
            text_content="text",
            embedding=vector,
            screenshot_hash=None,
            source="vision_model",
            extraction_warnings=[],
            metadata_json={},
        ),
    )

    rows = get_all_embeddings(conn)

    assert len(rows) == 1
    assert rows[0].embedding.shape == (1536,)
    assert rows[0].embedding.dtype == np.float32
    np.testing.assert_array_equal(rows[0].embedding, vector)


def test_upsert_slide_accepts_configurable_embedding_dimensions(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="a",
            file_size=100,
            file_mtime=1.0,
        ),
    )
    vector = np.arange(768, dtype=np.float32)

    upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title="Title",
            text_content="text",
            embedding=vector,
            screenshot_hash=None,
            source="vision_model",
            extraction_warnings=[],
            metadata_json={},
        ),
    )

    rows = get_all_embeddings(conn)

    assert rows[0].embedding.shape == (768,)
    np.testing.assert_array_equal(rows[0].embedding, vector)


def test_upsert_slide_rejects_non_vector_embedding(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="a",
            file_size=100,
            file_mtime=1.0,
        ),
    )

    with pytest.raises(DatabaseError):
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=presentation_id,
                slide_index=0,
                title="Title",
                text_content="text",
                embedding=np.ones((2, 2), dtype=np.float32),
                screenshot_hash=None,
                source="vision_model",
                extraction_warnings=[],
                metadata_json={},
            ),
        )


def test_index_job_lifecycle(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)

    job_id = create_or_update_job(conn, tmp_path / "deck.pptx", "pending")
    create_or_update_job(conn, tmp_path / "deck.pptx", "processing", slide_index=2)
    mark_job_failed(conn, job_id, "bad file")

    failed = list_failed_jobs(conn)
    assert len(failed) == 1
    assert failed[0].status == "failed"
    assert failed[0].error_msg == "bad file"

    mark_job_completed(conn, job_id)
    assert list_failed_jobs(conn) == []


def test_stats_include_failed_jobs_and_orphans(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "missing.pptx",
            filename="missing.pptx",
            project_name=None,
            slide_count=0,
            content_hash="a",
            file_size=1,
            file_mtime=1.0,
        ),
    )
    create_or_update_job(conn, tmp_path / "bad.pptx", "failed", error_msg="bad")

    stats = get_stats(conn)

    assert stats.presentation_count == 1
    assert stats.failed_job_count == 1
    assert stats.orphan_presentation_count == 1
    assert list_orphan_presentations(conn)[0].path == tmp_path / "missing.pptx"


def test_replace_presentation_slides_removes_old_rows(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=2,
            content_hash="a",
            file_size=1,
            file_mtime=1.0,
        ),
    )
    vector = np.ones(1536, dtype=np.float32)
    for slide_index in [0, 1]:
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=presentation_id,
                slide_index=slide_index,
                title=None,
                text_content=f"old-{slide_index}",
                embedding=vector,
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            ),
        )
    replace_presentation_slides(
        conn,
        presentation_id,
        [
            SlideRecord(
                presentation_id=presentation_id,
                slide_index=0,
                title=None,
                text_content="new",
                embedding=vector,
                screenshot_hash=None,
                source="text_extraction",
                extraction_warnings=[],
                metadata_json={},
            )
        ],
    )
    conn.commit()

    assert conn.execute("SELECT slide_index, text_content FROM slides").fetchall() == [(0, "new")]


def test_source_field_accepts_only_allowed_values(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="a",
            file_size=1,
            file_mtime=1.0,
        ),
    )

    with pytest.raises(DatabaseError):
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id=presentation_id,
                slide_index=0,
                title=None,
                text_content="",
                embedding=np.ones(1536, dtype=np.float32),
                screenshot_hash=None,
                source="bad_source",
                extraction_warnings=[],
                metadata_json={},
            ),
        )


def test_backup_uses_consistent_snapshot(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=1,
            content_hash="a",
            file_size=1,
            file_mtime=1.0,
        ),
    )

    backup_path = backup_db(conn, tmp_path / "backups")

    backup_conn = sqlite3.connect(backup_path)
    assert backup_conn.execute("SELECT COUNT(*) FROM presentations").fetchone()[0] == 1


# ── Schema migration tests ────────────────────────────────────────────


def test_init_db_creates_full_asset_tables(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "deals" in tables
    assert "assemble_runs" in tables
    assert "slide_usage" in tables
    assert "slide_lineage" in tables
    assert "library_sources" in tables
    assert "workspace_profiles" in tables
    assert "slide_assets" in tables
    assert "duplicate_groups" in tables
    assert "slide_duplicate_members" in tables
    assert "deck_families" in tables
    assert "presentation_versions" in tables
    assert "deck_insights" in tables
    assert "slide_importance" in tables


def test_init_db_creates_new_slides_columns(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(slides)").fetchall()}
    for col in ("industry", "scenario", "narrative_role", "win_rate", "won_count",
                "lost_count", "reuse_count", "last_deal_outcome", "quality_rating",
                "origin_type", "raw_text", "ai_summary", "visual_summary",
                "summary_status", "profile_id", "text_hash", "content_hash",
                "canonical_slide_id"):
        assert col in cols, f"Missing column: {col}"


def test_init_db_sets_schema_version(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    assert get_schema_version(conn) == SCHEMA_VERSION


def test_migration_from_v2_legacy_preserves_slides(tmp_path: Path) -> None:
    db_path = tmp_path / "migrate.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS presentations (
          id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, filename TEXT NOT NULL,
          project_name TEXT, slide_count INTEGER, content_hash TEXT,
          file_size INTEGER, file_mtime REAL, indexed_at TEXT, last_validated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS slides (
          id INTEGER PRIMARY KEY, presentation_id INTEGER REFERENCES presentations(id),
          slide_index INTEGER NOT NULL, title TEXT, text_content TEXT,
          embedding BLOB, screenshot_hash TEXT,
          source TEXT NOT NULL CHECK(source IN ('vision_model','text_extraction','hybrid')),
          extraction_warnings TEXT, metadata_json TEXT,
          UNIQUE(presentation_id, slide_index)
        );
        CREATE TABLE IF NOT EXISTS screenshots (
          hash TEXT PRIMARY KEY, file_path TEXT NOT NULL, width INTEGER, height INTEGER
        );
        CREATE TABLE IF NOT EXISTS index_jobs (
          id INTEGER PRIMARY KEY, file_path TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL CHECK(status IN ('pending','processing','completed','failed')),
          slide_index INTEGER, error_msg TEXT, retry_count INTEGER DEFAULT 0,
          last_error_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    conn.execute(
        "INSERT INTO _meta (key, value) VALUES ('schema_version', '2')"
    )
    conn.execute(
        "INSERT INTO presentations (path, filename, slide_count, content_hash, file_size, file_mtime) VALUES (?, ?, ?, ?, ?, ?)",
        (str(tmp_path / "old.pptx"), "old.pptx", 3, "abc", 100, 1.0),
    )
    conn.execute(
        "INSERT INTO slides (presentation_id, slide_index, title, text_content, source) VALUES (?, ?, ?, ?, ?)",
        (1, 0, "Old Slide", "old text", "text_extraction"),
    )
    conn.commit()
    conn.close()

    conn = connect(db_path)
    init_db(conn, backups_dir=tmp_path / "backups")

    assert get_schema_version(conn) == SCHEMA_VERSION
    cols = {row[1] for row in conn.execute("PRAGMA table_info(slides)").fetchall()}
    for col in ("industry", "origin_type", "win_rate", "raw_text", "ai_summary", "canonical_slide_id"):
        assert col in cols

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "slide_assets" in tables
    assert "duplicate_groups" in tables
    assert "slide_duplicate_members" in tables
    assert "workspace_profiles" in tables

    row = conn.execute("SELECT title, text_content FROM slides WHERE id = 1").fetchone()
    assert row == ("Old Slide", "old text")

    assert conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 0

    assert conn.execute("SELECT name FROM library_sources").fetchone() is None

    backups = list(tmp_path.glob("backups/*.db"))
    assert len(backups) >= 1
    conn.close()


def test_migration_without_backup_still_succeeds(tmp_path: Path) -> None:
    db_path = tmp_path / "nobackup.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE presentations (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, filename TEXT NOT NULL);
        CREATE TABLE slides (id INTEGER PRIMARY KEY, presentation_id INTEGER, slide_index INTEGER NOT NULL,
          title TEXT, text_content TEXT, embedding BLOB, screenshot_hash TEXT,
          source TEXT NOT NULL CHECK(source IN ('vision_model','text_extraction','hybrid')),
          extraction_warnings TEXT, metadata_json TEXT,
          UNIQUE(presentation_id, slide_index));
        CREATE TABLE screenshots (hash TEXT PRIMARY KEY, file_path TEXT NOT NULL);
        CREATE TABLE index_jobs (id INTEGER PRIMARY KEY, file_path TEXT NOT NULL UNIQUE, status TEXT NOT NULL);
    """)
    conn.commit()
    conn.close()

    conn = connect(db_path)
    init_db(conn)
    assert get_schema_version(conn) == SCHEMA_VERSION
    cols = {row[1] for row in conn.execute("PRAGMA table_info(slides)").fetchall()}
    assert "raw_text" in cols
    conn.close()


def test_library_source_and_workspace_profile_crud(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    source_id = upsert_library_source(
        conn,
        "local-disk",
        source_type="local",
        metadata_json={"root": "tmp"},
    )
    sources = list_library_sources(conn)
    assert [source.name for source in sources] == ["local-disk"]

    profile_id1 = create_workspace_profile(
        conn,
        library_source_id=source_id,
        name="analysis",
        metadata_json={"mode": "baseline"},
    )
    profile_id2 = create_workspace_profile(
        conn,
        library_source_id=source_id,
        name="analysis",
        metadata_json={"mode": "overwrite"},
    )
    active = get_active_workspace_profile(conn, library_source_id=source_id)
    assert isinstance(active, WorkspaceProfileRecord)
    assert active.id == profile_id2
    assert profile_id2 == profile_id1

    record = conn.execute(
        "SELECT metadata_json FROM workspace_profiles WHERE id = ?", (profile_id2,)
    ).fetchone()
    assert record[0] is not None

    assert get_active_workspace_profile(conn, library_source_id=source_id) == active


def test_library_source_allows_same_path_for_multiple_roles(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    source_path = str(tmp_path / "baseline-and-library.pptx")

    baseline_id = upsert_library_source(conn, source_path, source_type="baseline")
    library_id = upsert_library_source(conn, source_path, source_type="library")

    assert baseline_id != library_id
    rows = conn.execute(
        "SELECT name, source_type FROM library_sources WHERE name = ? ORDER BY source_type",
        (source_path,),
    ).fetchall()
    assert rows == [(source_path, "baseline"), (source_path, "library")]


def test_slide_asset_and_duplicate_canonical_roundtrip(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=2,
            content_hash="a",
            file_size=1,
            file_mtime=1.0,
        ),
    )
    vector = np.ones(1536, dtype=np.float32)
    canonical_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title=None,
            text_content="canonical",
            embedding=vector,
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    duplicate_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=1,
            title=None,
            text_content="duplicate",
            embedding=vector,
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )

    source_id = upsert_library_source(conn, "local-disk")
    profile_id = create_workspace_profile(
        conn, library_source_id=source_id, name="analysis", is_active=False
    )

    update_slide_summary_fields(
        conn,
        canonical_id,
        raw_text="canonical text",
        ai_summary="summary",
        visual_summary="visual",
        summary_status="ready",
    )

    group_id = upsert_duplicate_group(
        conn,
        canonical_slide_id=canonical_id,
        workspace_profile_id=profile_id,
    )
    upsert_duplicate_member(
        conn,
        duplicate_group_id=group_id,
        slide_id=duplicate_id,
    )

    asset_id = upsert_slide_asset(
        conn,
        slide_id=canonical_id,
        asset_type="embedding",
        asset_uri="s3://bucket/canonical",
        workspace_profile_id=profile_id,
        source_id=source_id,
    )
    assert asset_id > 0

    canonical_row = conn.execute(
        "SELECT canonical_slide_id FROM slides WHERE id = ?", (duplicate_id,)
    ).fetchone()
    assert canonical_row[0] == canonical_id

    rows = conn.execute(
        "SELECT slide_id, asset_type FROM slide_assets WHERE id = ?", (asset_id,)
    ).fetchone()
    assert rows == (canonical_id, "embedding")


def test_duplicate_member_canonical_switch_updates_group_members_and_slides(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx",
            filename="deck.pptx",
            project_name=None,
            slide_count=2,
            content_hash="a",
            file_size=1,
            file_mtime=1.0,
        ),
    )
    vector = np.ones(1536, dtype=np.float32)
    old_canonical_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title="old",
            text_content="old",
            embedding=vector,
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    new_canonical_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=1,
            title="new",
            text_content="new",
            embedding=vector,
            screenshot_hash=None,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )
    group_id = upsert_duplicate_group(conn, canonical_slide_id=old_canonical_id)
    upsert_duplicate_member(
        conn,
        duplicate_group_id=group_id,
        slide_id=old_canonical_id,
        is_canonical=True,
    )

    upsert_duplicate_member(
        conn,
        duplicate_group_id=group_id,
        slide_id=new_canonical_id,
        is_canonical=True,
    )

    group_row = conn.execute(
        "SELECT canonical_slide_id FROM duplicate_groups WHERE id = ?",
        (group_id,),
    ).fetchone()
    assert group_row[0] == new_canonical_id

    member_rows = conn.execute(
        """
        SELECT slide_id, canonical_slide_id, is_canonical
        FROM slide_duplicate_members
        WHERE duplicate_group_id = ?
        ORDER BY slide_id
        """,
        (group_id,),
    ).fetchall()
    assert member_rows == [
        (old_canonical_id, new_canonical_id, 0),
        (new_canonical_id, new_canonical_id, 1),
    ]

    slide_rows = conn.execute(
        "SELECT id, canonical_slide_id FROM slides ORDER BY id"
    ).fetchall()
    assert slide_rows == [
        (old_canonical_id, new_canonical_id),
        (new_canonical_id, new_canonical_id),
    ]


def test_new_columns_are_nullable(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx", filename="deck.pptx", project_name=None,
            slide_count=1, content_hash="a", file_size=100, file_mtime=1.0,
        ),
    )
    sid = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id, slide_index=0,
            title="T", text_content="t", embedding=np.ones(1536, dtype=np.float32),
            screenshot_hash=None, source="text_extraction",
            extraction_warnings=[], metadata_json={},
        ),
    )
    row = conn.execute("SELECT industry, win_rate, origin_type FROM slides WHERE id = ?", (sid,)).fetchone()
    assert row[0] is None  # industry nullable
    assert row[1] is None  # win_rate nullable
    assert row[2] == "original"  # default value


# ── Deal / usage CRUD ──────────────────────────────────────────────────────


def test_insert_deal_creates_entry(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    deal_id = insert_deal(conn, "Test Project", client_type="retail", outcome="won")
    row = conn.execute("SELECT deal_name, client_type, outcome FROM deals WHERE id = ?", (deal_id,)).fetchone()
    assert row == ("Test Project", "retail", "won")


def test_record_slide_usage_creates_entry(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    pres_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx", filename="deck.pptx", project_name=None,
            slide_count=3, content_hash="a", file_size=100, file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id, slide_index=0, title="T", text_content="t",
            embedding=np.ones(1536, dtype=np.float32), screenshot_hash=None,
            source="text_extraction", extraction_warnings=[], metadata_json={},
        ),
    )
    deal_id = insert_deal(conn, "Deal A")

    usage_id = record_slide_usage(
        conn, slide_id=slide_id, deal_id=deal_id,
        deck_presentation_id=pres_id, position=1,
    )
    assert usage_id > 0
    row = conn.execute(
        "SELECT slide_id, deal_id, position FROM slide_usage WHERE id = ?", (usage_id,),
    ).fetchone()
    assert row == (slide_id, deal_id, 1)


def test_record_slide_usage_deduplicates(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    pres_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx", filename="deck.pptx", project_name=None,
            slide_count=1, content_hash="a", file_size=100, file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id, slide_index=0, title="T", text_content="t",
            embedding=np.ones(1536, dtype=np.float32), screenshot_hash=None,
            source="text_extraction", extraction_warnings=[], metadata_json={},
        ),
    )
    deal_id = insert_deal(conn, "Deal A")

    record_slide_usage(conn, slide_id=slide_id, deal_id=deal_id, deck_presentation_id=pres_id, position=1)
    record_slide_usage(conn, slide_id=slide_id, deal_id=deal_id, deck_presentation_id=pres_id, position=1)

    count = conn.execute("SELECT COUNT(*) FROM slide_usage").fetchone()[0]
    assert count == 1, "Duplicate usage should be silently ignored"


def test_record_slide_usage_deduplicates_missing_position(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    pres_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx", filename="deck.pptx", project_name=None,
            slide_count=1, content_hash="a", file_size=100, file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id, slide_index=0, title="T", text_content="t",
            embedding=np.ones(1536, dtype=np.float32), screenshot_hash=None,
            source="text_extraction", extraction_warnings=[], metadata_json={},
        ),
    )
    deal_id = insert_deal(conn, "Deal A")

    record_slide_usage(conn, slide_id=slide_id, deal_id=deal_id, deck_presentation_id=pres_id)
    record_slide_usage(conn, slide_id=slide_id, deal_id=deal_id, deck_presentation_id=pres_id)

    rows = conn.execute("SELECT position FROM slide_usage").fetchall()
    assert rows == [(0,)]


# ── Recompute cache fields ─────────────────────────────────────────────────


def test_recompute_stats_empty(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    result = recompute_slide_stats(conn)
    assert result == {"updated": 0}


def test_recompute_stats_updates_reuse_count(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)

    pres_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx", filename="deck.pptx", project_name=None,
            slide_count=1, content_hash="a", file_size=100, file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id, slide_index=0, title="T", text_content="t",
            embedding=np.ones(1536, dtype=np.float32), screenshot_hash=None,
            source="text_extraction", extraction_warnings=[], metadata_json={},
        ),
    )
    deal_won = insert_deal(conn, "Won Deal", outcome="won")
    deal_lost = insert_deal(conn, "Lost Deal", outcome="lost")

    record_slide_usage(conn, slide_id=slide_id, deal_id=deal_won, deck_presentation_id=pres_id, position=1)
    record_slide_usage(conn, slide_id=slide_id, deal_id=deal_lost, deck_presentation_id=pres_id, position=2)

    result = recompute_slide_stats(conn, slide_id=slide_id)
    assert result == {"updated": 1}

    row = conn.execute(
        "SELECT reuse_count, won_count, lost_count, win_rate, last_deal_outcome FROM slides WHERE id = ?",
        (slide_id,),
    ).fetchone()
    assert row[0] == 2  # reuse_count
    assert row[1] == 1  # won_count
    assert row[2] == 1  # lost_count
    assert row[3] == 0.5  # win_rate = 1/2
    assert row[4] == "lost"  # last outcome


def test_recompute_stats_full_recompute(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)

    pres_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx", filename="deck.pptx", project_name=None,
            slide_count=2, content_hash="a", file_size=100, file_mtime=1.0,
        ),
    )
    slide_a = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id, slide_index=0, title="A", text_content="a",
            embedding=np.ones(1536, dtype=np.float32), screenshot_hash=None,
            source="text_extraction", extraction_warnings=[], metadata_json={},
        ),
    )
    slide_b = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id, slide_index=1, title="B", text_content="b",
            embedding=np.ones(1536, dtype=np.float32), screenshot_hash=None,
            source="text_extraction", extraction_warnings=[], metadata_json={},
        ),
    )
    deal_id = insert_deal(conn, "Deal", outcome="won")
    record_slide_usage(conn, slide_id=slide_a, deal_id=deal_id, deck_presentation_id=pres_id, position=1)

    result = recompute_slide_stats(conn)
    assert result == {"updated": 2}

    row_a = conn.execute("SELECT reuse_count FROM slides WHERE id = ?", (slide_a,)).fetchone()
    row_b = conn.execute("SELECT reuse_count FROM slides WHERE id = ?", (slide_b,)).fetchone()
    assert row_a[0] == 1
    assert row_b[0] == 0


def test_record_slide_usage_triggers_auto_recompute(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)

    pres_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx", filename="deck.pptx", project_name=None,
            slide_count=1, content_hash="a", file_size=100, file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id, slide_index=0, title="T", text_content="t",
            embedding=np.ones(1536, dtype=np.float32), screenshot_hash=None,
            source="text_extraction", extraction_warnings=[], metadata_json={},
        ),
    )
    deal_id = insert_deal(conn, "Deal", outcome="won")

    # record_slide_usage auto-triggers recompute
    record_slide_usage(conn, slide_id=slide_id, deal_id=deal_id, deck_presentation_id=pres_id, position=1)

    row = conn.execute(
        "SELECT reuse_count, won_count FROM slides WHERE id = ?", (slide_id,),
    ).fetchone()
    assert row == (1, 1), "Auto-recompute should update cache fields immediately"


def test_record_slide_usage_can_be_rolled_back_with_outer_transaction(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    pres_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx", filename="deck.pptx", project_name=None,
            slide_count=1, content_hash="a", file_size=100, file_mtime=1.0,
        ),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id, slide_index=0, title="T", text_content="t",
            embedding=np.ones(1536, dtype=np.float32), screenshot_hash=None,
            source="text_extraction", extraction_warnings=[], metadata_json={},
        ),
    )
    deal_id = insert_deal(conn, "Deal", outcome="won")

    conn.execute("BEGIN")
    record_slide_usage(conn, slide_id=slide_id, deal_id=deal_id, deck_presentation_id=pres_id, position=1, commit=False)
    conn.rollback()

    assert conn.execute("SELECT COUNT(*) FROM slide_usage").fetchone()[0] == 0
    row = conn.execute(
        "SELECT reuse_count, won_count FROM slides WHERE id = ?", (slide_id,),
    ).fetchone()
    assert row == (0, 0)


# ── Critical #1: slide identity stability ──────────────────────────────────


def test_replace_presentation_slides_preserves_slide_ids(tmp_path: Path) -> None:
    conn = initialized_conn(tmp_path)
    pres_id = upsert_presentation(
        conn,
        PresentationRecord(
            path=tmp_path / "deck.pptx", filename="deck.pptx", project_name=None,
            slide_count=2, content_hash="a", file_size=100, file_mtime=1.0,
        ),
    )
    vector = np.ones(1536, dtype=np.float32)

    sid_0 = upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id, slide_index=0, title="S0", text_content="t0",
            embedding=vector, screenshot_hash=None, source="text_extraction",
            extraction_warnings=[], metadata_json={},
        ),
    )
    upsert_slide(
        conn,
        SlideRecord(
            presentation_id=pres_id, slide_index=1, title="S1", text_content="t1",
            embedding=vector, screenshot_hash=None, source="text_extraction",
            extraction_warnings=[], metadata_json={},
        ),
    )

    # Establish foreign key dependency: slide_usage references sid_0
    deal_id = insert_deal(conn, "Test Deal")
    record_slide_usage(conn, slide_id=sid_0, deal_id=deal_id, deck_presentation_id=pres_id, position=1)

    # Replace: keep slide_index=0 (updated), drop slide_index=1, add slide_index=2 (new)
    replace_presentation_slides(
        conn,
        pres_id,
        [
            SlideRecord(
                presentation_id=pres_id, slide_index=0, title="S0-updated",
                text_content="updated", embedding=vector, screenshot_hash=None,
                source="hybrid", extraction_warnings=[], metadata_json={},
            ),
            SlideRecord(
                presentation_id=pres_id, slide_index=2, title="S2-new",
                text_content="new", embedding=vector, screenshot_hash=None,
                source="text_extraction", extraction_warnings=[], metadata_json={},
            ),
        ],
    )

    rows = {
        int(row[0]): row
        for row in conn.execute(
            "SELECT slide_index, id, title FROM slides WHERE presentation_id = ?", (pres_id,)
        ).fetchall()
    }

    assert 0 in rows, "slide_index=0 should survive (upsert)"
    assert rows[0][1] == sid_0, "slide_index=0 should keep original id"
    assert rows[0][2] == "S0-updated", "slide_index=0 should have updated title"

    assert 1 not in rows, "slide_index=1 should be removed (not in replacement list)"
    assert 2 in rows, "slide_index=2 should be inserted (genuinely new)"

    # Verify that slide_usage FK still works (sid_0 still exists)
    usage = conn.execute("SELECT slide_id FROM slide_usage WHERE slide_id = ?", (sid_0,)).fetchone()
    assert usage is not None, "slide_usage referencing sid_0 should survive"
