from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ppt_lib.db import (
    ScreenshotRecord,
    backup_db,
    delete_jobs,
    delete_presentations,
    delete_screenshots,
    delete_slides_for_presentations,
    list_missing_job_ids,
    list_orphan_presentations,
    list_unreferenced_screenshots,
)
from ppt_lib.settings import Settings


@dataclass(frozen=True)
class PruneResult:
    dry_run: bool
    backup_path: str | None
    presentation_count: int
    slide_count: int
    job_count: int
    screenshot_count: int
    removed_presentations: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class PurgeResult:
    dry_run: bool
    backup_path: str | None
    presentation_count: int
    slide_count: int
    lineage_count: int
    assemble_run_count: int
    job_count: int
    screenshot_count: int
    warnings: list[str]


def prune_orphans(conn: sqlite3.Connection, settings: Settings, *, dry_run: bool = True) -> PruneResult:
    orphans = list_orphan_presentations(conn)
    orphan_ids = [item.id for item in orphans]
    missing_job_ids = list_missing_job_ids(conn)
    slide_count = _count_slides_for_presentations(conn, orphan_ids)
    screenshot_hashes = _screenshot_hashes_that_would_become_unreferenced(conn, orphan_ids)
    removed_presentations = [str(item.path) for item in orphans]

    if dry_run:
        return PruneResult(
            dry_run=True,
            backup_path=None,
            presentation_count=len(orphans),
            slide_count=slide_count,
            job_count=len(missing_job_ids),
            screenshot_count=len(screenshot_hashes),
            removed_presentations=removed_presentations,
            warnings=[],
        )

    backup_path = None
    if settings.backups_dir is not None:
        backup_path = str(backup_db(conn, settings.backups_dir))
    deleted_slide_count = delete_slides_for_presentations(conn, orphan_ids, commit=False)
    deleted_presentation_count = delete_presentations(conn, orphan_ids, commit=False)
    deleted_job_count = delete_jobs(conn, missing_job_ids, commit=False)
    unreferenced = list_unreferenced_screenshots(conn)
    deleted_screenshot_count = delete_screenshots(conn, [item.hash for item in unreferenced], commit=False)
    conn.commit()
    warnings = _delete_screenshot_files(settings, unreferenced)

    return PruneResult(
        dry_run=False,
        backup_path=backup_path,
        presentation_count=deleted_presentation_count,
        slide_count=deleted_slide_count,
        job_count=deleted_job_count,
        screenshot_count=deleted_screenshot_count,
        removed_presentations=removed_presentations,
        warnings=warnings,
    )


def purge_assembled_output(conn: sqlite3.Connection, settings: Settings, *, dry_run: bool = True) -> PurgeResult:
    presentation_ids = _assembled_presentation_ids(conn)
    slide_ids = _assembled_slide_ids(conn)
    lineage_ids = _lineage_ids_for_derived_slides(conn, slide_ids)
    assemble_run_ids = _assemble_run_ids_for_outputs(conn, presentation_ids, lineage_ids)
    job_ids = _job_ids_for_presentations(conn, presentation_ids)
    screenshot_hashes = _screenshot_hashes_that_would_become_unreferenced(conn, presentation_ids)

    if dry_run:
        return PurgeResult(
            dry_run=True,
            backup_path=None,
            presentation_count=len(presentation_ids),
            slide_count=len(slide_ids),
            lineage_count=len(lineage_ids),
            assemble_run_count=len(assemble_run_ids),
            job_count=len(job_ids),
            screenshot_count=len(screenshot_hashes),
            warnings=[],
        )

    backup_path = None
    if settings.backups_dir is not None:
        backup_path = str(backup_db(conn, settings.backups_dir))
    _delete_slide_usage_for_outputs(conn, slide_ids, presentation_ids)
    deleted_lineage_count = _delete_by_ids(conn, "slide_lineage", lineage_ids)
    deleted_assemble_run_count = _delete_by_ids(conn, "assemble_runs", assemble_run_ids)
    deleted_slide_count = delete_slides_for_presentations(conn, presentation_ids, commit=False)
    deleted_presentation_count = delete_presentations(conn, presentation_ids, commit=False)
    deleted_job_count = delete_jobs(conn, job_ids, commit=False)
    unreferenced = list_unreferenced_screenshots(conn)
    deleted_screenshot_count = delete_screenshots(conn, [item.hash for item in unreferenced], commit=False)
    conn.commit()
    warnings = _delete_screenshot_files(settings, unreferenced)

    return PurgeResult(
        dry_run=False,
        backup_path=backup_path,
        presentation_count=deleted_presentation_count,
        slide_count=deleted_slide_count,
        lineage_count=deleted_lineage_count,
        assemble_run_count=deleted_assemble_run_count,
        job_count=deleted_job_count,
        screenshot_count=deleted_screenshot_count,
        warnings=warnings,
    )


