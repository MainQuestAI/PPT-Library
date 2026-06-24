"""Tests for asset health detectors (v1.7-G)."""

from __future__ import annotations

import sqlite3

from ppt_lib.asset_health import (
    DEFAULT_DETECTORS,
    HealthDetector,
    HealthReport,
    ensure_health_tables,
    get_open_findings,
    resolve_finding,
    run_all_detectors,
    run_detector_empty_content,
    run_detector_orphan_assets,
)


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE presentations (
            id INTEGER PRIMARY KEY,
            path TEXT,
            filename TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE slides (
            id INTEGER PRIMARY KEY,
            presentation_id INTEGER,
            text_content TEXT
        )"""
    )
    conn.execute("INSERT INTO presentations VALUES (1, '/test.pptx', 'test.pptx')")
    return conn


class TestHealthDetector:
    def test_to_json(self):
        d = HealthDetector("test", "empty_content", "warning", True, "test detector")
        j = d.to_json()
        assert j["name"] == "test"
        assert j["severity"] == "warning"

    def test_default_detectors(self):
        assert len(DEFAULT_DETECTORS) >= 3
        types = {d.detector_type for d in DEFAULT_DETECTORS}
        assert "empty_content" in types
        assert "orphan" in types


class TestEmptyContentDetector:
    def test_detects_empty(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, '')")
        conn.execute("INSERT INTO slides VALUES (2, 1, '   ')")
        conn.execute("INSERT INTO slides VALUES (3, 1, 'has content')")
        count = run_detector_empty_content(conn)
        assert count == 2

    def test_no_empty(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, 'has content')")
        count = run_detector_empty_content(conn)
        assert count == 0

    def test_detects_null_content(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, NULL)")
        count = run_detector_empty_content(conn)
        assert count == 1


class TestOrphanDetector:
    def test_detects_orphans(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, 'text')")
        conn.execute("INSERT INTO slides VALUES (2, 999, 'orphan')")
        count = run_detector_orphan_assets(conn)
        assert count == 1

    def test_no_orphans(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, 'text')")
        count = run_detector_orphan_assets(conn)
        assert count == 0

    def test_null_presentation(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, NULL, 'text')")
        count = run_detector_orphan_assets(conn)
        assert count == 1


class TestRunAllDetectors:
    def test_runs_all(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, '')")
        conn.execute("INSERT INTO slides VALUES (2, 999, 'orphan')")
        report = run_all_detectors(conn)
        assert isinstance(report, HealthReport)
        assert report.total_assets == 2
        assert report.detectors_run >= 2
        assert report.findings_created >= 2

    def test_report_to_json(self):
        conn = _create_db()
        report = run_all_detectors(conn)
        j = report.to_json()
        assert "generated_at" in j
        assert "total_assets" in j
        assert "findings_by_severity" in j

    def test_custom_detectors(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, '')")
        detectors = [
            HealthDetector("empty_only", "empty_content", "error"),
        ]
        report = run_all_detectors(conn, detectors=detectors)
        assert report.detectors_run == 1


class TestResolveFinding:
    def test_resolve(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, '')")
        run_detector_empty_content(conn)
        findings = get_open_findings(conn)
        assert len(findings) == 1

        ok = resolve_finding(conn, findings[0]["finding_id"])
        assert ok is True

        findings_after = get_open_findings(conn)
        assert len(findings_after) == 0

    def test_dismiss(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, '')")
        run_detector_empty_content(conn)
        findings = get_open_findings(conn)
        resolve_finding(conn, findings[0]["finding_id"], state="dismissed")
        findings_after = get_open_findings(conn)
        assert len(findings_after) == 0

    def test_resolve_nonexistent(self):
        conn = _create_db()
        ensure_health_tables(conn)
        ok = resolve_finding(conn, "nonexistent_id")
        assert ok is False


class TestGetOpenFindings:
    def test_filter_by_severity(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, '')")
        run_detector_empty_content(conn, severity="error")
        findings = get_open_findings(conn, severity="error")
        assert len(findings) == 1
        findings2 = get_open_findings(conn, severity="info")
        assert len(findings2) == 0

    def test_filter_by_type(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, '')")
        run_detector_empty_content(conn)
        findings = get_open_findings(conn, finding_type="empty_content")
        assert len(findings) == 1
        findings2 = get_open_findings(conn, finding_type="orphan")
        assert len(findings2) == 0

    def test_sorted_by_severity(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, '')")
        conn.execute("INSERT INTO slides VALUES (2, 999, 'orphan')")
        run_detector_empty_content(conn, severity="warning")
        run_detector_orphan_assets(conn, severity="error")
        findings = get_open_findings(conn)
        assert len(findings) == 2
        # error should come before warning
        assert findings[0]["severity"] == "error"

    def test_limit(self):
        conn = _create_db()
        for i in range(1, 11):
            conn.execute(f"INSERT INTO slides VALUES ({i}, 1, '')")
        run_detector_empty_content(conn)
        findings = get_open_findings(conn, limit=3)
        assert len(findings) == 3
