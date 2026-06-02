from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from ppt_lib.assets import normalize_text, normalized_text_hash
from ppt_lib.settings import Settings


class DeckInsightClient(Protocol):
    def summarize(self, prompt: str) -> str | dict[str, object] | Any:
        """Return a deck-level summary payload."""


@dataclass(frozen=True)
class VersionRecomputeResult:
    family_count: int
    presentation_count: int
    representative_count: int
    dry_run: bool
    changes: list[dict[str, object]]


@dataclass(frozen=True)
class DeckVersionStatus:
    family_count: int
    presentation_version_count: int
    representative_count: int
    insight_count: int
    slide_importance_count: int


@dataclass(frozen=True)
class DeckInsightRunResult:
    processed: int
    remaining: int
    warnings: list[str]


def recompute_deck_versions(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    commit: bool = True,
) -> VersionRecomputeResult:
    presentations = _load_presentations(conn)
    groups: dict[str, list[dict[str, object]]] = {}
    for item in presentations:
        family_key = _family_key(item)
        groups.setdefault(family_key, []).append(item | {"family_key": family_key})

    assignments: list[dict[str, object]] = []
    for family_key, group in groups.items():
        representative = max(group, key=_representative_sort_key)
        for item in group:
            version_info = _version_info(str(item["filename"]), _as_float(item.get("file_mtime")))
            presentation_id = _as_int(item["id"])
            assignments.append(
                {
                    "presentation_id": presentation_id,
                    "family_key": family_key,
                    "project_name": item.get("project_name"),
                    "family_title": _family_title(item),
                    "version_key": version_info["version_key"],
                    "version_role": version_info["version_role"],
                    "version_rank": version_info["version_rank"],
                    "version_date": version_info["version_date"],
                    "is_representative": presentation_id == _as_int(representative["id"]),
                    "confidence": _family_confidence(group, item),
                    "signals": {
                        "filename": item["filename"],
                        "normalized_stem": _normalized_deck_stem(str(item["filename"])),
                        "project_name": item.get("project_name"),
                        "first_slide_title": item.get("first_slide_title"),
                        "slide_count": item.get("slide_count"),
                        "file_mtime": item.get("file_mtime"),
                        "group_size": len(group),
                    },
                }
            )

    if not dry_run:
        _write_version_assignments(conn, assignments)
        if commit:
            conn.commit()

    return VersionRecomputeResult(
        family_count=len(groups),
        presentation_count=len(presentations),
        representative_count=sum(1 for item in assignments if item["is_representative"]),
        dry_run=dry_run,
        changes=assignments,
    )


def get_version_status(conn: sqlite3.Connection) -> DeckVersionStatus:
    return DeckVersionStatus(
        family_count=_count(conn, "deck_families"),
        presentation_version_count=_count(conn, "presentation_versions"),
        representative_count=int(conn.execute("SELECT COUNT(*) FROM presentation_versions WHERE is_representative = 1").fetchone()[0]),
        insight_count=_count(conn, "deck_insights"),
        slide_importance_count=_count(conn, "slide_importance"),
    )


def inspect_deck_family(conn: sqlite3.Connection, family_id: int) -> dict[str, object] | None:
    family = conn.execute(
        """
        SELECT id, family_key, project_name, title, representative_presentation_id, presentation_count
        FROM deck_families
        WHERE id = ?
        """,
        (family_id,),
    ).fetchone()
    if family is None:
        return None
    versions = conn.execute(
        """
        SELECT
          p.id, p.path, p.filename, p.slide_count, p.file_mtime,
          pv.version_key, pv.version_role, pv.version_rank, pv.version_date,
          pv.is_representative, pv.confidence
        FROM presentation_versions pv
        JOIN presentations p ON p.id = pv.presentation_id
        WHERE pv.deck_family_id = ?
        ORDER BY pv.is_representative DESC, pv.version_rank DESC, p.file_mtime DESC, p.filename
        """,
        (family_id,),
    ).fetchall()
    return {
        "family": {
            "id": int(family[0]),
            "family_key": family[1],
            "project_name": family[2],
            "title": family[3],
            "representative_presentation_id": family[4],
            "presentation_count": int(family[5] or 0),
        },
        "versions": [
            {
                "presentation_id": int(row[0]),
                "path": row[1],
                "filename": row[2],
                "slide_count": int(row[3] or 0),
                "file_mtime": float(row[4] or 0.0),
                "version_key": row[5],
                "version_role": row[6],
                "version_rank": int(row[7] or 0),
                "version_date": row[8],
                "is_representative": bool(row[9]),
                "confidence": float(row[10] or 0.0),
            }
            for row in versions
        ],
    }


