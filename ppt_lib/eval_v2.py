"""Evaluation v2: graded relevance benchmark with release gates (v1.6-F).

Provides Recall@K, Precision@K, MRR, and nDCG@K metrics with
synthetic and private dataset support.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GradedRelevance:
    """A single graded relevance judgment."""

    query: str
    slide_id: int
    relevance: int  # 0=irrelevant, 1=marginal, 2=relevant, 3=highly relevant

    def to_json(self) -> dict[str, object]:
        return {
            "query": self.query,
            "slide_id": self.slide_id,
            "relevance": self.relevance,
        }


@dataclass(frozen=True)
class EvaluationQuery:
    """A single evaluation query with ground truth."""

    query_id: str
    query: str
    relevant_ids: list[int]
    graded: list[GradedRelevance] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {
            "query_id": self.query_id,
            "query": self.query,
            "relevant_ids": self.relevant_ids,
        }
        if self.graded:
            d["graded"] = [g.to_json() for g in self.graded]
        return d


@dataclass(frozen=True)
class EvaluationDataset:
    """A collection of evaluation queries."""

    name: str
    version: str
    queries: list[EvaluationQuery]
    source: str = "synthetic"  # synthetic | private | manual

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "version": self.version,
            "query_count": len(self.queries),
            "source": self.source,
            "queries": [q.to_json() for q in self.queries],
        }


@dataclass(frozen=True)
class MetricResult:
    """A single metric measurement."""

    name: str
    value: float
    at_k: int | None = None
    details: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {"name": self.name, "value": round(self.value, 4)}
        if self.at_k is not None:
            d["at_k"] = self.at_k
        if self.details:
            d["details"] = self.details
        return d


@dataclass(frozen=True)
class EvaluationReport:
    """Complete evaluation report."""

    dataset_name: str
    dataset_version: str
    metrics: list[MetricResult]
    per_query: dict[str, list[MetricResult]] = field(default_factory=dict)
    pass_thresholds: dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        if not self.pass_thresholds:
            return True
        metric_map = {m.name: m.value for m in self.metrics}
        for name, threshold in self.pass_thresholds.items():
            actual = metric_map.get(name)
            if actual is None or actual < threshold:
                return False
        return True

    def to_json(self) -> dict[str, object]:
        return {
            "dataset_name": self.dataset_name,
            "dataset_version": self.dataset_version,
            "passed": self.passed,
            "metrics": [m.to_json() for m in self.metrics],
            "pass_thresholds": self.pass_thresholds,
        }


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def recall_at_k(
    relevant_ids: set[int],
    retrieved_ids: list[int],
    k: int,
) -> float:
    """Compute Recall@K: fraction of relevant docs retrieved in top-K."""
    if not relevant_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = len(relevant_ids & set(top_k))
    return hits / len(relevant_ids)


def precision_at_k(
    relevant_ids: set[int],
    retrieved_ids: list[int],
    k: int,
) -> float:
    """Compute Precision@K: fraction of top-K that are relevant."""
    if k == 0:
        return 0.0
    top_k = retrieved_ids[:k]
    hits = len(relevant_ids & set(top_k))
    return hits / k


def mrr(
    relevant_ids: set[int],
    retrieved_ids: list[int],
    k: int,
) -> float:
    """Compute Mean Reciprocal Rank (for a single query)."""
    for rank, doc_id in enumerate(retrieved_ids[:k], start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def dcg_at_k(
    relevances: list[int],
    k: int,
) -> float:
    """Compute Discounted Cumulative Gain at K."""
    dcg = 0.0
    for i, rel in enumerate(relevances[:k]):
        if rel > 0:
            dcg += rel / math.log2(i + 2)  # i+2 because rank starts at 1
    return dcg


def ndcg_at_k(
    relevances: list[int],
    ideal_relevances: list[int],
    k: int,
) -> float:
    """Compute Normalized Discounted Cumulative Gain at K."""
    actual_dcg = dcg_at_k(relevances, k)
    ideal_dcg = dcg_at_k(ideal_relevances, k)
    if ideal_dcg == 0:
        return 0.0
    return actual_dcg / ideal_dcg


# ---------------------------------------------------------------------------
# Evaluation runner
# ---------------------------------------------------------------------------


def evaluate_dataset(
    dataset: EvaluationDataset,
    retrieve_fn: Any,
    *,
    k_values: list[int] | None = None,
    pass_thresholds: dict[str, float] | None = None,
) -> EvaluationReport:
    """Run evaluation on a dataset.

    retrieve_fn: callable(query: str, top_k: int) -> list[int]
        Returns list of slide_ids in ranked order.
    """
    k_values = k_values or [5, 10, 20]
    pass_thresholds = pass_thresholds or {}

    all_metrics: dict[str, list[float]] = {}
    per_query: dict[str, list[MetricResult]] = {}

    for eq in dataset.queries:
        max_k = max(k_values)
        retrieved = retrieve_fn(eq.query, max_k)
        relevant = set(eq.relevant_ids)
        query_metrics: list[MetricResult] = []

        for k in k_values:
            # Recall@K
            rec = recall_at_k(relevant, retrieved, k)
            key = f"recall@{k}"
            all_metrics.setdefault(key, []).append(rec)
            query_metrics.append(MetricResult(key, rec, at_k=k))

            # Precision@K
            prec = precision_at_k(relevant, retrieved, k)
            key = f"precision@{k}"
            all_metrics.setdefault(key, []).append(prec)
            query_metrics.append(MetricResult(key, prec, at_k=k))

            # MRR@K
            m = mrr(relevant, retrieved, k)
            key = f"mrr@{k}"
            all_metrics.setdefault(key, []).append(m)
            query_metrics.append(MetricResult(key, m, at_k=k))

            # nDCG@K (if graded relevance available)
            if eq.graded:
                rel_map = {g.slide_id: g.relevance for g in eq.graded}
                actual_rels = [rel_map.get(sid, 0) for sid in retrieved[:k]]
                ideal_rels = sorted(
                    [g.relevance for g in eq.graded],
                    reverse=True,
                )
                n = ndcg_at_k(actual_rels, ideal_rels, k)
                key = f"ndcg@{k}"
                all_metrics.setdefault(key, []).append(n)
                query_metrics.append(MetricResult(key, n, at_k=k))

        per_query[eq.query_id] = query_metrics

    # Aggregate metrics
    aggregate: list[MetricResult] = []
    for name, values in all_metrics.items():
        avg = sum(values) / len(values) if values else 0.0
        aggregate.append(MetricResult(name, avg))

    return EvaluationReport(
        dataset_name=dataset.name,
        dataset_version=dataset.version,
        metrics=aggregate,
        per_query=per_query,
        pass_thresholds=pass_thresholds,
    )


def load_dataset_from_json(path: Path) -> EvaluationDataset:
    """Load an evaluation dataset from a JSON file."""
    with path.open() as f:
        data = json.load(f)

    queries: list[EvaluationQuery] = []
    for q in data.get("queries", []):
        graded = [
            GradedRelevance(
                query=g["query"],
                slide_id=g["slide_id"],
                relevance=g["relevance"],
            )
            for g in q.get("graded", [])
        ]
        queries.append(EvaluationQuery(
            query_id=q["query_id"],
            query=q["query"],
            relevant_ids=q["relevant_ids"],
            graded=graded,
        ))

    return EvaluationDataset(
        name=data.get("name", path.stem),
        version=data.get("version", "1.0"),
        queries=queries,
        source=data.get("source", "manual"),
    )
