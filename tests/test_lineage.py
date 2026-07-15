"""Tests for deck/slide lineage (v1.7-D)."""

from __future__ import annotations

import sqlite3

from ppt_lib.asset_schema import add_lineage_edge, create_asset_schema_tables
from ppt_lib.lineage import (
    LineageInference,
    LineagePath,
    apply_inferred_lineage,
    compute_change_summary,
    detect_cycles,
    get_lineage_chain,
    infer_lineage_from_text_similarity,
)


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE slides (
            id INTEGER PRIMARY KEY,
            text_content TEXT,
            title TEXT
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
        """CREATE TABLE presentations (
            id INTEGER PRIMARY KEY,
            path TEXT,
            filename TEXT
        )"""
    )
    create_asset_schema_tables(conn)
    return conn


class TestLineageInference:
    def test_to_json(self):
        inf = LineageInference("a1", "a2", "revision", 0.9, {"method": "text"})
        j = inf.to_json()
        assert j["confidence"] == 0.9
        assert j["edge_type"] == "revision"


class TestInferFromText:
    def test_infer_similar(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 'architecture microservices deployment containers', 'T1')")
        conn.execute("INSERT INTO slides VALUES (2, 'architecture microservices deployment cloud', 'T2')")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1)")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a2', 'srev_2', 2)")
        inferences = infer_lineage_from_text_similarity(conn, "a1", threshold=0.5)
        assert len(inferences) >= 1
        assert inferences[0].target_asset_id == "a1"

    def test_no_similar(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 'architecture microservices', 'T1')")
        conn.execute("INSERT INTO slides VALUES (2, 'machine learning neural network', 'T2')")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1)")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a2', 'srev_2', 2)")
        inferences = infer_lineage_from_text_similarity(conn, "a1", threshold=0.8)
        assert len(inferences) == 0

    def test_missing_asset(self):
        conn = _create_db()
        inferences = infer_lineage_from_text_similarity(conn, "nonexistent")
        assert inferences == []


class TestApplyInferred:
    def test_apply(self):
        conn = _create_db()
        inferences = [
            LineageInference("a1", "a2", "revision", 0.9, {}),
            LineageInference("a3", "a4", "copy", 0.6, {}),
        ]
        count = apply_inferred_lineage(conn, inferences, min_confidence=0.7)
        assert count == 1  # Only a1->a2 passes threshold


class TestLineagePath:
    def test_to_json(self):
        p = LineagePath(["a1", "a2", "a3"], ["revision", "copy"], 0.9)
        j = p.to_json()
        assert len(j["asset_ids"]) == 3
        assert j["total_confidence"] == 0.9


class TestDetectCycles:
    def test_no_cycle(self):
        conn = _create_db()
        add_lineage_edge(conn, "a1", "a2", "revision")
        add_lineage_edge(conn, "a2", "a3", "revision")
        cycles = detect_cycles(conn, "a1")
        assert len(cycles) == 0

    def test_detect_cycle(self):
        conn = _create_db()
        add_lineage_edge(conn, "a1", "a2", "revision")
        add_lineage_edge(conn, "a2", "a3", "revision")
        add_lineage_edge(conn, "a3", "a1", "revision")
        cycles = detect_cycles(conn, "a1")
        assert len(cycles) >= 1


class TestGetLineageChain:
    def test_outgoing_chain(self):
        conn = _create_db()
        add_lineage_edge(conn, "a1", "a2", "revision")
        add_lineage_edge(conn, "a2", "a3", "copy")
        paths = get_lineage_chain(conn, "a1", direction="outgoing", max_depth=5)
        assert len(paths) >= 1
        all_ids = []
        for p in paths:
            all_ids.extend(p.asset_ids)
        assert "a1" in all_ids

    def test_empty_chain(self):
        conn = _create_db()
        paths = get_lineage_chain(conn, "a1", direction="outgoing")
        assert paths == []

    def test_cycle_path_includes_closing_asset(self):
        conn = _create_db()
        add_lineage_edge(conn, "a1", "a2", "revision")
        add_lineage_edge(conn, "a2", "a1", "copy")

        paths = get_lineage_chain(conn, "a1", direction="outgoing")

        assert paths[0].asset_ids == ["a1", "a2", "a1"]
        assert paths[0].edge_types == ["revision", "copy"]
        assert len(paths[0].asset_ids) == len(paths[0].edge_types) + 1

    def test_depth_limited_path_includes_terminal_asset(self):
        conn = _create_db()
        add_lineage_edge(conn, "a1", "a2", "revision")
        add_lineage_edge(conn, "a2", "a3", "copy")

        paths = get_lineage_chain(conn, "a1", direction="outgoing", max_depth=0)

        assert paths[0].asset_ids == ["a1", "a2"]
        assert paths[0].edge_types == ["revision"]


class TestChangeSummary:
    def test_compute_summary(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 'architecture microservices deployment', 'T1')")
        conn.execute("INSERT INTO slides VALUES (2, 'architecture containers deployment cloud', 'T2')")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1)")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a2', 'srev_2', 2)")
        summary = compute_change_summary(conn, "a1", "a2")
        assert summary["asset_a"] == "a1"
        assert summary["asset_b"] == "a2"
        assert summary["similarity"] > 0
        assert summary["words_added"] >= 1
        assert summary["words_removed"] >= 1