def enrich_pending_decks(
    settings: Settings,
    *,
    limit: int | None = None,
    client: DeckInsightClient | None = None,
) -> DeckInsightRunResult:
    assert settings.db_path is not None
    from ppt_lib.db import connect, init_db

    conn = connect(settings.db_path)
    init_db(conn)
    rows = _load_pending_decks(conn, limit=limit)
    warnings: list[str] = []
    for row in rows:
        presentation_id = int(row[0])
        slides = _load_deck_slides(conn, presentation_id)
        summary_payload, summary_warnings = _summarize_deck(row, slides, client=client)
        warnings.extend(summary_warnings)
        _upsert_deck_insight(conn, presentation_id, "ok" if not summary_warnings else "fallback", summary_payload, summary_warnings)
        for slide in slides:
            importance = _slide_importance(slide, _as_int(row[3] or len(slides)))
            _upsert_slide_importance(conn, _as_int(slide["slide_id"]), importance)
    conn.commit()
    remaining = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM presentations p
            LEFT JOIN deck_insights di ON di.presentation_id = p.id
            WHERE di.id IS NULL OR di.status IN ('pending', 'failed')
            """
        ).fetchone()[0]
    )
    return DeckInsightRunResult(processed=len(rows), remaining=remaining, warnings=_dedupe(warnings))


def _load_presentations(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
          p.id, p.path, p.filename, p.project_name, p.slide_count, p.content_hash,
          p.file_size, p.file_mtime, s.title, s.text_content
        FROM presentations p
        LEFT JOIN slides s ON s.presentation_id = p.id AND s.slide_index = 0
        ORDER BY p.id
        """
    ).fetchall()
    return [
        {
            "id": int(row[0]),
            "path": row[1],
            "filename": row[2],
            "project_name": row[3],
            "slide_count": int(row[4] or 0),
            "content_hash": row[5],
            "file_size": int(row[6] or 0),
            "file_mtime": float(row[7] or 0.0),
            "first_slide_title": row[8],
            "first_slide_text": row[9],
        }
        for row in rows
    ]


def _write_version_assignments(conn: sqlite3.Connection, assignments: list[dict[str, object]]) -> None:
    now = _now_iso()
    family_ids: dict[str, int] = {}
    grouped_counts: dict[str, int] = {}
    representative_by_family: dict[str, int] = {}
    for item in assignments:
        family_key = str(item["family_key"])
        grouped_counts[family_key] = grouped_counts.get(family_key, 0) + 1
        if item["is_representative"]:
            representative_by_family[family_key] = _as_int(item["presentation_id"])

    for item in assignments:
        family_key = str(item["family_key"])
        if family_key not in family_ids:
            conn.execute(
                """
                INSERT INTO deck_families (
                  family_key, project_name, title, representative_presentation_id,
                  presentation_count, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(family_key) DO UPDATE SET
                  project_name=excluded.project_name,
                  title=excluded.title,
                  representative_presentation_id=excluded.representative_presentation_id,
                  presentation_count=excluded.presentation_count,
                  updated_at=excluded.updated_at
                """,
                (
                    family_key,
                    item.get("project_name"),
                    item.get("family_title"),
                    representative_by_family.get(family_key),
                    grouped_counts[family_key],
                    now,
                    now,
                ),
            )
            family_ids[family_key] = int(conn.execute("SELECT id FROM deck_families WHERE family_key = ?", (family_key,)).fetchone()[0])

        conn.execute(
            """
            INSERT INTO presentation_versions (
              presentation_id, deck_family_id, version_key, version_role, version_rank,
              version_date, is_representative, confidence, signals_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(presentation_id) DO UPDATE SET
              deck_family_id=excluded.deck_family_id,
              version_key=excluded.version_key,
              version_role=excluded.version_role,
              version_rank=excluded.version_rank,
              version_date=excluded.version_date,
              is_representative=excluded.is_representative,
              confidence=excluded.confidence,
              signals_json=excluded.signals_json,
              updated_at=excluded.updated_at
            """,
            (
                item["presentation_id"],
                family_ids[family_key],
                item.get("version_key"),
                item.get("version_role"),
                item.get("version_rank"),
                item.get("version_date"),
                int(bool(item.get("is_representative"))),
                item.get("confidence"),
                json.dumps(item.get("signals", {}), ensure_ascii=False),
                now,
                now,
            ),
        )


