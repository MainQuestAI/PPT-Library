"""Tests for feedback ranking v2 (v1.7-F)."""

from __future__ import annotations

import sqlite3

from ppt_lib.ranking_v2 import (
    AssetScore,
    RankingContext,
    apply_business_ranking,
    compute_asset_score,
    compute_scores_from_db,
    explain_score,
)


class TestComputeAssetScore:
    def test_no_feedback_returns_prior(self):
        score = compute_asset_score(0, 0, 0)
        assert score.raw_score == 0.5
        assert score.shrunk_score == 0.5
        assert score.confidence == 0.0

    def test_all_selected(self):
        score = compute_asset_score(10, 0, 0)
        assert score.raw_score == 1.0
        assert score.shrunk_score > 0.5
        assert score.confidence > 0.0

    def test_all_rejected(self):
        score = compute_asset_score(0, 10, 0)
        assert score.raw_score == 0.0
        assert score.shrunk_score < 0.5

    def test_mixed_feedback(self):
        score = compute_asset_score(5, 2, 3)
        assert score.raw_score == 0.8  # (5+3)/10
        assert score.shrunk_score > 0.5  # Positive bias

    def test_shrinkage_with_few_samples(self):
        """Few samples should shrink toward prior."""
        score = compute_asset_score(1, 0, 0)
        # With 1 positive and prior_weight=10, shrunk should be close to prior
        assert 0.4 < score.shrunk_score < 0.7
        assert score.confidence < 0.2

    def test_large_sample_converges(self):
        """Large samples should converge to raw score."""
        score = compute_asset_score(80, 20, 0)
        assert abs(score.shrunk_score - score.raw_score) < 0.05
        assert score.confidence > 0.8

    def test_custom_prior(self):
        score = compute_asset_score(0, 0, 0, prior_mean=0.3, prior_weight=5)
        assert score.shrunk_score == 0.3

    def test_to_json(self):
        score = compute_asset_score(5, 3, 2)
        j = score.to_json()
        assert "raw_score" in j
        assert "shrunk_score" in j
        assert "confidence" in j


class TestComputeScoresFromDB:
    def _create_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """CREATE TABLE feedback_events (
                event_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                reason TEXT,
                context_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )"""
        )
        return conn

    def _add_events(self, conn: sqlite3.Connection, asset_id: str, event_type: str, count: int) -> None:
        import uuid
        from datetime import datetime
        for _ in range(count):
            conn.execute(
                "INSERT INTO feedback_events VALUES (?, ?, ?, NULL, '{}', ?)",
                (str(uuid.uuid4()), asset_id, event_type, datetime.now().isoformat()),
            )
        conn.commit()

    def test_compute_from_db(self):
        conn = self._create_db()
        self._add_events(conn, "a1", "selected", 5)
        self._add_events(conn, "a1", "rejected", 2)
        self._add_events(conn, "a2", "selected", 3)
        scores = compute_scores_from_db(conn)
        assert len(scores) == 2
        # Both assets have positive feedback; verify scores are computed
        a1_score = next(s for s in scores if s.asset_id == "a1")
        a2_score = next(s for s in scores if s.asset_id == "a2")
        assert a1_score.selection_count == 5
        assert a2_score.selection_count == 3

    def test_filter_by_asset_ids(self):
        conn = self._create_db()
        self._add_events(conn, "a1", "selected", 5)
        self._add_events(conn, "a2", "selected", 3)
        scores = compute_scores_from_db(conn, asset_ids=["a1"])
        assert len(scores) == 1
        assert scores[0].asset_id == "a1"

    def test_empty_db(self):
        conn = self._create_db()
        scores = compute_scores_from_db(conn)
        assert scores == []

    def test_sorted_by_shrunk_score(self):
        conn = self._create_db()
        self._add_events(conn, "a1", "selected", 2)
        self._add_events(conn, "a2", "selected", 10)
        self._add_events(conn, "a2", "rejected", 1)
        self._add_events(conn, "a3", "rejected", 5)
        scores = compute_scores_from_db(conn)
        shrunk_scores = [s.shrunk_score for s in scores]
        assert shrunk_scores == sorted(shrunk_scores, reverse=True)


class TestBusinessRanking:
    def test_no_context_no_adjustment(self):
        ctx = RankingContext()
        result = apply_business_ranking(0.5, ctx)
        assert result == 0.5

    def test_win_rate_bonus(self):
        ctx = RankingContext()
        result = apply_business_ranking(0.5, ctx, feedback_aggregates={"won": 8, "lost": 2})
        assert result > 0.5

    def test_lose_rate_penalty(self):
        ctx = RankingContext()
        result = apply_business_ranking(0.5, ctx, feedback_aggregates={"won": 2, "lost": 8})
        assert result < 0.5

    def test_context_industry_bonus(self):
        ctx = RankingContext(industry="technology")
        result = apply_business_ranking(0.5, ctx)
        assert result > 0.5

    def test_clamped_to_range(self):
        ctx = RankingContext(industry="x", scenario="y")
        result = apply_business_ranking(0.99, ctx, feedback_aggregates={"won": 100})
        assert result <= 1.0

        result2 = apply_business_ranking(0.01, ctx, feedback_aggregates={"lost": 100})
        assert result2 >= 0.0


class TestExplainScore:
    def test_no_feedback(self):
        score = compute_asset_score(0, 0, 0)
        explanation = explain_score(score)
        assert "No feedback" in explanation["explanation"]

    def test_with_feedback(self):
        score = compute_asset_score(5, 2, 3)
        score = AssetScore("a1", 5, 2, 3, score.raw_score, score.shrunk_score, score.confidence)
        explanation = explain_score(score)
        assert "10 feedback events" in explanation["explanation"]
        assert "5 selected" in explanation["explanation"]

    def test_low_confidence_explanation(self):
        score = compute_asset_score(1, 0, 0)
        score = AssetScore("a1", 1, 0, 0, score.raw_score, score.shrunk_score, score.confidence)
        explanation = explain_score(score)
        assert "Low confidence" in explanation["explanation"]


class TestRankingContext:
    def test_to_json(self):
        ctx = RankingContext(industry="tech", scenario="proposal", narrative_role="solution")
        j = ctx.to_json()
        assert j["industry"] == "tech"
        assert j["scenario"] == "proposal"
