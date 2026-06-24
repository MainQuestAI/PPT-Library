"""Tests for audit log (v1.8-G)."""

from __future__ import annotations

import sqlite3

from ppt_lib.audit import (
    AuditEntry,
    get_audit_log,
    get_audit_summary,
    log_action,
)


def _create_db() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")


class TestAuditEntry:
    def test_to_json(self):
        e = AuditEntry("id1", "2026-01-01", "create", "asset", "a1", "user1", {"key": "val"})
        j = e.to_json()
        assert j["action"] == "create"
        assert j["actor"] == "user1"


class TestLogAction:
    def test_log_creates_entry(self):
        conn = _create_db()
        entry = log_action(conn, "approve", "classification", "a1")
        assert entry.action == "approve"
        assert entry.entity_id == "a1"

    def test_log_with_details(self):
        conn = _create_db()
        entry = log_action(conn, "update", "asset", "a1", details={"field": "value"})
        assert entry.details == {"field": "value"}

    def test_log_with_actor(self):
        conn = _create_db()
        entry = log_action(conn, "delete", "asset", "a1", actor="admin")
        assert entry.actor == "admin"


class TestGetAuditLog:
    def test_get_all(self):
        conn = _create_db()
        log_action(conn, "create", "asset", "a1")
        log_action(conn, "update", "asset", "a2")
        entries = get_audit_log(conn)
        assert len(entries) == 2

    def test_filter_by_entity(self):
        conn = _create_db()
        log_action(conn, "create", "asset", "a1")
        log_action(conn, "create", "classification", "c1")
        entries = get_audit_log(conn, entity_type="asset")
        assert len(entries) == 1

    def test_filter_by_action(self):
        conn = _create_db()
        log_action(conn, "create", "asset", "a1")
        log_action(conn, "delete", "asset", "a2")
        entries = get_audit_log(conn, action="create")
        assert len(entries) == 1

    def test_limit(self):
        conn = _create_db()
        for i in range(10):
            log_action(conn, "create", "asset", f"a{i}")
        entries = get_audit_log(conn, limit=3)
        assert len(entries) == 3


class TestAuditSummary:
    def test_empty(self):
        conn = _create_db()
        summary = get_audit_summary(conn)
        assert summary["total_entries"] == 0

    def test_with_entries(self):
        conn = _create_db()
        log_action(conn, "create", "asset", "a1")
        log_action(conn, "create", "asset", "a2")
        log_action(conn, "delete", "asset", "a3")
        summary = get_audit_summary(conn)
        assert summary["total_entries"] == 3
        assert summary["by_action"]["create"] == 2
        assert summary["by_action"]["delete"] == 1
