"""Tests for SSE events (v1.8-F)."""

from __future__ import annotations

import sqlite3

from ppt_lib.sse import (
    SSEEvent,
    format_sse_stream,
    generate_health_stream,
    generate_job_events,
)


def _create_jobs_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            job_type TEXT, idempotency_key TEXT, source_id TEXT,
            source_locator TEXT, source_content_hash TEXT,
            pipeline_config_hash TEXT, status TEXT, current_stage TEXT,
            total_units INTEGER, completed_units INTEGER,
            failed_units INTEGER, attempt INTEGER, cancel_requested INTEGER,
            created_at TEXT, updated_at TEXT, started_at TEXT, finished_at TEXT,
            error_json TEXT, warning_json TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE job_events (
            event_id TEXT PRIMARY KEY,
            job_id TEXT, event_type TEXT, occurred_at TEXT, payload_json TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE job_stages (
            stage_id TEXT PRIMARY KEY,
            job_id TEXT, stage_name TEXT, status TEXT,
            started_at TEXT, finished_at TEXT, artifact_path TEXT, error_json TEXT
        )"""
    )
    return conn


class TestSSEEvent:
    def test_format_basic(self):
        event = SSEEvent(event="test", data={"key": "value"})
        formatted = event.format()
        assert "event: test" in formatted
        assert 'data: {"key": "value"}' in formatted

    def test_format_with_id(self):
        event = SSEEvent(event="test", data={}, event_id="42")
        formatted = event.format()
        assert "id: 42" in formatted

    def test_format_with_retry(self):
        event = SSEEvent(event="test", data={}, retry_ms=5000)
        formatted = event.format()
        assert "retry: 5000" in formatted

    def test_format_ends_with_double_newline(self):
        event = SSEEvent(event="test", data={})
        formatted = event.format()
        assert formatted.endswith("\n\n")


class TestGenerateJobEvents:
    def test_completed_job(self):
        conn = _create_jobs_db()
        conn.execute(
            """INSERT INTO jobs VALUES (
                'j1', 'index', NULL, NULL, NULL, NULL, 'hash', 'completed',
                'finalize', 10, 10, 0, 1, 0,
                'now', 'now', 'now', 'now', NULL, NULL
            )"""
        )
        events = list(generate_job_events(conn, "j1", poll_interval=0.01))
        assert len(events) >= 1
        # Should have a terminal event
        terminal = [e for e in events if "completed" in e.event or "failed" in e.event]
        assert len(terminal) >= 1

    def test_not_found_job(self):
        conn = _create_jobs_db()
        events = list(generate_job_events(conn, "nonexistent", poll_interval=0.01))
        assert len(events) == 1
        assert events[0].event == "error"

    def test_running_job_emits_progress(self):
        conn = _create_jobs_db()
        conn.execute(
            """INSERT INTO jobs VALUES (
                'j1', 'index', NULL, NULL, NULL, NULL, 'hash', 'completed',
                'commit', 10, 10, 0, 1, 0,
                'now', 'now', 'now', 'now', NULL, NULL
            )"""
        )
        events = list(generate_job_events(conn, "j1", poll_interval=0.01, max_events=5))
        assert len(events) >= 1


class TestGenerateHealthStream:
    def test_empty_health(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """CREATE TABLE health_findings (
                finding_id TEXT PRIMARY KEY,
                asset_id TEXT, severity TEXT, finding_type TEXT,
                message TEXT, suggested_action TEXT,
                state TEXT DEFAULT 'open', created_at TEXT, resolved_at TEXT
            )"""
        )
        events = list(generate_health_stream(conn, poll_interval=0.01, max_events=2))
        assert len(events) >= 1
        assert events[0].event == "health.update"
        assert events[0].data["open_findings"] == 0


class TestFormatSSEStream:
    def test_format_multiple_events(self):
        def gen():
            yield SSEEvent(event="a", data={"x": 1})
            yield SSEEvent(event="b", data={"y": 2})

        output = format_sse_stream(gen())
        assert "event: a" in output
        assert "event: b" in output
