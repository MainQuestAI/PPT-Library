from __future__ import annotations

import json
from pathlib import Path

import pytest

from ppt_lib.evaluation import (
    EvaluationManifest,
    EvaluationManifestError,
    EvaluationQuery,
    SearchEvaluationSummary,
    calibrate_search_thresholds,
    calibrate_threshold_results,
    load_evaluation_manifest,
    score_query_results,
)
from ppt_lib.searcher import SearchResult
from ppt_lib.settings import Settings


def test_load_evaluation_manifest_requires_queries(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": "1.0"}), encoding="utf-8")

    with pytest.raises(EvaluationManifestError, match="queries"):
        load_evaluation_manifest(manifest)


def test_load_evaluation_manifest_accepts_expected_keywords(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": "1.0",
                "queries": [
                    {
                        "id": "q1",
                        "query": "数据治理",
                        "expected_source_keywords": ["governance"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_evaluation_manifest(manifest)

    assert loaded.version == "1.0"
    assert loaded.queries[0].id == "q1"
    assert loaded.queries[0].expected_source_keywords == ["governance"]


def test_load_evaluation_manifest_rejects_duplicate_ids(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "queries": [
                    {"id": "q1", "query": "a", "expected_title_keywords": ["a"]},
                    {"id": "q1", "query": "b", "expected_title_keywords": ["b"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationManifestError, match="unique"):
        load_evaluation_manifest(manifest)


def test_load_evaluation_manifest_rejects_invalid_threshold(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "queries": [{"id": "q1", "query": "a", "expected_title_keywords": ["a"]}],
                "thresholds": [-0.1],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationManifestError, match="between"):
        load_evaluation_manifest(manifest)


def test_load_evaluation_manifest_rejects_non_numeric_threshold(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "queries": [{"id": "q1", "query": "a", "expected_title_keywords": ["a"]}],
                "thresholds": ["bad"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationManifestError, match="numbers"):
        load_evaluation_manifest(manifest)


def test_score_query_results_uses_slide_id_match() -> None:
    query = EvaluationQuery(id="q1", query="SCRM", expected_slide_ids=[20])

    scored = score_query_results(query, [_result(10, "A", "/tmp/a.pptx"), _result(20, "B", "/tmp/b.pptx")], top_k=10)

    assert scored.passed is True
    assert scored.rank == 2
    assert scored.recall_at_10 == 1.0
    assert scored.mrr == 0.5
    assert scored.matched_by == "slide_id"


def test_score_query_results_uses_keyword_match() -> None:
    query = EvaluationQuery(id="q1", query="CMS", expected_title_keywords=["部署"])

    scored = score_query_results(query, [_result(1, "CMS 部署方式", "/tmp/cms.pptx")], top_k=10)

    assert scored.passed is True
    assert scored.rank == 1
    assert scored.top_results[0]["text_summary"] == "summary"


def test_score_query_results_records_failure_reason() -> None:
    query = EvaluationQuery(id="q1", query="CMS", expected_title_keywords=["部署"])

    empty = score_query_results(query, [], top_k=10)
    off_target = score_query_results(query, [_result(1, "Other", "/tmp/other.pptx")], top_k=10)

    assert empty.failure_reason == "empty_results"
    assert off_target.failure_reason == "expected_result_not_in_top_k"


def test_score_query_results_matches_source_keyword_in_full_text_beyond_summary() -> None:
    query = EvaluationQuery(id="q1", query="long deck", expected_source_keywords=["tail-keyword"])
    result = _result(1, "Title", "/tmp/a.pptx", summary="short summary")
    result = SearchResult(
        slide_id=result.slide_id,
        score=result.score,
        title=result.title,
        text_summary=result.text_summary,
        source_file=result.source_file,
        page_number=result.page_number,
        screenshot_path=result.screenshot_path,
        source=result.source,
        confidence=result.confidence,
        metadata=result.metadata,
        text_content="x" * 300 + " tail-keyword",
    )

    scored = score_query_results(query, [result], top_k=10)

    assert scored.passed is True
    assert scored.matched_by == "source_keyword"


def test_calibrate_threshold_results_picks_highest_threshold_with_same_recall() -> None:
    reports = [
        (0.0, SearchEvaluationSummary(10, 8, 2, 0.7, 0.8, 0.6, True, "passed")),
        (0.35, SearchEvaluationSummary(10, 8, 2, 0.7, 0.8, 0.6, True, "passed")),
        (0.65, SearchEvaluationSummary(10, 5, 5, 0.4, 0.5, 0.3, False, "needs_review")),
    ]

    calibrated = calibrate_threshold_results(reports)

    assert calibrated["recommended_threshold"] == 0.35
    assert calibrated["target_recall_at_10"] == 0.8
    assert calibrated["target_met"] is True


def test_calibrate_threshold_results_falls_back_to_best_recall() -> None:
    reports = [
        (0.0, SearchEvaluationSummary(10, 3, 7, 0.2, 0.3, 0.1, False, "needs_review")),
        (0.35, SearchEvaluationSummary(10, 5, 5, 0.4, 0.5, 0.3, False, "needs_review")),
    ]

    calibrated = calibrate_threshold_results(reports)

    assert calibrated["recommended_threshold"] == 0.35
    assert calibrated["target_met"] is False


def test_calibration_runs_production_search_for_each_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(home_dir=tmp_path, embedding_provider="fake")
    manifest = EvaluationManifest(
        version="1.0",
        queries=[EvaluationQuery(id="q1", query="CMS", expected_title_keywords=["CMS"])],
        thresholds=[0.0, 0.5, 0.8],
    )
    observed_thresholds: list[float] = []

    monkeypatch.setattr("ppt_lib.evaluation.load_search_rows", lambda conn, dimensions: [])

    def fake_search(query, options, settings, **kwargs):
        observed_thresholds.append(options.threshold)
        return [_result(1, "CMS", "/tmp/cms.pptx")] if options.threshold < 0.8 else []

    monkeypatch.setattr("ppt_lib.evaluation.search", fake_search)

    calibrated = calibrate_search_thresholds(manifest, settings)

    assert observed_thresholds == [0.0, 0.5, 0.8]
    assert calibrated["recommended_threshold"] == 0.5


def _result(slide_id: int, title: str, source_file: str, summary: str = "summary") -> SearchResult:
    return SearchResult(
        slide_id=slide_id,
        score=0.9,
        title=title,
        text_summary=summary,
        source_file=Path(source_file),
        page_number=1,
        screenshot_path=None,
        source="text_extraction",
        confidence=None,
        metadata={},
    )
