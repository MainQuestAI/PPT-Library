"""Tests for evaluation v2 metrics and runner (v1.6-F)."""

from __future__ import annotations

import json
from pathlib import Path

from ppt_lib.eval_v2 import (
    EvaluationDataset,
    EvaluationQuery,
    GradedRelevance,
    MetricResult,
    dcg_at_k,
    evaluate_dataset,
    load_dataset_from_json,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


class TestRecall:
    def test_perfect_recall(self):
        assert recall_at_k({1, 2, 3}, [1, 2, 3, 4, 5], 5) == 1.0

    def test_partial_recall(self):
        assert recall_at_k({1, 2, 3, 4}, [1, 2, 5, 6, 7], 5) == 0.5

    def test_zero_recall(self):
        assert recall_at_k({1, 2}, [3, 4, 5], 5) == 0.0

    def test_empty_relevant(self):
        assert recall_at_k(set(), [1, 2, 3], 5) == 0.0

    def test_at_k_truncation(self):
        assert recall_at_k({5}, [1, 2, 3, 4, 5], 3) == 0.0
        assert recall_at_k({5}, [1, 2, 3, 4, 5], 5) == 1.0


class TestPrecision:
    def test_perfect_precision(self):
        assert precision_at_k({1, 2, 3}, [1, 2, 3], 3) == 1.0

    def test_partial_precision(self):
        assert precision_at_k({1, 2, 3}, [1, 4, 5, 6, 7], 5) == 0.2

    def test_zero_k(self):
        assert precision_at_k({1}, [1, 2, 3], 0) == 0.0


class TestMRR:
    def test_first_rank(self):
        assert mrr({1}, [1, 2, 3], 5) == 1.0

    def test_second_rank(self):
        assert mrr({2}, [1, 2, 3], 5) == 0.5

    def test_third_rank(self):
        assert mrr({3}, [1, 2, 3], 5) == 1.0 / 3

    def test_not_found(self):
        assert mrr({10}, [1, 2, 3], 5) == 0.0

    def test_at_k_truncation(self):
        assert mrr({5}, [1, 2, 3, 4, 5], 3) == 0.0


class TestDCG:
    def test_dcg_basic(self):
        rels = [3, 2, 3, 0, 1, 2]
        dcg = dcg_at_k(rels, 6)
        assert dcg > 0

    def test_dcg_zeros(self):
        assert dcg_at_k([0, 0, 0], 3) == 0.0

    def test_dcg_single(self):
        dcg = dcg_at_k([1], 1)
        assert dcg == 1.0 / 1.0  # rel / log2(2) = 1.0

    def test_dcg_empty(self):
        assert dcg_at_k([], 5) == 0.0


class TestNDCG:
    def test_perfect_ndcg(self):
        rels = [3, 2, 1]
        ideal = [3, 2, 1]
        assert ndcg_at_k(rels, ideal, 3) == 1.0

    def test_zero_ndcg(self):
        assert ndcg_at_k([0, 0, 0], [3, 2, 1], 3) == 0.0

    def test_zero_ideal(self):
        assert ndcg_at_k([0, 0], [0, 0], 2) == 0.0

    def test_partial_ndcg(self):
        rels = [1, 2, 3]
        ideal = [3, 2, 1]
        n = ndcg_at_k(rels, ideal, 3)
        assert 0 < n < 1.0


class TestMetricResult:
    def test_to_json(self):
        m = MetricResult("recall@10", 0.85, at_k=10)
        j = m.to_json()
        assert j["name"] == "recall@10"
        assert j["value"] == 0.85
        assert j["at_k"] == 10

    def test_to_json_no_details(self):
        m = MetricResult("mrr", 0.7)
        j = m.to_json()
        assert "details" not in j


class TestEvaluationDataset:
    def test_to_json(self):
        ds = EvaluationDataset(
            name="test",
            version="1.0",
            queries=[
                EvaluationQuery("q1", "architecture", [1, 2, 3]),
            ],
        )
        j = ds.to_json()
        assert j["name"] == "test"
        assert j["query_count"] == 1


class TestEvaluateDataset:
    def _make_dataset(self) -> EvaluationDataset:
        return EvaluationDataset(
            name="test",
            version="1.0",
            queries=[
                EvaluationQuery("q1", "architecture", [1, 2]),
                EvaluationQuery("q2", "machine learning", [3, 4]),
            ],
        )

    def test_perfect_retrieval(self):
        ds = self._make_dataset()
        results = evaluate_dataset(ds, lambda q, k: [1, 2, 3, 4, 5][:k])
        assert len(results.metrics) > 0
        recall_metrics = [m for m in results.metrics if "recall" in m.name]
        assert len(recall_metrics) > 0

    def test_with_thresholds_pass(self):
        ds = self._make_dataset()
        results = evaluate_dataset(
            ds,
            lambda q, k: [1, 2, 3, 4, 5][:k],
            pass_thresholds={"recall@5": 0.5},
        )
        assert results.passed is True

    def test_with_thresholds_fail(self):
        ds = self._make_dataset()
        results = evaluate_dataset(
            ds,
            lambda q, k: [99, 98, 97, 96, 95][:k],
            pass_thresholds={"recall@5": 0.5},
        )
        assert results.passed is False

    def test_per_query_metrics(self):
        ds = self._make_dataset()
        results = evaluate_dataset(ds, lambda q, k: [1, 2, 3][:k])
        assert "q1" in results.per_query
        assert "q2" in results.per_query

    def test_with_graded_relevance(self):
        ds = EvaluationDataset(
            name="graded",
            version="1.0",
            queries=[
                EvaluationQuery(
                    "q1", "test query", [1, 2],
                    graded=[
                        GradedRelevance("test query", 1, 3),
                        GradedRelevance("test query", 2, 1),
                    ],
                ),
            ],
        )
        results = evaluate_dataset(ds, lambda q, k: [1, 2, 3][:k])
        ndcg_metrics = [m for m in results.metrics if "ndcg" in m.name]
        assert len(ndcg_metrics) > 0

    def test_report_to_json(self):
        ds = self._make_dataset()
        results = evaluate_dataset(ds, lambda q, k: [1, 2][:k])
        j = results.to_json()
        assert j["dataset_name"] == "test"
        assert "passed" in j
        assert "metrics" in j


class TestLoadDataset:
    def test_load_from_json(self, tmp_path: Path):
        data = {
            "name": "test-suite",
            "version": "2.0",
            "source": "synthetic",
            "queries": [
                {
                    "query_id": "q1",
                    "query": "architecture overview",
                    "relevant_ids": [1, 2, 3],
                    "graded": [
                        {"query": "architecture overview", "slide_id": 1, "relevance": 3},
                        {"query": "architecture overview", "slide_id": 2, "relevance": 2},
                    ],
                },
            ],
        }
        f = tmp_path / "eval.json"
        f.write_text(json.dumps(data))
        ds = load_dataset_from_json(f)
        assert ds.name == "test-suite"
        assert ds.version == "2.0"
        assert len(ds.queries) == 1
        assert ds.queries[0].relevant_ids == [1, 2, 3]
        assert len(ds.queries[0].graded) == 2
