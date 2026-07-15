from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, TypedDict

import numpy as np

from ppt_lib.db import connect, init_db
from ppt_lib.discovery import is_cache_path
from ppt_lib.embedding import EmbeddingProvider, build_embedding_provider
from ppt_lib.labels import INDUSTRY_LABELS, SCENARIO_LABELS
from ppt_lib.settings import Settings


class SearchError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SearchOptions:
    top_k: int = 5
    threshold: float = 0.5
    cluster: bool = False
    include_assembled: bool = False
    dedupe_lineage: bool = False
    ranking: Literal["classic", "business"] = "classic"
    narrative_role: str | None = None
    context: str | None = None
    include_cache: bool = False
    include_duplicates: bool = False
    include_versions: bool = False
    scope: Literal["all", "active"] = "all"


@dataclass(frozen=True)
class SearchIndexStats:
    configured_dimensions: int
    total_embeddings: int
    searchable_embeddings: int
    skipped_embeddings: int
    dimension_counts: dict[int, int]


@dataclass(frozen=True)
class SearchResult:
    slide_id: int
    score: float
    title: str | None
    text_summary: str
    source_file: Path
    page_number: int
    screenshot_path: Path | None
    source: str
    confidence: float | None
    metadata: dict[str, object]
    cluster_id: int | None = None
    cluster_label: str | None = None
    embedding: np.ndarray | None = None
    text_content: str = ""
    score_breakdown: dict[str, float | None] | None = None
    duplicate_count: int | None = None
    canonical_slide_id: int | None = None
    deck_family_id: int | None = None
    version_role: str | None = None
    is_representative_version: bool | None = None
    family_duplicate_count: int | None = None


class _SearchRow(TypedDict):
    slide_id: int
    title: str | None
    text_content: str
    embedding: np.ndarray
    screenshot_hash: str | None
    source: str
    metadata: dict[str, object]
    slide_index: int
    source_file: Path
    screenshot_path: Path | None
    raw_text: str | None
    ai_summary: str | None
    visual_summary: str | None
    canonical_slide_id: int | None
    duplicate_count: int | None
    deck_family_id: int | None
    version_role: str | None
    is_representative_version: bool | None
    family_duplicate_count: int | None
    importance_score: float | None
    importance_reason: str | None
    page_role: str | None
    needs_visual: bool | None
    importance_status: str | None


_SEMANTIC_SCORE_WEIGHT = 0.7
_LEXICAL_SCORE_WEIGHT = 0.3
_LOW_OVERLAP_THRESHOLD = 0.05
_NO_OVERLAP_PENALTY = 0.12
_LOW_OVERLAP_PENALTY = 0.06
_BUSINESS_SCORE_WEIGHT = 0.15
_BUSINESS_CONFIDENCE_THRESHOLD = 5
_CONTEXT_MATCH_BOOST = 0.05


def search(
    query: str,
    options: SearchOptions,
    settings: Settings,
    *,
    conn: sqlite3.Connection | None = None,
    rows: list[_SearchRow] | None = None,
    provider: EmbeddingProvider | None = None,
) -> list[SearchResult]:
    if not query.strip():
        raise SearchError("Search query must not be empty.", code="SEARCH_EMPTY_QUERY")

    close_conn = False
    if conn is None:
        assert settings.db_path is not None
        conn = connect(settings.db_path)
        init_db(conn)
        close_conn = True

    try:
        rows = rows if rows is not None else load_search_rows(
            conn,
            settings.embedding_dimensions,
            include_assembled=options.include_assembled,
            dedupe_lineage=options.dedupe_lineage,
            narrative_role=options.narrative_role,
            include_cache=options.include_cache,
            include_duplicates=options.include_duplicates,
            include_versions=options.include_versions,
            scope=options.scope,
        )
        if not rows:
            if options.scope == "all":
                _raise_if_only_dimension_mismatch(conn, settings.embedding_dimensions)
            return []

        provider = provider or build_embedding_provider(settings)
        query_vector = provider.encode(query)
        results = _rank_rows(query, rows, query_vector, options)
        if options.cluster:
            return cluster_results(results)
        return results
    finally:
        if close_conn:
            conn.close()


