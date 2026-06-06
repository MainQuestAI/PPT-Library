from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def list_key_pages(
    conn: sqlite3.Connection,
    *,
    status: str = "candidate",
    needs_visual: bool = False,
    limit: int | None = None,
) -> dict[str, object]:
    rows = _fetch_insight_rows(conn, status=status, needs_visual=needs_visual, limit=limit)
    items = [_row_to_item(row) for row in rows]
    return {
        "summary": {
            "total": len(items),
            "status": status,
            "needs_visual": needs_visual,
            "message": _empty_message(items),
        },
        "items": items,
        "next_commands": [
            "ppt-lib enrich-decks --pending --limit 20",
            "ppt-lib search \"<query>\" --ranking business --output json",
            "ppt-lib insights review-pack --output review-pack.jsonl",
        ],
    }


def export_review_pack(
    conn: sqlite3.Connection,
    path: Path,
    *,
    output_format: str = "jsonl",
    limit: int | None = None,
) -> dict[str, object]:
    rows = _fetch_review_rows(conn, limit=limit)
    items = [_row_to_item(row) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(
            "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items) + ("\n" if items else ""),
            encoding="utf-8",
        )
    return {
        "exported": len(items),
        "output_path": path,
        "output_format": output_format,
        "summary": {
            "candidate_count": sum(1 for item in items if item.get("status") == "candidate"),
            "needs_visual_count": sum(1 for item in items if item.get("needs_visual") is True),
        },
    }


def _fetch_insight_rows(
    conn: sqlite3.Connection,
    *,
    status: str,
    needs_visual: bool,
    limit: int | None,
) -> list[dict[str, object]]:
    where = ["1=1"]
    params: list[object] = []
    if status != "all":
        where.append("si.status = ?")
        params.append(status)
    if needs_visual:
        where.append("si.needs_visual = 1")
    return _execute_insight_query(conn, where, params, limit)


def _fetch_review_rows(conn: sqlite3.Connection, *, limit: int | None) -> list[dict[str, object]]:
    return _execute_insight_query(conn, [], [], limit, left_join_importance=True)


def _execute_insight_query(
    conn: sqlite3.Connection,
    where: list[str],
    params: list[object],
    limit: int | None,
    *,
    left_join_importance: bool = False,
) -> list[dict[str, object]]:
    importance_join = (
        "LEFT JOIN slide_importance si ON si.slide_id = s.id"
        if left_join_importance
        else "JOIN slide_importance si ON si.slide_id = s.id"
    )
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT ?"
        params = [*params, limit]
    cursor = conn.execute(
        f"""
        SELECT
          s.id AS slide_id,
          s.slide_index AS slide_index,
          s.title AS title,
          s.industry AS industry,
          s.scenario AS scenario,
          s.narrative_role AS narrative_role,
          s.quality_rating AS quality_rating,
          s.win_rate AS win_rate,
          s.won_count AS won_count,
          s.lost_count AS lost_count,
          s.reuse_count AS reuse_count,
          s.last_deal_outcome AS last_deal_outcome,
          p.id AS presentation_id,
          p.path AS path,
          p.filename AS filename,
          p.project_name AS project_name,
          si.importance_score AS importance_score,
          si.importance_reason AS importance_reason,
          si.page_role AS page_role,
          si.needs_visual AS needs_visual,
          si.status AS status,
          pv.deck_family_id AS deck_family_id,
          pv.version_role AS version_role,
          pv.is_representative AS is_representative_version,
          df.presentation_count AS family_duplicate_count
        FROM slides s
        JOIN presentations p ON p.id = s.presentation_id
        {importance_join}
        LEFT JOIN presentation_versions pv ON pv.presentation_id = p.id
        LEFT JOIN deck_families df ON df.id = pv.deck_family_id
        {where_sql}
        ORDER BY
          COALESCE(si.importance_score, 0) DESC,
          COALESCE(s.reuse_count, 0) DESC,
          COALESCE(s.won_count, 0) DESC,
          p.filename,
          s.slide_index
        {limit_sql}
        """,
        params,
    )
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]


def _row_to_item(row: dict[str, object]) -> dict[str, object]:
    win_rate = row["win_rate"]
    return {
        "slide_id": _int_value(row["slide_id"]),
        "presentation": {
            "id": _int_value(row["presentation_id"]),
            "path": row["path"],
            "filename": row["filename"],
            "project_name": row["project_name"],
        },
        "page_number": _int_value(row["slide_index"]) + 1,
        "title": row["title"],
        "page_role": row["page_role"],
        "importance_score": row["importance_score"],
        "importance_reason": row["importance_reason"],
        "needs_visual": bool(row["needs_visual"]) if row["needs_visual"] is not None else None,
        "status": row["status"],
        "metadata": {
            "industry": row["industry"],
            "scenario": row["scenario"],
            "narrative_role": row["narrative_role"],
            "quality_rating": row["quality_rating"],
        },
        "business": {
            "reuse_count": _int_value(row["reuse_count"]),
            "won_count": _int_value(row["won_count"]),
            "lost_count": _int_value(row["lost_count"]),
            "win_rate": float(win_rate) if isinstance(win_rate, int | float) else None,
            "last_deal_outcome": row["last_deal_outcome"],
        },
        "version": {
            "deck_family_id": row["deck_family_id"],
            "version_role": row["version_role"],
            "is_representative_version": bool(row["is_representative_version"]) if row["is_representative_version"] is not None else None,
            "family_duplicate_count": row["family_duplicate_count"],
        },
    }


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(value)
    return default


def _empty_message(items: list[dict[str, object]]) -> str | None:
    if items:
        return None
    return "No key page insights yet. Run `ppt-lib enrich-decks --pending --limit 20` first."
