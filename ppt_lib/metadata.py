from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class MetadataJsonlError(RuntimeError):
    pass


def import_metadata_jsonl(conn: sqlite3.Connection, path: Path) -> dict[str, object]:
    imported = 0
    skipped = 0
    updated_slide_ids: list[int] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        item = _parse_metadata_line(line, line_no)
        slide_id = _parse_slide_id(item, line_no)
        quality_rating = _parse_quality_rating(item.get("quality_rating"), line_no)

        cursor = conn.execute(
            """
            UPDATE slides
            SET industry = ?,
                scenario = ?,
                narrative_role = ?,
                quality_rating = ?
            WHERE id = ?
            """,
            (
                _optional_str(item.get("industry")),
                _optional_str(item.get("scenario")),
                _optional_str(item.get("narrative_role")),
                quality_rating,
                slide_id,
            ),
        )
        if cursor.rowcount == 0:
            skipped += 1
            continue
        imported += 1
        updated_slide_ids.append(slide_id)
    conn.commit()
    return {"imported": imported, "skipped": skipped, "updated_slide_ids": updated_slide_ids}


def export_metadata_jsonl(conn: sqlite3.Connection, path: Path) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT id, industry, scenario, narrative_role, quality_rating,
               win_rate, won_count, lost_count, reuse_count, last_deal_outcome, origin_type
        FROM slides
        ORDER BY id
        """
    ).fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            item = {
                "slide_id": int(row[0]),
                "industry": row[1],
                "scenario": row[2],
                "narrative_role": row[3],
                "quality_rating": row[4],
                "win_rate": row[5],
                "won_count": int(row[6] or 0),
                "lost_count": int(row[7] or 0),
                "reuse_count": int(row[8] or 0),
                "last_deal_outcome": row[9],
                "origin_type": row[10],
            }
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
    return {"exported": len(rows), "output_path": path}


def _parse_metadata_line(line: str, line_no: int) -> dict[str, object]:
    try:
        item = json.loads(line)
    except json.JSONDecodeError as exc:
        raise MetadataJsonlError(f"Invalid JSON on line {line_no}: {exc.msg}") from exc
    if not isinstance(item, dict):
        raise MetadataJsonlError(f"Line {line_no} must be a JSON object")
    return item


def _parse_slide_id(item: dict[str, object], line_no: int) -> int:
    if "slide_id" not in item:
        raise MetadataJsonlError(f"Line {line_no} must contain integer slide_id")
    return _parse_int(item["slide_id"], f"Line {line_no} must contain integer slide_id")


def _parse_quality_rating(value: object, line_no: int) -> int | None:
    if value is None:
        return None
    return _parse_int(value, f"Line {line_no} quality_rating must be an integer or null")


def _parse_int(value: object, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise MetadataJsonlError(message)
    try:
        return int(value)
    except ValueError as exc:
        raise MetadataJsonlError(message) from exc


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