def _count_slides_for_presentations(conn: sqlite3.Connection, presentation_ids: list[int]) -> int:
    if not presentation_ids:
        return 0
    count = 0
    for chunk in _chunks(presentation_ids):
        placeholders = ",".join("?" for _ in chunk)
        count += int(conn.execute(f"SELECT COUNT(*) FROM slides WHERE presentation_id IN ({placeholders})", chunk).fetchone()[0])
    return count


def _assembled_presentation_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        """
        SELECT DISTINCT presentation_id
        FROM slides
        WHERE origin_type = 'assembled_output'
        ORDER BY presentation_id
        """
    ).fetchall()
    return [int(row[0]) for row in rows]


def _assembled_slide_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        """
        SELECT id
        FROM slides
        WHERE origin_type = 'assembled_output'
        ORDER BY id
        """
    ).fetchall()
    return [int(row[0]) for row in rows]


def _lineage_ids_for_derived_slides(conn: sqlite3.Connection, slide_ids: list[int]) -> list[int]:
    ids: list[int] = []
    for chunk in _chunks(slide_ids):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(f"SELECT id FROM slide_lineage WHERE derived_slide_id IN ({placeholders})", chunk).fetchall()
        ids.extend(int(row[0]) for row in rows)
    return ids


def _assemble_run_ids_for_outputs(conn: sqlite3.Connection, presentation_ids: list[int], lineage_ids: list[int]) -> list[int]:
    ids: set[int] = set()
    for chunk in _chunks(presentation_ids):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(f"SELECT id FROM assemble_runs WHERE output_presentation_id IN ({placeholders})", chunk).fetchall()
        ids.update(int(row[0]) for row in rows)
    for chunk in _chunks(lineage_ids):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(f"SELECT assemble_run_id FROM slide_lineage WHERE id IN ({placeholders})", chunk).fetchall()
        ids.update(int(row[0]) for row in rows)
    return sorted(ids)


def _job_ids_for_presentations(conn: sqlite3.Connection, presentation_ids: list[int]) -> list[int]:
    ids: list[int] = []
    for chunk in _chunks(presentation_ids):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT j.id
            FROM index_jobs j
            JOIN presentations p ON p.path = j.file_path
            WHERE p.id IN ({placeholders})
            """,
            chunk,
        ).fetchall()
        ids.extend(int(row[0]) for row in rows)
    return ids


def _delete_slide_usage_for_outputs(
    conn: sqlite3.Connection,
    slide_ids: list[int],
    presentation_ids: list[int],
) -> None:
    for chunk in _chunks(slide_ids):
        placeholders = ",".join("?" for _ in chunk)
        conn.execute(f"DELETE FROM slide_usage WHERE slide_id IN ({placeholders})", chunk)
    for chunk in _chunks(presentation_ids):
        placeholders = ",".join("?" for _ in chunk)
        conn.execute(f"DELETE FROM slide_usage WHERE deck_presentation_id IN ({placeholders})", chunk)


def _delete_by_ids(conn: sqlite3.Connection, table: str, ids: list[int]) -> int:
    deleted = 0
    for chunk in _chunks(ids):
        placeholders = ",".join("?" for _ in chunk)
        cursor = conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", chunk)
        deleted += int(cursor.rowcount if cursor.rowcount != -1 else 0)
    return deleted


def _screenshot_hashes_that_would_become_unreferenced(conn: sqlite3.Connection, presentation_ids: list[int]) -> list[str]:
    if not presentation_ids:
        return [item.hash for item in list_unreferenced_screenshots(conn)]
    orphan_id_set = set(presentation_ids)
    hashes: set[str] = set()
    for chunk in _chunks(presentation_ids):
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT DISTINCT screenshot_hash
            FROM slides
            WHERE presentation_id IN ({placeholders}) AND screenshot_hash IS NOT NULL
            """,
            chunk,
        ).fetchall()
        hashes.update(str(row[0]) for row in rows)
    removable: list[str] = []
    for item in sorted(hashes):
        rows = conn.execute("SELECT presentation_id FROM slides WHERE screenshot_hash = ?", (item,)).fetchall()
        if all(int(row[0]) in orphan_id_set for row in rows):
            removable.append(item)
    removable.extend(item.hash for item in list_unreferenced_screenshots(conn) if item.hash not in removable)
    return removable


def _delete_screenshot_files(settings: Settings, screenshots: Iterable[ScreenshotRecord]) -> list[str]:
    warnings: list[str] = []
    screenshots_dir = settings.screenshots_dir.resolve(strict=False) if settings.screenshots_dir else None
    for screenshot in screenshots:
        path = Path(screenshot.file_path)
        if screenshots_dir and path.resolve(strict=False).is_relative_to(screenshots_dir):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                warnings.append(f"Failed to delete screenshot file {path}: {exc}")
    return warnings


def _chunks(items: list[int], size: int = 900) -> Iterable[list[int]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]