def get_search_index_stats(settings: Settings) -> SearchIndexStats:
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    rows = conn.execute("SELECT embedding FROM slides WHERE embedding IS NOT NULL").fetchall()
    dimension_counts: dict[int, int] = {}
    for row in rows:
        dimensions = int(np.frombuffer(row[0], dtype=np.float32).shape[0])
        dimension_counts[dimensions] = dimension_counts.get(dimensions, 0) + 1
    searchable = dimension_counts.get(settings.embedding_dimensions, 0)
    total = sum(dimension_counts.values())
    return SearchIndexStats(
        configured_dimensions=settings.embedding_dimensions,
        total_embeddings=total,
        searchable_embeddings=searchable,
        skipped_embeddings=total - searchable,
        dimension_counts=dimension_counts,
    )


def cosine_scores(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    query = np.asarray(query, dtype=np.float32)
    matrix_norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    query_norm = float(np.linalg.norm(query))
    matrix_norm[matrix_norm == 0] = 1.0
    if query_norm == 0:
        query_norm = 1.0
    return (matrix / matrix_norm) @ (query / query_norm)


def cluster_results(results: list[SearchResult], threshold: float = 0.3) -> list[SearchResult]:
    clustered: list[SearchResult] = []
    centroids: list[np.ndarray] = []
    for result in results:
        vector = result.embedding
        if vector is None:
            cluster_id = len(centroids)
            centroids.append(np.zeros(1, dtype=np.float32))
            clustered.append(replace(result, cluster_id=cluster_id, cluster_label=f"cluster-{cluster_id}"))
            continue
        assigned: int | None = None
        for idx, centroid in enumerate(centroids):
            if centroid.shape == vector.shape and float(cosine_scores(np.asarray([centroid]), vector)[0]) >= 1 - threshold:
                assigned = idx
                break
        if assigned is None:
            assigned = len(centroids)
            centroids.append(vector)
        clustered.append(replace(result, cluster_id=assigned, cluster_label=f"cluster-{assigned}"))
    return clustered


def load_search_rows(
    conn: sqlite3.Connection,
    dimensions: int,
    *,
    include_assembled: bool = False,
    dedupe_lineage: bool = False,
    narrative_role: str | None = None,
    include_cache: bool = False,
    include_duplicates: bool = False,
    include_versions: bool = False,
    scope: Literal["all", "active"] = "all",
) -> list[_SearchRow]:
    slide_columns = _table_columns(conn, "slides")
    has_raw_text = "raw_text" in slide_columns
    has_ai_summary = "ai_summary" in slide_columns
    has_visual_summary = "visual_summary" in slide_columns
    has_canonical = "canonical_slide_id" in slide_columns
    has_screenshot_table = _table_exists(conn, "screenshots")
    has_versions = _table_exists(conn, "presentation_versions") and _table_exists(conn, "deck_families")
    has_slide_importance = _table_exists(conn, "slide_importance")

    select_parts: list[tuple[str, str]] = [
        ("s.id", "id"),
        ("s.title", "title"),
        ("s.text_content", "text_content"),
        ("s.embedding", "embedding"),
        ("s.screenshot_hash", "screenshot_hash"),
        ("s.source", "source"),
        ("s.metadata_json", "metadata_json"),
        ("s.slide_index", "slide_index"),
        ("p.path", "path"),
        ("s.origin_type", "origin_type"),
        ("s.industry", "industry"),
        ("s.scenario", "scenario"),
        ("s.narrative_role", "narrative_role"),
        ("s.win_rate", "win_rate"),
        ("s.won_count", "won_count"),
        ("s.lost_count", "lost_count"),
        ("s.reuse_count", "reuse_count"),
        ("s.last_deal_outcome", "last_deal_outcome"),
    ]
    if has_raw_text:
        select_parts.append(("s.raw_text", "raw_text"))
    if has_ai_summary:
        select_parts.append(("s.ai_summary", "ai_summary"))
    if has_visual_summary:
        select_parts.append(("s.visual_summary", "visual_summary"))
    if has_canonical:
        select_parts.append(("s.canonical_slide_id", "canonical_slide_id"))

    select_fields = ", ".join(expr for expr, _ in select_parts)

    screenshot_join = "LEFT JOIN screenshots sc ON sc.hash = s.screenshot_hash" if has_screenshot_table else ""
    select_fields += ", sc.file_path AS screenshot_path" if has_screenshot_table else ", NULL AS screenshot_path"
    version_join = ""
    if has_versions:
        version_join = (
            "LEFT JOIN presentation_versions pv ON pv.presentation_id = p.id "
            "LEFT JOIN deck_families df ON df.id = pv.deck_family_id"
        )
        select_fields += (
            ", pv.deck_family_id AS deck_family_id, pv.version_role AS version_role, "
            "pv.is_representative AS is_representative_version, df.presentation_count AS family_duplicate_count"
        )
    else:
        select_fields += ", NULL AS deck_family_id, NULL AS version_role, NULL AS is_representative_version, NULL AS family_duplicate_count"
    importance_join = ""
    if has_slide_importance:
        importance_join = "LEFT JOIN slide_importance si ON si.slide_id = s.id"
        select_fields += (
            ", si.importance_score AS importance_score, si.importance_reason AS importance_reason, "
            "si.page_role AS page_role, si.needs_visual AS needs_visual, si.status AS importance_status"
        )
    else:
        select_fields += (
            ", NULL AS importance_score, NULL AS importance_reason, NULL AS page_role, "
            "NULL AS needs_visual, NULL AS importance_status"
        )

    narrative_filter = ""
    params: list[object] = [int(include_assembled), int(dedupe_lineage)]
    if narrative_role is not None:
        narrative_filter = "AND s.narrative_role = ?"
        params.append(narrative_role)

    canonical_filter = ""
    if has_canonical and not include_duplicates:
        canonical_filter = "AND (s.canonical_slide_id IS NULL OR s.canonical_slide_id = s.id)"

    version_filter = ""
    if has_versions and not include_versions:
        version_filter = "AND (pv.id IS NULL OR pv.is_representative = 1)"

    active_filter = ""
    if scope == "active":
        active_filter = """
          AND EXISTS (
            SELECT 1
            FROM presentation_source_links psl
            JOIN library_sources ls ON ls.id = psl.library_source_id
            WHERE psl.presentation_id = p.id AND ls.is_active = 1
          )
        """

    rows = conn.execute(
        f"""
        SELECT
          {select_fields}
        FROM slides s
        JOIN presentations p ON p.id = s.presentation_id
        {screenshot_join}
        {version_join}
        {importance_join}
        WHERE s.embedding IS NOT NULL
          AND (? OR s.origin_type != 'assembled_output')
          AND (? = 0 OR s.origin_type != 'assembled_output')
          {canonical_filter}
          {version_filter}
          {narrative_filter}
          {active_filter}
        """,
        params,
    ).fetchall()

    aliases = [
        alias for _, alias in select_parts
    ] + [
        "screenshot_path",
        "deck_family_id",
        "version_role",
        "is_representative_version",
        "family_duplicate_count",
        "importance_score",
        "importance_reason",
        "page_role",
        "needs_visual",
        "importance_status",
    ]
    alias_to_index = {alias: index for index, alias in enumerate(aliases)}

    canonical_ids: set[int] = set()
    loaded: list[_SearchRow] = []
    for row in rows:
        values = {alias: row[index] for alias, index in alias_to_index.items()}
        source_file = Path(values.get("path") or "")
        if not include_cache and is_cache_path(source_file):
            continue
        raw_embedding = values.get("embedding")
        if raw_embedding is None:
            continue
        embedding = np.frombuffer(raw_embedding, dtype=np.float32).copy()
        if embedding.shape != (dimensions,):
            continue

        canonical_slide_id = values.get("canonical_slide_id") if has_canonical else None
        if canonical_slide_id is not None:
            canonical_ids.add(int(canonical_slide_id))

        raw_text = values.get("raw_text") if has_raw_text else None
        ai_summary = values.get("ai_summary") if has_ai_summary else None
        visual_summary = values.get("visual_summary") if has_visual_summary else None

        screenshot_path = values.get("screenshot_path")
        slide_index = values.get("slide_index")
        source = values.get("source")
        metadata_json = values.get("metadata_json")
        origin_type = values.get("origin_type")
        industry = values.get("industry")
        scenario = values.get("scenario")
        narrative = values.get("narrative_role")
        win_rate = values.get("win_rate")
        won_count = values.get("won_count")
        lost_count = values.get("lost_count")
        reuse_count = values.get("reuse_count")
        last_deal_outcome = values.get("last_deal_outcome")
        needs_visual_value = values.get("needs_visual")

        slide_id = values.get("id")
        if slide_id is None:
            continue
        optional_canonical_slide_id = _optional_int(canonical_slide_id)

        loaded.append(
            {
                "slide_id": int(slide_id),
                "title": values.get("title"),
                "text_content": values.get("text_content") or "",
                "embedding": embedding,
                "screenshot_hash": values.get("screenshot_hash"),
                "source": source if isinstance(source, str) else "text_extraction",
                "metadata": _load_metadata(metadata_json if isinstance(metadata_json, str) or metadata_json is None else None)
                | {
                    "origin_type": origin_type,
                    "industry": industry,
                    "scenario": scenario,
                    "narrative_role": narrative,
                    "win_rate": win_rate,
                    "won_count": int(won_count or 0),
                    "lost_count": int(lost_count or 0),
                    "reuse_count": int(reuse_count or 0),
                    "last_deal_outcome": last_deal_outcome,
                    "importance_score": values.get("importance_score"),
                    "importance_reason": values.get("importance_reason"),
                    "page_role": values.get("page_role"),
                    "needs_visual": _optional_bool(needs_visual_value),
                    "importance_status": values.get("importance_status"),
                },
                "slide_index": int(slide_index or 0),
                "source_file": source_file,
                "screenshot_path": Path(screenshot_path) if screenshot_path else None,
                "raw_text": raw_text if isinstance(raw_text, str) else None,
                "ai_summary": ai_summary if isinstance(ai_summary, str) else None,
                "visual_summary": visual_summary if isinstance(visual_summary, str) else None,
                "canonical_slide_id": optional_canonical_slide_id,
                "duplicate_count": None,
                "deck_family_id": _optional_int(values.get("deck_family_id")),
                "version_role": values.get("version_role") if isinstance(values.get("version_role"), str) else None,
                "is_representative_version": _optional_bool(values.get("is_representative_version")),
                "family_duplicate_count": _optional_int(values.get("family_duplicate_count")),
                "importance_score": values.get("importance_score") if isinstance(values.get("importance_score"), int | float) else None,
                "importance_reason": values.get("importance_reason") if isinstance(values.get("importance_reason"), str) else None,
                "page_role": values.get("page_role") if isinstance(values.get("page_role"), str) else None,
                "needs_visual": _optional_bool(needs_visual_value),
                "importance_status": values.get("importance_status") if isinstance(values.get("importance_status"), str) else None,
            }
        )

    if has_canonical:
        duplicate_counts = _load_duplicate_counts(conn, canonical_ids)
        for row in loaded:
            canonical = row.get("canonical_slide_id")
            if canonical is None:
                continue
            row["duplicate_count"] = duplicate_counts.get(int(canonical))

    return loaded


def _rank_rows(query: str, rows: list[_SearchRow], query_vector: np.ndarray, options: SearchOptions) -> list[SearchResult]:
    matrix: np.ndarray = np.vstack([row["embedding"] for row in rows])
    semantic_scores = cosine_scores(matrix, query_vector)
    context_hints = _parse_context(options.context) if options.context and options.ranking == "business" else None
    ranked = sorted(
        [
            (score, lexical_score, semantic_score, business_score, context_score, row)
            for semantic_score, row in zip(semantic_scores.tolist(), rows, strict=True)
            if semantic_score >= options.threshold
            for lexical_score in [_lexical_score(query, row)]
            for hybrid_score in [_hybrid_score(float(semantic_score), lexical_score)]
            for business_score in [_business_score(row) if options.ranking == "business" else None]
            for context_score in [_context_score(row, context_hints) if context_hints else None]
            for score in [_final_score(hybrid_score, business_score, context_score)]
            if score >= options.threshold
        ],
        key=lambda item: (item[0], item[1], item[2], item[3] or 0),
        reverse=True,
    )[: options.top_k]
    return [
        _row_to_result(
            row,
            score,
            score_breakdown={
                "semantic_score": float(semantic_score),
                "lexical_score": float(lexical_score_value),
                "business_score": business_score,
                "context_score": context_score,
            },
        )
        for score, lexical_score_value, semantic_score, business_score, context_score, row in ranked
    ]


def _hybrid_score(semantic_score: float, lexical_score: float) -> float:
    if lexical_score == 0:
        low_overlap_penalty = _NO_OVERLAP_PENALTY
    elif lexical_score < _LOW_OVERLAP_THRESHOLD:
        low_overlap_penalty = _LOW_OVERLAP_PENALTY
    else:
        low_overlap_penalty = 0.0
    blended_score = (_SEMANTIC_SCORE_WEIGHT * semantic_score) + (_LEXICAL_SCORE_WEIGHT * lexical_score)
    return max(0.0, min(1.0, blended_score - low_overlap_penalty))


def _business_score(row: _SearchRow) -> float | None:
    metadata = row["metadata"]
    win_rate = metadata.get("win_rate") if isinstance(metadata, dict) else None
    won_count = metadata.get("won_count") if isinstance(metadata, dict) else None
    lost_count = metadata.get("lost_count") if isinstance(metadata, dict) else None
    reuse_count = metadata.get("reuse_count") if isinstance(metadata, dict) else None
    if not isinstance(win_rate, int | float):
        return None
    won = int(won_count) if isinstance(won_count, int | float) else 0
    lost = int(lost_count) if isinstance(lost_count, int | float) else 0
    reuse = int(reuse_count) if isinstance(reuse_count, int | float) else 0
    total = won + lost
    if total <= 0:
        return None
    confidence = min(1.0, total / _BUSINESS_CONFIDENCE_THRESHOLD)
    win_rate_boost = float(win_rate) * confidence * _BUSINESS_SCORE_WEIGHT
    reuse_boost = min(0.1, reuse * 0.01)
    return win_rate_boost + reuse_boost


def _final_score(hybrid_score: float, business_score: float | None, context_score: float | None = None) -> float:
    total = hybrid_score
    if business_score is not None:
        total += business_score
    if context_score is not None:
        total += context_score
    return max(0.0, min(1.0, total))


@dataclass(frozen=True)
class _ContextHints:
    """Parsed context hints: industries and scenarios extracted from free-text context."""
    industries: frozenset[str]
    scenarios: frozenset[str]


# Mapping from Chinese keywords / aliases to canonical labels
_INDUSTRY_ALIASES: dict[str, str] = {
    "零售": "retail", "快消": "fmcg", "美妆": "beauty", "时尚": "fashion",
    "服装": "fashion", "鞋服": "fashion", "制造": "manufacturing", "制造业": "manufacturing",
    "医疗": "healthcare", "健康": "healthcare", "教育": "education",
    "金融": "finance", "银行": "finance", "保险": "finance",
    "地产": "real_estate", "房地产": "real_estate",
    "汽车": "automotive", "车企": "automotive",
    "科技": "technology", "tech": "technology", "it": "technology",
    "媒体": "media", "传媒": "media",
    "物流": "logistics", "供应链": "logistics",
    "能源": "energy", "电力": "energy",
    "政府": "government", "政务": "government",
}

_SCENARIO_ALIASES: dict[str, str] = {
    "pitch": "pitch", "售前": "pitch", "拜访": "pitch",
    "proposal": "proposal", "方案": "proposal", "投标": "proposal", "标书": "proposal",
    "案例": "case_study", "case": "case_study",
    "培训": "training", "赋能": "training",
    "汇报": "internal_review", "内部": "internal_review", "review": "internal_review",
    "demo": "product_demo", "演示": "product_demo",
    "战略": "strategy", "规划": "strategy",
    "方法论": "methodology",
}


def _parse_context(context: str) -> _ContextHints | None:
    """Parse free-text context into industry/scenario hints via keyword matching."""
    if not context or not context.strip():
        return None
    text = context.lower().strip()
    industries: set[str] = set()
    scenarios: set[str] = set()

    # Direct label match
    for label in INDUSTRY_LABELS:
        if label in text:
            industries.add(label)
    for label in SCENARIO_LABELS:
        if label in text:
            scenarios.add(label)

    # Alias match
    for alias, canonical in _INDUSTRY_ALIASES.items():
        if alias in text:
            industries.add(canonical)
    for alias, canonical in _SCENARIO_ALIASES.items():
        if alias in text:
            scenarios.add(canonical)

    if not industries and not scenarios:
        return None
    return _ContextHints(industries=frozenset(industries), scenarios=frozenset(scenarios))


def _context_score(row: _SearchRow, hints: _ContextHints | None) -> float | None:
    """Score a row based on context hints. Returns boost or None if no context."""
    if hints is None:
        return None
    metadata = row["metadata"]
    if not isinstance(metadata, dict):
        return 0.0
    industry = metadata.get("industry")
    scenario = metadata.get("scenario")
    boost = 0.0
    if industry and industry in hints.industries:
        boost += _CONTEXT_MATCH_BOOST
    if scenario and scenario in hints.scenarios:
        boost += _CONTEXT_MATCH_BOOST
    return boost if boost > 0 else 0.0


def _row_to_result(row: _SearchRow, score: float, *, score_breakdown: dict[str, float | None] | None = None) -> SearchResult:
    metadata = row["metadata"]
    confidence = metadata.get("confidence") if isinstance(metadata, dict) else None
    return SearchResult(
        slide_id=int(row["slide_id"]),
        score=float(score),
        title=_normalize_title(row["title"], row["source_file"], int(row["slide_index"])),
        text_summary=_select_readable_summary(row),
        source_file=row["source_file"],
        page_number=int(row["slide_index"]) + 1,
        screenshot_path=row["screenshot_path"],
        source=str(row["source"]),
        confidence=float(confidence) if isinstance(confidence, int | float) else None,
        metadata=metadata if isinstance(metadata, dict) else {},
        embedding=row["embedding"],
        text_content=str(row["text_content"]),
        score_breakdown=score_breakdown,
        duplicate_count=row.get("duplicate_count"),
        canonical_slide_id=row.get("canonical_slide_id"),
        deck_family_id=row.get("deck_family_id"),
        version_role=row.get("version_role"),
        is_representative_version=row.get("is_representative_version"),
        family_duplicate_count=row.get("family_duplicate_count"),
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in columns}


def _load_duplicate_counts(conn: sqlite3.Connection, canonical_ids: set[int]) -> dict[int, int]:
    if not canonical_ids:
        return {}
    ids = sorted(canonical_ids)
    placeholders = ",".join("?" * len(ids))

    if _table_exists(conn, "slide_duplicate_members") and _table_exists(conn, "duplicate_groups"):
        rows = conn.execute(
            "SELECT dg.canonical_slide_id, COUNT(DISTINCT m.slide_id), "
            "MAX(CASE WHEN m.slide_id = dg.canonical_slide_id THEN 1 ELSE 0 END) "
            "FROM duplicate_groups dg "
            "LEFT JOIN slide_duplicate_members m ON m.duplicate_group_id = dg.id "
            f"WHERE dg.canonical_slide_id IN ({placeholders}) "
            "GROUP BY dg.canonical_slide_id",
            ids,
        ).fetchall()
        if rows:
            return {
                int(row[0]): int(row[1]) + (0 if int(row[2] or 0) else 1)
                for row in rows
            }

    if _table_exists(conn, "slides"):
        rows = conn.execute(
            f"SELECT canonical_slide_id, COUNT(*) FROM slides WHERE canonical_slide_id IN ({placeholders}) GROUP BY canonical_slide_id",
            ids,
        ).fetchall()
        return {int(row[0]): int(row[1]) for row in rows if row[0] is not None}
    return {}


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str | bytes | bytearray | float):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes"}
    return None


