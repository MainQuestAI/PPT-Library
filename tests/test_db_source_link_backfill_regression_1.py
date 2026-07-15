"""Regression coverage for incremental source-link backfill."""

from __future__ import annotations

from pathlib import Path

import ppt_lib.db as db
from ppt_lib.db import PresentationRecord, connect, init_db, upsert_library_source, upsert_presentation


def _presentation(path: Path, name: str) -> PresentationRecord:
    return PresentationRecord(
        path=path,
        filename=name,
        project_name="qa",
        slide_count=1,
        content_hash=name,
        file_size=1,
        file_mtime=1.0,
    )


def test_incremental_backfill_does_not_rescan_existing_presentations(tmp_path: Path, monkeypatch) -> None:
    # Regression: ISSUE-001 — a new presentation triggered a full source-link rescan during Workbench startup.
    # Found by /qa on 2026-07-15
    # Report: .gstack/qa-reports/qa-report-ppt-library-2026-07-15.md
    db_path = tmp_path / "index.db"
    source_root = tmp_path / "library"
    source_root.mkdir()
    conn = connect(db_path)
    init_db(conn)
    upsert_library_source(
        conn,
        str(source_root),
        source_type="library",
        metadata_json={"path": str(source_root)},
    )
    upsert_presentation(conn, _presentation(source_root / "first.pptx", "first.pptx"))
    init_db(conn)

    existing_linked_at = conn.execute(
        "SELECT linked_at FROM presentation_source_links WHERE presentation_id = 1"
    ).fetchone()[0]
    upsert_presentation(conn, _presentation(source_root / "second.pptx", "second.pptx"))
    monkeypatch.setattr(
        db,
        "backfill_presentation_source_links",
        lambda conn: (_ for _ in ()).throw(AssertionError("full backfill must not run")),
    )

    init_db(conn)

    assert conn.execute("SELECT COUNT(*) FROM presentation_source_links").fetchone()[0] == 2
    assert conn.execute(
        "SELECT linked_at FROM presentation_source_links WHERE presentation_id = 1"
    ).fetchone()[0] == existing_linked_at
    conn.close()