def _family_key(item: dict[str, object]) -> str:
    project = _compact_key(str(item.get("project_name") or Path(str(item.get("path") or "")).parent.name or "ungrouped"))
    stem = _normalized_deck_stem(str(item.get("filename") or "deck.pptx"))
    title = _compact_key(str(item.get("first_slide_title") or item.get("first_slide_text") or ""))
    base = stem or title or _compact_key(str(item.get("content_hash") or item.get("path") or "deck"))
    if title and len(title) > 6 and title != base:
        base = _common_prefix_key(base, title) or base
    digest = normalized_text_hash(f"{project}:{base}")[:8]
    return f"{project}:{base[:72]}:{digest}"


def _family_title(item: dict[str, object]) -> str:
    title = str(item.get("first_slide_title") or "").strip()
    if title:
        return title[:120]
    return _normalized_deck_stem(str(item.get("filename") or "deck.pptx")).replace("-", " ")[:120]


def _normalized_deck_stem(filename: str) -> str:
    stem = Path(filename).stem.lower()
    stem = re.sub(r"[\[\(（【][^\]\)）】]{0,30}[\]\)）】]", " ", stem)
    stem = re.sub(r"20\d{2}[-_.年]?\d{1,2}[-_.月]?\d{1,2}日?", " ", stem)
    stem = re.sub(r"(?<!\d)\d{8}(?!\d)", " ", stem)
    stem = re.sub(r"[_\-\s]*(v|版本|版)?\d{1,3}(\.\d+)?\b", " ", stem, flags=re.IGNORECASE)
    version_words = (
        r"final|draft|backup|old|new|rev\d+|终稿|定稿|初稿|草稿|备份|旧版|最新版|"
        r"汇报版|客户修改版|客户版|修改版|送审版"
    )
    stem = re.sub(f"({version_words})", " ", stem)
    stem = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", stem)
    return _compact_key(stem)


