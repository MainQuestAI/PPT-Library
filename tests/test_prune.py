from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ppt_lib.db import (
    PresentationRecord,
    ScreenshotRecord,
    SlideRecord,
    connect,
    create_or_update_job,
    init_db,
    insert_screenshot,
    upsert_presentation,
    upsert_slide,
)
from ppt_lib.prune import prune_orphans, purge_assembled_output
from ppt_lib.settings import Settings


def test_prune_orphans_dry_run_counts_without_deleting(tmp_path: Path) -> None:
    settings = Settings(home_dir=tmp_path)
    conn = connect(settings.db_path)
    init_db(conn)
    missing = tmp_path / "missing.pptx"
    presentation_id = _insert_presentation(conn, missing)
    _insert_slide(conn, presentation_id)
    create_or_update_job(conn, tmp_path / "missing-job.pptx", "failed", error_msg="bad")

    result = prune_orphans(conn, settings, dry_run=True)

    assert result.dry_run is True
    assert result.presentation_count == 1
    assert result.slide_count == 1
    assert result.job_count == 1
    assert result.warnings == []
    assert conn.execute("SELECT COUNT(*) FROM presentations").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM slides").fetchone()[0] == 1


def test_prune_orphans_apply_deletes_records_and_creates_backup(tmp_path: Path) -> None:
    settings = Settings(home_dir=tmp_path)
    conn = connect(settings.db_path)
    init_db(conn)
    missing = tmp_path / "missing.pptx"
    presentation_id = _insert_presentation(conn, missing)
    _insert_slide(conn, presentation_id)
    create_or_update_job(conn, tmp_path / "missing-job.pptx", "failed", error_msg="bad")

    result = prune_orphans(conn, settings, dry_run=False)

    assert result.dry_run is False
    assert result.backup_path is not None
    assert Path(result.backup_path).exists()
    assert result.presentation_count == 1
    assert result.slide_count == 1
    assert result.job_count == 1
    assert result.warnings == []
    assert conn.execute("SELECT COUNT(*) FROM presentations").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM slides").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM index_jobs").fetchone()[0] == 0


def test_prune_orphans_deletes_unreferenced_screenshot_inside_home(tmp_path: Path) -> None:
    settings = Settings(home_dir=tmp_path)
    conn = connect(settings.db_path)
    init_db(conn)
    assert settings.screenshots_dir is not None
    screenshot_path = settings.screenshots_dir / "abc.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(b"png")
    insert_screenshot(conn, ScreenshotRecord("abc", screenshot_path, 10, 10))
    missing = tmp_path / "missing.pptx"
    presentation_id = _insert_presentation(conn, missing)
    _insert_slide(conn, presentation_id, screenshot_hash="abc")

    result = prune_orphans(conn, settings, dry_run=False)

    assert result.screenshot_count == 1
    assert not screenshot_path.exists()
    assert conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0] == 0


def test_prune_orphans_does_not_delete_screenshot_file_before_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(home_dir=tmp_path).model_copy(update={"backups_dir": None})
    conn = connect(settings.db_path)
    init_db(conn)
    assert settings.screenshots_dir is not None
    screenshot_path = settings.screenshots_dir / "abc.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(b"png")
    insert_screenshot(conn, ScreenshotRecord("abc", screenshot_path, 10, 10))
    missing = tmp_path / "missing.pptx"
    presentation_id = _insert_presentation(conn, missing)
    _insert_slide(conn, presentation_id, screenshot_hash="abc")
    proxy = _CommitFailingConnection(conn)

    def fail_if_called(settings, screenshots):
        raise AssertionError("screenshot files must not be deleted before commit succeeds")

    monkeypatch.setattr("ppt_lib.prune._delete_screenshot_files", fail_if_called)

    with pytest.raises(RuntimeError, match="commit failed"):
        prune_orphans(proxy, settings, dry_run=False)

    assert screenshot_path.exists()


def test_prune_orphans_handles_more_than_sqlite_parameter_limit(tmp_path: Path) -> None:
    settings = Settings(home_dir=tmp_path)
    conn = connect(settings.db_path)
    init_db(conn)
    for index in range(1005):
        presentation_id = _insert_presentation(conn, tmp_path / f"missing-{index}.pptx")
        _insert_slide(conn, presentation_id)

    result = prune_orphans(conn, settings, dry_run=False)

    assert result.presentation_count == 1005
    assert result.slide_count == 1005
    assert conn.execute("SELECT COUNT(*) FROM presentations").fetchone()[0] == 0


