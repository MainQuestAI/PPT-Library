"""Feedback ranking v2 with Bayesian shrinkage (v1.7-F).

Computes asset value scores from feedback events using Bayesian
shrinkage to prevent small samples from dominating rankings.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class AssetScore:
    """Computed score for an asset based on feedback events."""

    asset_id: str
    selection_count: int
    rejection_count: int
    approval_count: int
    raw_score: float
    shrunk_score: float
    confidence: float

    def to_json(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "selection_count": self.selection_count,
            "rejection_count": self.rejection_count,
            "approval_count": self.approval_count,
            "raw_score": round(self.raw_score, 4),
            "shrunk_score": round(self.shrunk_score, 4),
            "confidence": round(self.confidence, 4),
        }


@dataclass(frozen=True)
class RankingContext:
    """Context for business ranking adjustments."""

    industry: str | None = None
    scenario: str | None = None
    narrative_role: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "industry": self.industry,
            "scenario": self.scenario,
            "narrative_role": self.narrative_role,
        }


def compute_asset_score(
    selection_count: int,
    rejection_count: int,
    approval_count: int,
    *,
    prior_mean: float = 0.5,
    prior_weight: int = 10,
) -> AssetScore:
    """Compute Bayesian-shrunk score for an asset.

    Uses a Beta-Binomial conjugate model:
    - Prior: Beta(prior_mean * prior_weight, (1-prior_mean) * prior_weight)
    - Posterior: updated with selection/approval as successes, rejection as failures

    The shrunk_score converges to prior_mean when sample size is small,
    and to raw_score when sample size is large.
    """
    total = selection_count + rejection_count + approval_count

    # Raw score: positive events / total events
    if total == 0:
        return AssetScore(
            asset_id="",
            selection_count=0,
            rejection_count=0,
            approval_count=0,
            raw_score=prior_mean,
            shrunk_score=prior_mean,
            confidence=0.0,
        )

    positive = selection_count + approval_count
    raw_score = positive / total

    # Bayesian shrinkage
    prior_alpha = prior_mean * prior_weight
    prior_beta = (1 - prior_mean) * prior_weight
    posterior_alpha = prior_alpha + positive
    posterior_beta = prior_beta + rejection_count
    shrunk_score = posterior_alpha / (posterior_alpha + posterior_beta)

    # Confidence: based on sample size relative to prior weight
    confidence = min(1.0, total / (total + prior_weight))

    return AssetScore(
        asset_id="",
        selection_count=selection_count,
        rejection_count=rejection_count,
        approval_count=approval_count,
        raw_score=raw_score,
        shrunk_score=shrunk_score,
        confidence=confidence,
    )


def compute_scores_from_db(
    conn: sqlite3.Connection,
    *,
    asset_ids: list[str] | None = None,
) -> list[AssetScore]:
    """Compute scores for assets from feedback_events table."""
    cursor = conn.cursor()

    if asset_ids:
        placeholders = ",".join("?" for _ in asset_ids)
        cursor.execute(
            f"""SELECT asset_id, event_type, COUNT(*)
                FROM feedback_events
                WHERE asset_id IN ({placeholders})
                GROUP BY asset_id, event_type""",
            asset_ids,
        )
    else:
        cursor.execute(
            """SELECT asset_id, event_type, COUNT(*)
               FROM feedback_events
               GROUP BY asset_id, event_type"""
        )

    # Aggregate by asset
    aggregates: dict[str, dict[str, int]] = {}
    for asset_id, event_type, count in cursor.fetchall():
        if asset_id not in aggregates:
            aggregates[asset_id] = {}
        aggregates[asset_id][event_type] = count

    scores: list[AssetScore] = []
    for asset_id, events in aggregates.items():
        score = compute_asset_score(
            selection_count=events.get("selected", 0),
            rejection_count=events.get("rejected", 0),
            approval_count=events.get("approved", 0),
        )
        # Replace empty asset_id
        scores.append(AssetScore(
            asset_id=asset_id,
            selection_count=score.selection_count,
            rejection_count=score.rejection_count,
            approval_count=score.approval_count,
            raw_score=score.raw_score,
            shrunk_score=score.shrunk_score,
            confidence=score.confidence,
        ))

    scores.sort(key=lambda s: s.shrunk_score, reverse=True)
    return scores


def apply_business_ranking(
    base_score: float,
    context: RankingContext,
    *,
    feedback_aggregates: dict[str, int] | None = None,
) -> float:
    """Apply business ranking adjustments to a base score.

    Adjustments are additive bonuses based on context matching.
    """
    adjustment = 0.0

    if feedback_aggregates:
        won = feedback_aggregates.get("won", 0)
        lost = feedback_aggregates.get("lost", 0)
        total_deals = won + lost
        if total_deals > 0:
            win_rate = won / total_deals
            # Win rate bonus: up to +0.1 for high win rate
            adjustment += (win_rate - 0.5) * 0.2

    # Context-specific adjustments
    if context.industry:
        # Industry match could boost by a small amount
        adjustment += 0.01

    if context.scenario:
        adjustment += 0.01

    return max(0.0, min(1.0, base_score + adjustment))


def explain_score(
    score: AssetScore,
    context: RankingContext | None = None,
) -> dict[str, object]:
    """Generate a human-readable explanation of an asset's score."""
    parts: list[str] = []

    total = score.selection_count + score.rejection_count + score.approval_count
    if total > 0:
        parts.append(
            f"{total} feedback events "
            f"({score.selection_count} selected, "
            f"{score.rejection_count} rejected, "
            f"{score.approval_count} approved)"
        )
    else:
        parts.append("No feedback events yet (using prior)")

    if score.confidence < 0.3:
        parts.append("Low confidence — score heavily shrunk toward prior")
    elif score.confidence < 0.7:
        parts.append("Moderate confidence")
    else:
        parts.append("High confidence — score reflects observed data")

    return {
        "asset_id": score.asset_id,
        "shrunk_score": round(score.shrunk_score, 4),
        "raw_score": round(score.raw_score, 4),
        "confidence": round(score.confidence, 4),
        "explanation": "; ".join(parts),
    }