def _version_info(filename: str, file_mtime: float) -> dict[str, object]:
    stem = Path(filename).stem.lower()
    version_key = None
    version_number = 0
    version_match = re.search(r"(?:^|[_\-\s])(v\d+(?:\.\d+)?|\d{1,3}版|版本\d{1,3})(?:$|[_\-\s])", stem, re.IGNORECASE)
    if version_match:
        version_key = version_match.group(1)
        digits = re.findall(r"\d+", version_key)
        version_number = int(digits[-1]) if digits else 0
    date_value = _version_date(stem)
    role = "current"
    role_bonus = 500_000_000
    if re.search(r"final|终稿|定稿|最终|正式版", stem):
        role = "final"
        role_bonus = 1_000_000_000
        version_key = version_key or "final"
    elif re.search(r"汇报版|客户修改版|客户版|送审版|修改版", stem):
        role = "review"
        role_bonus = 800_000_000
    elif re.search(r"draft|初稿|草稿|备份|backup|旧版|old", stem):
        role = "draft"
        role_bonus = 100_000_000
    date_rank = int(date_value.replace("-", "")) if date_value else 0
    mtime_rank = int(file_mtime // 86_400)
    return {
        "version_key": version_key or date_value or role,
        "version_role": role,
        "version_rank": role_bonus + version_number * 1_000_000 + date_rank + mtime_rank,
        "version_date": date_value,
    }


def _version_date(text: str) -> str | None:
    match = re.search(r"(20\d{2})[-_.年]?(\d{1,2})[-_.月]?(\d{1,2})日?", text)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _representative_sort_key(item: dict[str, object]) -> tuple[int, float, int, int, str]:
    version_info = _version_info(str(item["filename"]), _as_float(item.get("file_mtime")))
    return (
        _as_int(version_info["version_rank"]),
        _as_float(item.get("file_mtime")),
        _as_int(item.get("slide_count")),
        _as_int(item.get("file_size")),
        str(item.get("path") or ""),
    )


def _family_confidence(group: list[dict[str, object]], item: dict[str, object]) -> float:
    confidence = 0.6
    if len(group) > 1:
        confidence += 0.2
    if item.get("project_name"):
        confidence += 0.1
    if item.get("first_slide_title"):
        confidence += 0.05
    return min(0.95, confidence)


def _compact_key(text: str) -> str:
    normalized = normalize_text(text).lower()
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", normalized)
    return normalized.strip("-") or "untitled"


def _common_prefix_key(left: str, right: str) -> str | None:
    left_parts = [part for part in left.split("-") if part]
    right_parts = [part for part in right.split("-") if part]
    common: list[str] = []
    for left_part, right_part in zip(left_parts, right_parts, strict=False):
        if left_part != right_part:
            break
        common.append(left_part)
    return "-".join(common) if len(common) >= 2 else None


def _load_pending_decks(conn: sqlite3.Connection, *, limit: int | None) -> list[sqlite3.Row]:
    query = """
        SELECT p.id, p.filename, p.project_name, p.slide_count
        FROM presentations p
        LEFT JOIN deck_insights di ON di.presentation_id = p.id
        WHERE di.id IS NULL OR di.status IN ('pending', 'failed')
        ORDER BY p.id
    """
    params: list[object] = []
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return conn.execute(query, params).fetchall()


def _load_deck_slides(conn: sqlite3.Connection, presentation_id: int) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, slide_index, title, text_content, metadata_json, screenshot_hash
        FROM slides
        WHERE presentation_id = ?
        ORDER BY slide_index
        """,
        (presentation_id,),
    ).fetchall()
    return [
        {
            "slide_id": int(row[0]),
            "slide_index": int(row[1]),
            "title": row[2],
            "text_content": row[3] or "",
            "metadata": _json_loads(row[4]),
            "screenshot_hash": row[5],
        }
        for row in rows
    ]


def _summarize_deck(
    presentation_row: sqlite3.Row,
    slides: list[dict[str, object]],
    *,
    client: DeckInsightClient | None,
) -> tuple[dict[str, object], list[str]]:
    filename = str(presentation_row[1])
    project_name = presentation_row[2]
    combined = "\n".join(str(slide.get("text_content") or "") for slide in slides[:12])
    if client is not None:
        try:
            payload = client.summarize(_deck_prompt(filename, project_name, combined))
            parsed = _parse_payload(payload)
            if parsed:
                return parsed, []
        except Exception as exc:
            return _fallback_deck_summary(filename, project_name, slides), [f"DECK_LM_UNAVAILABLE:{type(exc).__name__}:{exc}"]
    return _fallback_deck_summary(filename, project_name, slides), ["DECK_SUMMARY_FALLBACK_TEXT_MODE"]


def _deck_prompt(filename: str, project_name: object, combined_text: str) -> str:
    return (
        "请基于整份 PPT 的文本输出 JSON，字段包括 project, industry, scenario, deck_type, "
        "one_sentence_summary, key_topics, reusable_scenarios, section_outline。\n"
        f"Filename: {filename}\n"
        f"Project: {project_name or ''}\n"
        f"Slides text:\n{combined_text[:6000]}"
    )


def _fallback_deck_summary(filename: str, project_name: object, slides: list[dict[str, object]]) -> dict[str, object]:
    titles = [str(slide.get("title") or "").strip() for slide in slides if str(slide.get("title") or "").strip()]
    text = " ".join(" ".join(str(slide.get("text_content") or "").split()) for slide in slides[:8])
    return {
        "project": project_name or Path(filename).stem,
        "industry": "unknown",
        "scenario": "general",
        "deck_type": "unknown",
        "one_sentence_summary": _trim_text(text, 220) or f"{Path(filename).stem} 的 PPT 文本摘要暂不可用。",
        "key_topics": _keywords(text),
        "reusable_scenarios": [],
        "section_outline": titles[:10],
    }


def _slide_importance(slide: dict[str, object], slide_count: int) -> dict[str, object]:
    index = _as_int(slide["slide_index"])
    text = str(slide.get("text_content") or "")
    compact = normalize_text(text)
    role = _page_role(compact, index, slide_count)
    score = 0.35
    reasons: list[str] = []
    if index == 0:
        score += 0.35
        reasons.append("cover")
    if role in {"problem", "solution", "architecture", "case", "roi", "cta"}:
        score += 0.25
        reasons.append(role)
    if len(compact) < 80 and slide.get("screenshot_hash"):
        score += 0.15
        reasons.append("low_text_visual_risk")
    if any(token in compact for token in ("架构", "流程", "图", "roi", "价值", "案例", "方案")):
        score += 0.15
        reasons.append("business_reuse_signal")
    return {
        "importance_score": min(1.0, score),
        "importance_reason": ",".join(reasons) or "baseline",
        "page_role": role,
        "needs_visual": len(compact) < 80 or role in {"architecture", "case", "roi"},
        "status": "candidate" if score >= 0.6 else "low_priority",
    }


def _page_role(text: str, index: int, slide_count: int) -> str:
    if index == 0:
        return "cover"
    if any(token in text for token in ("痛点", "问题", "挑战", "现状")):
        return "problem"
    if any(token in text for token in ("方案", "解决", "能力", "建设")):
        return "solution"
    if any(token in text for token in ("架构", "流程", "蓝图", "体系")):
        return "architecture"
    if any(token in text for token in ("案例", "客户", "实践")):
        return "case"
    if any(token in text for token in ("roi", "收益", "价值", "预算", "成本")):
        return "roi"
    if any(token in text for token in ("下一步", "共创", "联系", "行动")) or index >= max(0, slide_count - 2):
        return "cta"
    return "content"


def _upsert_deck_insight(
    conn: sqlite3.Connection,
    presentation_id: int,
    status: str,
    summary_payload: dict[str, object],
    warnings: list[str],
) -> None:
    conn.execute(
        """
        INSERT INTO deck_insights (presentation_id, status, summary_json, warnings_json, generated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(presentation_id) DO UPDATE SET
          status=excluded.status,
          summary_json=excluded.summary_json,
          warnings_json=excluded.warnings_json,
          generated_at=excluded.generated_at
        """,
        (
            presentation_id,
            status,
            json.dumps(summary_payload, ensure_ascii=False),
            json.dumps(warnings, ensure_ascii=False),
            _now_iso(),
        ),
    )


def _upsert_slide_importance(conn: sqlite3.Connection, slide_id: int, importance: dict[str, object]) -> None:
    conn.execute(
        """
        INSERT INTO slide_importance (
          slide_id, importance_score, importance_reason, page_role, needs_visual, status, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(slide_id) DO UPDATE SET
          importance_score=excluded.importance_score,
          importance_reason=excluded.importance_reason,
          page_role=excluded.page_role,
          needs_visual=excluded.needs_visual,
          status=excluded.status,
          updated_at=excluded.updated_at
        """,
        (
            slide_id,
            importance["importance_score"],
            importance["importance_reason"],
            importance["page_role"],
            int(bool(importance["needs_visual"])),
            importance["status"],
            _now_iso(),
        ),
    )


def _parse_payload(payload: object) -> dict[str, object]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _json_loads(raw: object) -> dict[str, object]:
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[\u4e00-\u9fff]{2,6}|[a-zA-Z][a-zA-Z0-9_-]{2,}", text)
    seen: set[str] = set()
    result: list[str] = []
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        result.append(word)
        if len(result) >= 12:
            break
    return result


def _trim_text(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1].rstrip() + "…"


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _as_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str | bytes | bytearray):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str | bytes | bytearray):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