def test_prune_orphans_no_orphans_reports_zero(tmp_path: Path) -> None:
    settings = Settings(home_dir=tmp_path)
    conn = connect(settings.db_path)
    init_db(conn)
    existing = tmp_path / "deck.pptx"
    existing.write_bytes(b"pptx")
    _insert_presentation(conn, existing)

    result = prune_orphans(conn, settings, dry_run=True)

    assert result.presentation_count == 0
    assert result.slide_count == 0


def test_purge_assembled_output_dry_run_counts_without_deleting(tmp_path: Path) -> None:
    settings = Settings(home_dir=tmp_path)
    conn = connect(settings.db_path)
    init_db(conn)
    source_id, derived_id, output_presentation_id = _insert_lineage_fixture(conn, tmp_path)

    result = purge_assembled_output(conn, settings, dry_run=True)

    assert result.dry_run is True
    assert result.presentation_count == 1
    assert result.slide_count == 1
    assert result.lineage_count == 1
    assert result.assemble_run_count == 1
    assert conn.execute("SELECT COUNT(*) FROM slides WHERE id IN (?, ?)", (source_id, derived_id)).fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM presentations WHERE id = ?", (output_presentation_id,)).fetchone()[0] == 1


def test_purge_assembled_output_apply_deletes_lineage_and_derived_records(tmp_path: Path) -> None:
    settings = Settings(home_dir=tmp_path)
    conn = connect(settings.db_path)
    init_db(conn)
    source_id, derived_id, output_presentation_id = _insert_lineage_fixture(conn, tmp_path)
    create_or_update_job(conn, tmp_path / "assembled.pptx", "completed")

    result = purge_assembled_output(conn, settings, dry_run=False)

    assert result.dry_run is False
    assert result.presentation_count == 1
    assert result.slide_count == 1
    assert result.lineage_count == 1
    assert result.assemble_run_count == 1
    assert result.job_count == 1
    assert conn.execute("SELECT COUNT(*) FROM slides WHERE id = ?", (source_id,)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM slides WHERE id = ?", (derived_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM presentations WHERE id = ?", (output_presentation_id,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM slide_lineage").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM assemble_runs").fetchone()[0] == 0


def _insert_presentation(conn, path: Path) -> int:
    return upsert_presentation(
        conn,
        PresentationRecord(
            path=path,
            filename=path.name,
            project_name=None,
            slide_count=1,
            content_hash=f"hash-{path.name}",
            file_size=1,
            file_mtime=1.0,
        ),
    )


def _insert_slide(conn, presentation_id: int, screenshot_hash: str | None = None) -> int:
    return upsert_slide(
        conn,
        SlideRecord(
            presentation_id=presentation_id,
            slide_index=0,
            title="Title",
            text_content="Body",
            embedding=np.ones(3, dtype=np.float32),
            screenshot_hash=screenshot_hash,
            source="text_extraction",
            extraction_warnings=[],
            metadata_json={},
        ),
    )


def _insert_lineage_fixture(conn, tmp_path: Path) -> tuple[int, int, int]:
    source_presentation_id = _insert_presentation(conn, tmp_path / "source.pptx")
    source_id = _insert_slide(conn, source_presentation_id)
    output_presentation_id = _insert_presentation(conn, tmp_path / "assembled.pptx")
    derived_id = _insert_slide(conn, output_presentation_id)
    conn.execute("UPDATE slides SET origin_type = 'assembled_output' WHERE id = ?", (derived_id,))
    conn.execute(
        """
        INSERT INTO assemble_runs (run_name, output_presentation_id, slide_count, created_at, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("run", output_presentation_id, 1, "2026-05-25T00:00:00+00:00", "completed"),
    )
    run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """
        INSERT INTO slide_lineage (derived_slide_id, source_slide_id, assemble_run_id, derivation_type, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (derived_id, source_id, run_id, "copied", "2026-05-25T00:00:00+00:00"),
    )
    conn.commit()
    return source_id, derived_id, output_presentation_id


class _CommitFailingConnection:
    def __init__(self, inner):
        self.inner = inner

    def execute(self, *args, **kwargs):
        return self.inner.execute(*args, **kwargs)

    def commit(self):
        raise RuntimeError("commit failed")
