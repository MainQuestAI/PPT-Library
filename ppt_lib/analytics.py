"""Analytics and metrics aggregation (v2.0-F).

Provides aggregate metrics for dashboards: query patterns, asset
utilization, health trends, and governance compliance.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class AnalyticsReport:
    """Complete analytics report for a workspace."""

    generated_at: str
    period_days: int
    query_metrics: dict[str, object]
    asset_metrics: dict[str, object]
    health_metrics: dict[str, object]
    governance_metrics: dict[str, object]

    def to_json(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "period_days": self.period_days,
            "query_metrics": self.query_metrics,
            "asset_metrics": self.asset_metrics,
            "health_metrics": self.health_metrics,
            "governance_metrics": self.governance_metrics,
        }


def compute_query_metrics(conn: sqlite3.Connection) -> dict[str, object]:
    """Compute query-related metrics."""
    cursor = conn.cursor()
    metrics: dict[str, object] = {}

    # Total search queries (if search log exists)
    try:
        cursor.execute("SELECT COUNT(*) FROM search_log")
        metrics["total_queries"] = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        metrics["total_queries"] = 0

    # Feedback events as proxy for engagement
    try:
        cursor.execute("SELECT COUNT(*) FROM feedback_events")
        metrics["feedback_events"] = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        metrics["feedback_events"] = 0

    try:
        cursor.execute(
            "SELECT event_type, COUNT(*) FROM feedback_events GROUP BY event_type"
        )
        metrics["feedback_by_type"] = dict(cursor.fetchall())
    except sqlite3.OperationalError:
        metrics["feedback_by_type"] = {}

    return metrics


def compute_asset_metrics(conn: sqlite3.Connection) -> dict[str, object]:
    """Compute asset-related metrics."""
    cursor = conn.cursor()
    metrics: dict[str, object] = {}

    # Slide counts
    try:
        cursor.execute("SELECT COUNT(*) FROM slides")
        metrics["total_slides"] = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        metrics["total_slides"] = 0

    # Presentation counts
    try:
        cursor.execute("SELECT COUNT(*) FROM presentations")
        metrics["total_presentations"] = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        metrics["total_presentations"] = 0

    # Classification coverage
    try:
        cursor.execute("SELECT COUNT(DISTINCT asset_id) FROM classification_values")
        classified = cursor.fetchone()[0]
        total = metrics.get("total_slides", 0)
        metrics["classified_slides"] = classified
        if isinstance(total, int) and total > 0:
            metrics["classification_coverage_pct"] = round(classified / total * 100, 1)
        else:
            metrics["classification_coverage_pct"] = 0.0
    except sqlite3.OperationalError:
        metrics["classified_slides"] = 0
        metrics["classification_coverage_pct"] = 0.0

    # Duplicate groups
    try:
        cursor.execute("SELECT COUNT(*) FROM duplicate_groups")
        metrics["duplicate_groups"] = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        metrics["duplicate_groups"] = 0

    # Lineage edges
    try:
        cursor.execute("SELECT COUNT(*) FROM lineage_edges")
        metrics["lineage_edges"] = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        metrics["lineage_edges"] = 0

    return metrics


def compute_health_metrics(conn: sqlite3.Connection) -> dict[str, object]:
    """Compute health-related metrics."""
    cursor = conn.cursor()
    metrics: dict[str, object] = {}

    try:
        cursor.execute("SELECT COUNT(*) FROM health_findings")
        metrics["total_findings"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT state, COUNT(*) FROM health_findings GROUP BY state"
        )
        by_state = dict(cursor.fetchall())
        metrics["findings_by_state"] = by_state

        cursor.execute(
            "SELECT severity, COUNT(*) FROM health_findings GROUP BY severity"
        )
        metrics["findings_by_severity"] = dict(cursor.fetchall())

        open_count = by_state.get("open", 0)
        total = metrics["total_findings"]
        if isinstance(total, int) and total > 0:
            metrics["resolution_rate_pct"] = round(
                (1 - open_count / total) * 100, 1
            )
        else:
            metrics["resolution_rate_pct"] = 0.0
    except sqlite3.OperationalError:
        metrics["total_findings"] = 0
        metrics["findings_by_state"] = {}
        metrics["findings_by_severity"] = {}
        metrics["resolution_rate_pct"] = 0.0

    return metrics


def compute_governance_metrics(conn: sqlite3.Connection) -> dict[str, object]:
    """Compute governance-related metrics."""
    cursor = conn.cursor()
    metrics: dict[str, object] = {}

    # Identity coverage
    try:
        cursor.execute("SELECT COUNT(*) FROM asset_identity_map")
        metrics["identity_mappings"] = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        metrics["identity_mappings"] = 0

    # Audit log entries
    try:
        cursor.execute("SELECT COUNT(*) FROM audit_log")
        metrics["audit_entries"] = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        metrics["audit_entries"] = 0

    # Review requests
    try:
        cursor.execute("SELECT COUNT(*) FROM review_requests")
        metrics["review_requests"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT status, COUNT(*) FROM review_requests GROUP BY status"
        )
        metrics["reviews_by_status"] = dict(cursor.fetchall())
    except sqlite3.OperationalError:
        metrics["review_requests"] = 0
        metrics["reviews_by_status"] = {}

    # Jobs completed
    try:
        cursor.execute(
            "SELECT status, COUNT(*) FROM jobs GROUP BY status"
        )
        metrics["jobs_by_status"] = dict(cursor.fetchall())
    except sqlite3.OperationalError:
        metrics["jobs_by_status"] = {}

    return metrics


def generate_analytics_report(
    conn: sqlite3.Connection,
    *,
    period_days: int = 30,
) -> AnalyticsReport:
    """Generate a complete analytics report."""
    return AnalyticsReport(
        generated_at=datetime.now(UTC).isoformat(),
        period_days=period_days,
        query_metrics=compute_query_metrics(conn),
        asset_metrics=compute_asset_metrics(conn),
        health_metrics=compute_health_metrics(conn),
        governance_metrics=compute_governance_metrics(conn),
    )