def _select_readable_summary(row: _SearchRow) -> str:
    for key in ("ai_summary", "visual_summary", "raw_text", "text_content"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return _summarize(value)
    return _summarize(str(row.get("text_content", "")))


def _normalize_title(title: str | None, source_file: Path, page_index: int) -> str:
    if title and title.strip() and _is_effective_title(title):
        return title
    return f"{source_file.stem} · P{page_index + 1}"


def _is_effective_title(title: str) -> bool:
    normalized = title.strip().lower()
    if not normalized:
        return False
    untitled = {"untitled", "untitled slide", "未命名", "无标题", "暂无标题"}
    return normalized not in untitled


def _load_metadata(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _summarize(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _raise_if_only_dimension_mismatch(conn: sqlite3.Connection, dimensions: int) -> None:
    rows = conn.execute("SELECT embedding FROM slides WHERE embedding IS NOT NULL").fetchall()
    if not rows:
        return
    dimension_counts: dict[int, int] = {}
    for row in rows:
        row_dimensions = int(np.frombuffer(row[0], dtype=np.float32).shape[0])
        dimension_counts[row_dimensions] = dimension_counts.get(row_dimensions, 0) + 1
    if dimension_counts.get(dimensions, 0) > 0:
        return
    found = ", ".join(f"{key}d={value}" for key, value in sorted(dimension_counts.items()))
    raise SearchError(
        f"No searchable embeddings match configured dimension {dimensions}. Found indexed dimensions: {found}.",
        code="SEARCH_EMBEDDING_DIMENSION_MISMATCH",
    )


def _lexical_score(query: str, row: _SearchRow) -> float:
    terms = _query_terms(query)
    if not terms:
        return 0.0
    title = row["title"] or ""
    source_name = row["source_file"].name
    body = row["text_content"] or ""
    title_compact = _compact_text(title)
    source_compact = _compact_text(source_name)
    body_compact = _compact_text(body)
    title_tokens = _latin_tokens(title)
    source_tokens = _latin_tokens(source_name)
    body_tokens = _latin_tokens(body)

    matched_weight = 0.0
    total_weight = 0.0
    for term in terms:
        weight = 1.5 if len(term) >= 4 else 1.0
        total_weight += weight
        if _is_latin_term(term):
            if term in title_tokens:
                matched_weight += weight * 2.0
            elif term in source_tokens:
                matched_weight += weight * 1.5
            elif term in body_tokens:
                matched_weight += weight
        else:
            if term in title_compact:
                matched_weight += weight * 2.0
            elif term in source_compact:
                matched_weight += weight * 1.5
            elif term in body_compact:
                matched_weight += weight
    if total_weight == 0:
        return 0.0
    return min(1.0, matched_weight / total_weight)


def _query_terms(query: str) -> set[str]:
    normalized = query.lower()
    terms = {term for term in re.findall(r"[a-z0-9]+", normalized) if len(term) >= 2}
    for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized):
        if len(sequence) < 2:
            continue
        terms.add(sequence)
        for size in (2, 3, 4):
            if len(sequence) < size:
                continue
            terms.update(sequence[index : index + size] for index in range(len(sequence) - size + 1))
    stop_terms = {
        "\u4e00\u4e2a",
        "\u4e00\u9875",
        "\u627e\u4e00",
        "\u9700\u8981",
        "\u8bf4\u660e",
        "\u7528\u4e8e",
        "\u9875\u9762",
    }
    return {term for term in terms if term not in stop_terms}


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _latin_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _is_latin_term(term: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+", term))
