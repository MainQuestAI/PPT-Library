"""Tests for analytics (v2.0-F) and GA release gate (v2.0-H)."""

from __future__ import annotations

import sqlite3

from ppt_lib.analytics import (
    AnalyticsReport,
    compute_asset_metrics,
    compute_governance_metrics,
    compute_health_metrics,
    compute_query_metrics,
    generate_analytics_report,
)
from ppt_lib.asset_schema import create_asset_schema_tables
from ppt_lib.ga_release_gate import GAReleaseGate, run_ga_release_gate


def _create_full_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE presentations (id INTEGER PRIMARY KEY, path TEXT, filename TEXT)")
    conn.execute(
        """CREATE TABLE slides (
            id INTEGER PRIMARY KEY, presentation_id INTEGER,
            text_content TEXT, title TEXT
        )"""
    )
    conn.execute("CREATE TABLE embeddings (slide_id INTEGER, presentation_id INTEGER, embedding BLOB)")
    conn.execute(
        """CREATE TABLE asset_identity_map (
            canonical_asset_id TEXT, slide_revision_id TEXT, legacy_slide_id INTEGER
        )"""
    )
    conn.execute(
        """CREATE TABLE feedback_events (
            event_id TEXT PRIMARY KEY, asset_id TEXT, event_type TEXT,
            reason TEXT, context_json TEXT, created_at TEXT
        )"""
    )
    conn.execute("""CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT)""")
    conn.execute("INSERT INTO _meta VALUES ('schema_version', '5')")
    create_asset_schema_tables(conn)

    # Seed data
    conn.execute("INSERT INTO presentations VALUES (1, '/t.pptx', 't.pptx')")
    conn.execute("INSERT INTO slides VALUES (1, 1, 'architecture diagram', 'T1')")
    conn.execute("INSERT INTO slides VALUES (2, 1, 'data pipeline', 'T2')")
    conn.execute("INSERT INTO feedback_events VALUES ('f1', 'a1', 'selected', NULL, '{}', 'now')")
    conn.execute("INSERT INTO feedback_events VALUES ('f2', 'a1', 'rejected', NULL, '{}', 'now')")
    conn.commit()
    return conn


class TestComputeQueryMetrics:
    def test_with_feedback(self):
        conn = _create_full_db()
        metrics = compute_query_metrics(conn)
        assert metrics["feedback_events"] == 2
        assert metrics["feedback_by_type"]["selected"] == 1

    def test_empty_db(self):
        conn = sqlite3.connect(":memory:")
        metrics = compute_query_metrics(conn)
        assert metrics["total_queries"] == 0


class TestComputeAssetMetrics:
    def test_with_data(self):
        conn = _create_full_db()
        metrics = compute_asset_metrics(conn)
        assert metrics["total_slides"] == 2
        assert metrics["total_presentations"] == 1

    def test_empty_db(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE slides (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE presentations (id INTEGER PRIMARY KEY)")
        metrics = compute_asset_metrics(conn)
        assert metrics["total_slides"] == 0


class TestComputeHealthMetrics:
    def test_with_findings(self):
        conn = _create_full_db()
        conn.execute(
            """INSERT INTO health_findings VALUES
               ('h1', 'a1', 'warning', 'dup', 'msg', NULL, 'open', 'now', NULL)"""
        )
        metrics = compute_health_metrics(conn)
        assert metrics["total_findings"] == 1

    def test_empty(self):
        conn = _create_full_db()
        metrics = compute_health_metrics(conn)
        assert metrics["total_findings"] == 0


class TestComputeGovernanceMetrics:
    def test_with_identity(self):
        conn = _create_full_db()
        conn.execute(
            "INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1)"
        )
        metrics = compute_governance_metrics(conn)
        assert metrics["identity_mappings"] == 1


class TestAnalyticsReport:
    def test_generate(self):
        conn = _create_full_db()
        report = generate_analytics_report(conn, period_days=7)
        assert isinstance(report, AnalyticsReport)
        assert report.period_days == 7
        assert report.generated_at != ""

    def test_to_json(self):
        conn = _create_full_db()
        report = generate_analytics_report(conn)
        j = report.to_json()
        assert "query_metrics" in j
        assert "asset_metrics" in j
        assert "health_metrics" in j
        assert "governance_metrics" in j


class TestGAReleaseGate:
    def test_run_gate(self):
        conn = _create_full_db()
        gate = run_ga_release_gate(conn)
        assert isinstance(gate, GAReleaseGate)
        assert len(gate.checks) >= 8
        assert gate.pass_count >= 5

    def test_gate_to_json(self):
        conn = _create_full_db()
        gate = run_ga_release_gate(conn)
        j = gate.to_json()
        assert "passed" in j
        assert "checks" in j
        assert j["pass_count"] + j["fail_count"] == len(j["checks"])

    def test_core_features_intact(self):
        conn = _create_full_db()
        gate = run_ga_release_gate(conn)
        core_check = next(
            (c for c in gate.checks if c["name"] == "core_features_intact"),
            None,
        )
        assert core_check is not None
        assert core_check["passed"] is True

    def test_rbac_operational(self):
        conn = _create_full_db()
        gate = run_ga_release_gate(conn)
        rbac_check = next(
            (c for c in gate.checks if c["name"] == "rbac_operational"),
            None,
        )
        assert rbac_check is not None
        assert rbac_check["passed"] is True
