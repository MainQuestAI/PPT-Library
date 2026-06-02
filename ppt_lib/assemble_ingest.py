from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from ppt_lib.assembler import AssembleManifest, AssembleReport
from ppt_lib.db import connect, init_db
from ppt_lib.indexer import IndexResult
from ppt_lib.settings import Settings


class AssembleIngestError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssembleIngestResult:
    status: str
    assemble_run_id: int
    output_presentation_id: int | None
    indexed_slides: int
    lineage_count: int
    warnings: list[str]


def ingest_assemble_output(
    settings: Settings,
    manifest: AssembleManifest,
    report: AssembleReport,
    *,
    index_file_func: Callable[..., IndexResult],
) -> AssembleIngestResult:
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    run_id = _create_assemble_run(conn, manifest, report, status="completed_pending_ingest")

    index_result = index_file_func(report.output_path, settings, full=True)
    if index_result.status == "failed" or index_result.errors:
        warnings = [error.message for error in index_result.errors] or ["index failed"]
        return AssembleIngestResult(
            status="completed_pending_ingest",
            assemble_run_id=run_id,
            output_presentation_id=None,
            indexed_slides=0,
            lineage_count=0,
            warnings=warnings,
        )

    output_presentation_id = _presentation_id_for_path(conn, report.output_path)
    if output_presentation_id is None:
        return AssembleIngestResult(
            status="completed_pending_ingest",
            assemble_run_id=run_id,
            output_presentation_id=None,
            indexed_slides=index_result.slides_indexed,
            lineage_count=0,
            warnings=[f"indexed output presentation not found: {report.output_path}"],
        )

    try:
        conn.execute("BEGIN")
        _mark_output_slides(conn, output_presentation_id)
        lineage_count, warnings = _insert_lineage(conn, manifest, output_presentation_id, run_id)
        status = "completed" if lineage_count == len(manifest.slides) and not warnings else "partial"
        _update_assemble_run(conn, run_id, output_presentation_id=output_presentation_id, status=status)
        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        raise AssembleIngestError(f"Failed to write assemble lineage: {exc}") from exc

    return AssembleIngestResult(
        status=status,
        assemble_run_id=run_id,
        output_presentation_id=output_presentation_id,
        indexed_slides=index_result.slides_indexed,
        lineage_count=lineage_count,
        warnings=warnings,
    )


def _create_assemble_run(
    conn: sqlite3.Connection,
    manifest: AssembleManifest,
    report: AssembleReport,
    *,
    status: str,
) -> int:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO assemble_runs (run_name, manifest_hash, slide_count, created_at, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (manifest.run_name, _manifest_hash(manifest), report.slide_count, now, status),
    )
    conn.commit()
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _update_assemble_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    output_presentation_id: int,
    status: str,
) -> None:
    conn.execute(
        """
        UPDATE assemble_runs
        SET output_presentation_id = ?, status = ?
        WHERE id = ?
        """,
        (output_presentation_id, status, run_id),
    )


def _presentation_id_for_path(conn: sqlite3.Connection, path) -> int | None:
    row = conn.execute("SELECT id FROM presentations WHERE path = ?", (str(path),)).fetchone()
    return int(row[0]) if row else None


def _mark_output_slides(conn: sqlite3.Connection, presentation_id: int) -> None:
    conn.execute(
        "UPDATE slides SET origin_type = 'assembled_output' WHERE presentation_id = ?",
        (presentation_id,),
    )


def _insert_lineage(
    conn: sqlite3.Connection,
    manifest: AssembleManifest,
    output_presentation_id: int,
    run_id: int,
) -> tuple[int, list[str]]:
    output_rows = conn.execute(
        """
        SELECT id, slide_index
        FROM slides
        WHERE presentation_id = ?
        ORDER BY slide_index
        """,
        (output_presentation_id,),
    ).fetchall()
    derived_by_index = {int(row[1]): int(row[0]) for row in output_rows}
    warnings: list[str] = []
    lineage_count = 0
    for output_index, source_spec in enumerate(manifest.slides):
        derived_slide_id = derived_by_index.get(output_index)
        if derived_slide_id is None:
            warnings.append(f"missing derived slide for output index {output_index}")
            continue
        source_slide_id = source_spec.source_slide_id or _resolve_source_slide_id(conn, source_spec.source_file, source_spec.page_number)
        if source_slide_id is None or not _slide_exists(conn, source_slide_id):
            warnings.append(f"missing source slide for output index {output_index}")
            continue
        conn.execute(
            """
            INSERT INTO slide_lineage (derived_slide_id, source_slide_id, assemble_run_id, derivation_type, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (derived_slide_id, source_slide_id, run_id, "copied", datetime.now(UTC).isoformat()),
        )
        lineage_count += 1
    return lineage_count, warnings


def _resolve_source_slide_id(conn: sqlite3.Connection, source_file, page_number: int) -> int | None:
    row = conn.execute(
        """
        SELECT s.id
        FROM slides s
        JOIN presentations p ON p.id = s.presentation_id
        WHERE p.path = ? AND s.slide_index = ?
        """,
        (str(source_file), page_number - 1),
    ).fetchone()
    return int(row[0]) if row else None


def _slide_exists(conn: sqlite3.Connection, slide_id: int) -> bool:
    return conn.execute("SELECT 1 FROM slides WHERE id = ?", (slide_id,)).fetchone() is not None


def _manifest_hash(manifest: AssembleManifest) -> str:
    payload = {
        "run_name": manifest.run_name,
        "output_path": str(manifest.output_path),
        "slides": [
            {
                "source_file": str(slide.source_file),
                "page_number": slide.page_number,
                "source_slide_id": slide.source_slide_id,
            }
            for slide in manifest.slides
        ],
    }
    return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
