from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ppt_lib.embedding import EmbeddingProviderError
from ppt_lib.searcher import SearchOptions, SearchResult, load_search_rows, search
from ppt_lib.settings import Settings


class EvaluationManifestError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvaluationQuery:
    id: str
    query: str
    expected_slide_ids: list[int] = field(default_factory=list)
    expected_source_keywords: list[str] = field(default_factory=list)
    expected_title_keywords: list[str] = field(default_factory=list)
    expected_file_keywords: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass(frozen=True)
class EvaluationManifest:
    version: str
    queries: list[EvaluationQuery]
    thresholds: list[float]


@dataclass(frozen=True)
class QueryEvaluationResult:
    id: str
    query: str
    passed: bool
    rank: int | None
    recall_at_5: float
    recall_at_10: float
    mrr: float
    matched_by: str | None
    failure_reason: str | None
    result_count: int
    top_results: list[dict[str, object]]


@dataclass(frozen=True)
class SearchEvaluationSummary:
    total_queries: int
    passed_query_count: int
    failed_query_count: int
    recall_at_5: float
    recall_at_10: float
    mrr: float
    target_met: bool
    quality_status: str


@dataclass(frozen=True)
class SearchEvaluationReport:
    manifest_version: str
    summary: SearchEvaluationSummary
    query_results: list[QueryEvaluationResult]


