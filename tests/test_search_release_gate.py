"""Tests for search release gate (v1.6-H)."""

from __future__ import annotations

import sqlite3

from ppt_lib.fts_search import SearchDocument, create_fts_tables, index_search_document
from ppt_lib.search_release_gate import (
    GateCheck,
    SearchReleaseGate,
    run_search_release_gate,
)


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE slides (
            id INTEGER PRIMARY KEY,
            presentation_id INTEGER,
            title TEXT,
            text_content TEXT,
            metadata_json TEXT DEFAULT '{}',
            slide_revision_id TEXT,
            canonical_asset_id TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE asset_identity_map (
            canonical_asset_id TEXT,
            slide_revision_id TEXT,
            legacy_slide_id INTEGER
        )"""
    )
    conn.execute(
        """CREATE TABLE embeddings (
            slide_id INTEGER,
            presentation_id INTEGER,
            embedding BLOB
        )"""
    )
    return conn


class TestGateCheck:
    def test_to_json(self):
        c = GateCheck("test", True, "passed", details={"key": "value"})
        j = c.to_json()
        assert j["name"] == "test"
        assert j["passed"] is True


class TestSearchReleaseGate:
    def test_all_pass(self):
        gate = SearchReleaseGate(
            generated_at="2026-06-23",
            checks=[
                GateCheck("a", True, "ok"),
                GateCheck("b", True, "ok"),
            ],
            metrics={"m": 1.0},
        )
        assert gate.passed is True
        assert gate.pass_count == 2
        assert gate.fail_count == 0

    def test_some_fail(self):
        gate = SearchReleaseGate(
            generated_at="2026-06-23",
            checks=[
                GateCheck("a", True, "ok"),
                GateCheck("b", False, "fail"),
            ],
            metrics={},
        )
        assert gate.passed is False
        assert gate.pass_count == 1
        assert gate.fail_count == 1

    def test_to_json(self):
        gate = SearchReleaseGate(
            generated_at="2026-06-23",
            checks=[GateCheck("test", True, "ok")],
            metrics={"count": 100.0},
        )
        j = gate.to_json()
        assert j["passed"] is True
        assert "checks" in j
        assert "metrics" in j


class TestRunSearchReleaseGate:
    def test_runs_without_fts(self):
        conn = _create_db()
        gate = run_search_release_gate(conn)
        assert isinstance(gate, SearchReleaseGate)
        assert len(gate.checks) >= 5
        # FTS doesn't exist, so fts5_tables_exist should fail
        fts_check = next(c for c in gate.checks if c.name == "fts5_tables_exist")
        assert fts_check.passed is False

    def test_runs_with_fts(self):
        conn = _create_db()
        create_fts_tables(conn)
        doc = SearchDocument("sd_1", "a1", "srev_1", 1,
            "Test", "content", "", "", "", "", "", "", "", "")
        index_search_document(conn, doc)
        gate = run_search_release_gate(conn)
        fts_check = next(c for c in gate.checks if c.name == "fts5_tables_exist")
        assert fts_check.passed is True
        count_check = next(c for c in gate.checks if c.name == "fts5_document_count")
        assert count_check.passed is True

    def test_egress_policy_check(self):
        conn = _create_db()
        gate = run_search_release_gate(conn)
        egress_check = next(c for c in gate.checks if c.name == "egress_policy_default")
        assert egress_check.passed is True

    def test_contract_registry_check(self):
        conn = _create_db()
        gate = run_search_release_gate(conn)
        contract_check = next(c for c in gate.checks if c.name == "search_contract_registered")
        assert contract_check.passed is True

    def test_profiles_check(self):
        conn = _create_db()
        gate = run_search_release_gate(conn)
        profile_check = next(c for c in gate.checks if c.name == "search_profiles_available")
        assert profile_check.passed is True