def load_evaluation_manifest(path: Path) -> EvaluationManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationManifestError(f"Cannot read evaluation manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvaluationManifestError(f"Invalid evaluation manifest JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise EvaluationManifestError("Evaluation manifest must be a JSON object.")

    raw_queries = raw.get("queries")
    if not isinstance(raw_queries, list) or not raw_queries:
        raise EvaluationManifestError("Evaluation manifest must contain a non-empty queries array.")

    queries = [_parse_query(item) for item in raw_queries]
    query_ids = [item.id for item in queries]
    if len(set(query_ids)) != len(query_ids):
        raise EvaluationManifestError("Evaluation manifest query ids must be unique.")

    thresholds = _parse_thresholds(raw.get("thresholds", [0.0, 0.2, 0.35, 0.5, 0.65]))
    return EvaluationManifest(
        version=str(raw.get("version", "1.0")),
        queries=queries,
        thresholds=thresholds,
    )


def evaluate_search_manifest(
    manifest: EvaluationManifest,
    settings: Settings,
    *,
    top_k: int = 10,
    threshold: float = 0.0,
    target_recall_at_10: float = 0.8,
    conn: sqlite3.Connection | None = None,
) -> SearchEvaluationReport:
    if top_k <= 0:
        raise EvaluationManifestError("top_k must be greater than 0.")
    if threshold < 0.0 or threshold > 1.0:
        raise EvaluationManifestError("threshold must be between 0.0 and 1.0.")

    close_conn = False
    if conn is None:
        assert settings.db_path is not None
        from ppt_lib.db import connect, init_db

        conn = connect(settings.db_path)
        init_db(conn)
        close_conn = True
    try:
        rows = load_search_rows(conn, settings.embedding_dimensions)
        query_results = _evaluate_queries(manifest.queries, settings, rows, top_k=top_k, threshold=threshold, conn=conn)
        return SearchEvaluationReport(
            manifest_version=manifest.version,
            summary=summarize_evaluation(query_results, target_recall_at_10=target_recall_at_10),
            query_results=query_results,
        )
    finally:
        if close_conn:
            conn.close()


def calibrate_search_thresholds(
    manifest: EvaluationManifest,
    settings: Settings,
    *,
    top_k: int = 10,
    target_recall_at_10: float = 0.8,
) -> dict[str, object]:
    assert settings.db_path is not None
    from ppt_lib.db import connect, init_db

    conn = connect(settings.db_path)
    init_db(conn)
    try:
        rows = load_search_rows(conn, settings.embedding_dimensions)
        threshold_reports: list[tuple[float, SearchEvaluationSummary]] = []
        full_reports: list[dict[str, object]] = []
        for threshold in manifest.thresholds:
            query_results = [
                score_query_results(
                    item,
                    search(
                        item.query,
                        SearchOptions(top_k=top_k, threshold=threshold),
                        settings,
                        conn=conn,
                        rows=rows,
                    ),
                    top_k=top_k,
                )
                for item in manifest.queries
            ]
            summary = summarize_evaluation(query_results, target_recall_at_10=target_recall_at_10)
            threshold_reports.append((threshold, summary))
            full_reports.append({"threshold": threshold, "summary": summary_to_json(summary)})
        return {
            "manifest_version": manifest.version,
            **calibrate_threshold_results(threshold_reports, target_recall_at_10=target_recall_at_10),
            "threshold_results": full_reports,
        }
    finally:
        conn.close()


def calibrate_threshold_results(
    reports: list[tuple[float, SearchEvaluationSummary]],
    *,
    target_recall_at_10: float = 0.8,
) -> dict[str, object]:
    if not reports:
        raise EvaluationManifestError("At least one threshold report is required.")
    passing = [
        (threshold, summary)
        for threshold, summary in reports
        if summary.recall_at_10 >= target_recall_at_10
    ]
    if passing:
        best_threshold, best_summary = sorted(passing, key=lambda item: (item[0], item[1].mrr), reverse=True)[0]
    else:
        best_threshold, best_summary = sorted(reports, key=lambda item: (item[1].recall_at_10, item[1].mrr, item[0]), reverse=True)[0]
    return {
        "recommended_threshold": best_threshold,
        "target_recall_at_10": target_recall_at_10,
        "best_summary": summary_to_json(best_summary),
        "target_met": best_summary.recall_at_10 >= target_recall_at_10,
    }


def score_query_results(
    query: EvaluationQuery,
    results: list[SearchResult],
    *,
    top_k: int,
) -> QueryEvaluationResult:
    rank: int | None = None
    matched_by: str | None = None
    for idx, result in enumerate(results[:top_k], start=1):
        matched_by = _match_result(query, result)
        if matched_by:
            rank = idx
            break

    passed = rank is not None
    return QueryEvaluationResult(
        id=query.id,
        query=query.query,
        passed=passed,
        rank=rank,
        recall_at_5=1.0 if rank is not None and rank <= 5 else 0.0,
        recall_at_10=1.0 if rank is not None and rank <= 10 else 0.0,
        mrr=(1.0 / rank) if rank else 0.0,
        matched_by=matched_by,
        failure_reason=None if passed else _failure_reason(results),
        result_count=len(results),
        top_results=[_result_summary(item) for item in results[: min(3, top_k)]],
    )


def summarize_evaluation(
    results: list[QueryEvaluationResult],
    *,
    target_recall_at_10: float = 0.8,
) -> SearchEvaluationSummary:
    total = len(results)
    passed = sum(1 for item in results if item.passed)
    recall_at_5 = sum(item.recall_at_5 for item in results) / total if total else 0.0
    recall_at_10 = sum(item.recall_at_10 for item in results) / total if total else 0.0
    mrr = sum(item.mrr for item in results) / total if total else 0.0
    target_met = total > 0 and recall_at_10 >= target_recall_at_10
    return SearchEvaluationSummary(
        total_queries=total,
        passed_query_count=passed,
        failed_query_count=total - passed,
        recall_at_5=recall_at_5,
        recall_at_10=recall_at_10,
        mrr=mrr,
        target_met=target_met,
        quality_status="passed" if target_met else "needs_review",
    )


def summary_to_json(summary: SearchEvaluationSummary) -> dict[str, object]:
    return {
        "total_queries": summary.total_queries,
        "passed_query_count": summary.passed_query_count,
        "failed_query_count": summary.failed_query_count,
        "recall_at_5": summary.recall_at_5,
        "recall_at_10": summary.recall_at_10,
        "mrr": summary.mrr,
        "target_met": summary.target_met,
        "quality_status": summary.quality_status,
    }


def _evaluate_queries(
    queries: list[EvaluationQuery],
    settings: Settings,
    rows: list[Any],
    *,
    top_k: int,
    threshold: float,
    conn: sqlite3.Connection,
) -> list[QueryEvaluationResult]:
    query_results: list[QueryEvaluationResult] = []
    for item in queries:
        results = search(item.query, SearchOptions(top_k=top_k, threshold=threshold), settings, conn=conn, rows=rows)
        query_results.append(score_query_results(item, results, top_k=top_k))
    return query_results


def _parse_query(item: Any) -> EvaluationQuery:
    if not isinstance(item, dict):
        raise EvaluationManifestError("Each query must be a JSON object.")
    query_id = str(item.get("id", "")).strip()
    query = str(item.get("query", "")).strip()
    if not query_id:
        raise EvaluationManifestError("Each query must include id.")
    if not query:
        raise EvaluationManifestError(f"Query {query_id} must include query text.")

    expected_slide_ids = _positive_int_list(item.get("expected_slide_ids", []), "expected_slide_ids")
    expected_source_keywords = _string_list(item.get("expected_source_keywords", []), "expected_source_keywords")
    expected_title_keywords = _string_list(item.get("expected_title_keywords", []), "expected_title_keywords")
    expected_file_keywords = _string_list(item.get("expected_file_keywords", []), "expected_file_keywords")
    if not (expected_slide_ids or expected_source_keywords or expected_title_keywords or expected_file_keywords):
        raise EvaluationManifestError(
            f"Query {query_id} must include at least one expected slide id, source keyword, title keyword, or file keyword."
        )

    return EvaluationQuery(
        id=query_id,
        query=query,
        expected_slide_ids=expected_slide_ids,
        expected_source_keywords=expected_source_keywords,
        expected_title_keywords=expected_title_keywords,
        expected_file_keywords=expected_file_keywords,
        notes=str(item["notes"]) if "notes" in item else None,
    )


def _parse_thresholds(value: Any) -> list[float]:
    if not isinstance(value, list) or not value:
        raise EvaluationManifestError("thresholds must be a non-empty array.")
    try:
        thresholds = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise EvaluationManifestError("thresholds must contain numbers.") from exc
    for item in thresholds:
        if item < 0.0 or item > 1.0:
            raise EvaluationManifestError("thresholds must be between 0.0 and 1.0.")
    return sorted(set(thresholds))


def _positive_int_list(value: Any, field_name: str) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EvaluationManifestError(f"{field_name} must be an array.")
    try:
        parsed = [int(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise EvaluationManifestError(f"{field_name} must contain positive integers.") from exc
    if any(item <= 0 for item in parsed):
        raise EvaluationManifestError(f"{field_name} must contain positive integers.")
    return parsed


def _string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EvaluationManifestError(f"{field_name} must be an array.")
    return [str(item).strip() for item in value if str(item).strip()]


def _match_result(query: EvaluationQuery, result: SearchResult) -> str | None:
    if query.expected_slide_ids and result.slide_id in query.expected_slide_ids:
        return "slide_id"
    title = (result.title or "").lower()
    source_file = str(result.source_file).lower()
    full_text = (result.text_content or result.text_summary).lower()
    if _contains_any(title, query.expected_title_keywords):
        return "title_keyword"
    if _contains_any(source_file, query.expected_file_keywords):
        return "file_keyword"
    if _contains_any(full_text, query.expected_source_keywords):
        return "source_keyword"
    return None


def _contains_any(haystack: str, needles: list[str]) -> bool:
    return any(needle.lower() in haystack for needle in needles)


def _failure_reason(results: list[SearchResult]) -> str:
    return "empty_results" if not results else "expected_result_not_in_top_k"


def _result_summary(result: SearchResult) -> dict[str, object]:
    return {
        "slide_id": result.slide_id,
        "score": result.score,
        "title": result.title,
        "text_summary": result.text_summary,
        "source_file": str(result.source_file),
        "page_number": result.page_number,
    }


__all__ = [
    "EmbeddingProviderError",
    "EvaluationManifest",
    "EvaluationManifestError",
    "EvaluationQuery",
    "QueryEvaluationResult",
    "SearchEvaluationReport",
    "SearchEvaluationSummary",
    "calibrate_search_thresholds",
    "calibrate_threshold_results",
    "evaluate_search_manifest",
    "load_evaluation_manifest",
    "score_query_results",
    "summarize_evaluation",
]
