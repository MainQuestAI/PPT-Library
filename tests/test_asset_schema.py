"""Tests for asset/revision/lineage schema (v1.7-A)."""

from __future__ import annotations

import sqlite3

from ppt_lib.asset_schema import (
    ClassificationValue,
    FeedbackEvent,
    HealthFinding,
    LineageEdge,
    SlideAsset,
    SlideRevision,
    add_feedback_event,
    add_health_finding,
    add_lineage_edge,
    create_asset_schema_tables,
    get_feedback_aggregates,
    get_health_summary,
    get_lineage_edges,
    insert_slide_revision,
    resolve_health_finding,
    upsert_slide_asset,
)


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    create_asset_schema_tables(conn)
    return conn


class TestSlideAsset:
    def test_upsert_creates(self):
        conn = _create_db()
        asset = upsert_slide_asset(conn, "asset_001", labels={"type": "architecture"})
        assert asset.canonical_asset_id == "asset_001"
        assert asset.asset_type == "slide"
        assert asset.labels == {"type": "architecture"}

    def test_upsert_updates_labels(self):
        conn = _create_db()
        upsert_slide_asset(conn, "asset_001", labels={"v": "1"})
        updated = upsert_slide_asset(conn, "asset_001", labels={"v": "2"})
        assert updated.labels == {"v": "2"}

    def test_to_json(self):
        a = SlideAsset("a1", "slide", "now", "now", {"k": "v"})
        j = a.to_json()
        assert j["canonical_asset_id"] == "a1"
        assert j["labels"] == {"k": "v"}


class TestSlideRevision:
    def test_insert_revision(self):
        conn = _create_db()
        upsert_slide_asset(conn, "asset_001")
        rev = SlideRevision(
            slide_revision_id="srev_001",
            canonical_asset_id="asset_001",
            fingerprint="fp_hash",
            algorithm_version="v1",
            text_hash="text_hash",
            visual_hash=None,
            layout_hash=None,
            created_at="now",
        )
        insert_slide_revision(conn, rev)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM slide_revisions WHERE slide_revision_id = 'srev_001'")
        assert cursor.fetchone()[0] == 1

    def test_to_json(self):
        r = SlideRevision("srev_1", "a1", "fp", "v1", "th", "vh", "lh", "now")
        j = r.to_json()
        assert j["slide_revision_id"] == "srev_1"
        assert j["visual_hash"] == "vh"


class TestLineageEdge:
    def test_add_edge(self):
        conn = _create_db()
        edge = add_lineage_edge(conn, "asset_001", "asset_002", "revision")
        assert edge.edge_type == "revision"
        assert edge.source == "auto"
        assert edge.confidence == 1.0

    def test_add_edge_with_metadata(self):
        conn = _create_db()
        edge = add_lineage_edge(
            conn, "a1", "a2", "derived",
            confidence=0.8,
            source="manual",
            metadata={"reason": "similar content"},
        )
        assert edge.confidence == 0.8
        assert edge.metadata == {"reason": "similar content"}

    def test_get_edges_outgoing(self):
        conn = _create_db()
        add_lineage_edge(conn, "a1", "a2", "revision")
        add_lineage_edge(conn, "a1", "a3", "copy")
        add_lineage_edge(conn, "a3", "a4", "revision")
        edges = get_lineage_edges(conn, "a1", direction="outgoing")
        assert len(edges) == 2

    def test_get_edges_incoming(self):
        conn = _create_db()
        add_lineage_edge(conn, "a1", "a2", "revision")
        add_lineage_edge(conn, "a3", "a2", "copy")
        edges = get_lineage_edges(conn, "a2", direction="incoming")
        assert len(edges) == 2

    def test_get_edges_both(self):
        conn = _create_db()
        add_lineage_edge(conn, "a1", "a2", "revision")
        add_lineage_edge(conn, "a2", "a3", "copy")
        edges = get_lineage_edges(conn, "a2", direction="both")
        assert len(edges) == 2

    def test_get_edges_by_type(self):
        conn = _create_db()
        add_lineage_edge(conn, "a1", "a2", "revision")
        add_lineage_edge(conn, "a1", "a3", "copy")
        edges = get_lineage_edges(conn, "a1", direction="outgoing", edge_type="copy")
        assert len(edges) == 1
        assert edges[0].edge_type == "copy"

    def test_to_json(self):
        e = LineageEdge("e1", "a1", "a2", "revision", 1.0, "auto", "now")
        j = e.to_json()
        assert j["edge_id"] == "e1"
        assert j["confidence"] == 1.0


class TestFeedbackEvent:
    def test_add_feedback(self):
        conn = _create_db()
        event = add_feedback_event(
            conn, "asset_001", "selected",
            reason="good match",
            context={"query": "architecture"},
        )
        assert event.asset_id == "asset_001"
        assert event.event_type == "selected"
        assert event.reason == "good match"

    def test_get_aggregates(self):
        conn = _create_db()
        add_feedback_event(conn, "a1", "selected")
        add_feedback_event(conn, "a1", "selected")
        add_feedback_event(conn, "a1", "rejected")
        agg = get_feedback_aggregates(conn, "a1")
        assert agg["selected"] == 2
        assert agg["rejected"] == 1

    def test_to_json(self):
        e = FeedbackEvent("e1", "a1", "selected", "good", {}, "now")
        j = e.to_json()
        assert j["event_id"] == "e1"
        assert j["event_type"] == "selected"


class TestHealthFinding:
    def test_add_finding(self):
        conn = _create_db()
        finding = add_health_finding(
            conn, "asset_001", "warning", "duplicate",
            "Possible duplicate detected",
            suggested_action="Review and merge or split",
        )
        assert finding.severity == "warning"
        assert finding.state == "open"
        assert finding.suggested_action == "Review and merge or split"

    def test_resolve_finding(self):
        conn = _create_db()
        finding = add_health_finding(conn, "a1", "error", "orphan", "Orphan asset")
        resolve_health_finding(conn, finding.finding_id, state="resolved")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT state FROM health_findings WHERE finding_id = ?",
            (finding.finding_id,),
        )
        assert cursor.fetchone()[0] == "resolved"

    def test_get_health_summary(self):
        conn = _create_db()
        add_health_finding(conn, "a1", "warning", "duplicate", "dup 1")
        add_health_finding(conn, "a2", "warning", "duplicate", "dup 2")
        add_health_finding(conn, "a3", "error", "orphan", "orphan 1")
        f = add_health_finding(conn, "a4", "warning", "outdated", "old")
        resolve_health_finding(conn, f.finding_id)
        summary = get_health_summary(conn)
        assert summary["warning_open"] == 2
        assert summary["error_open"] == 1
        assert summary["warning_resolved"] == 1

    def test_to_json(self):
        f = HealthFinding("f1", "a1", "warning", "dup", "msg", "action", "open", "now")
        j = f.to_json()
        assert j["finding_id"] == "f1"
        assert j["severity"] == "warning"


class TestClassificationValue:
    def test_to_json(self):
        c = ClassificationValue("a1", "page_archetype", "diagram", 0.9, "model", "pending", "now")
        j = c.to_json()
        assert j["field_name"] == "page_archetype"
        assert j["confidence"] == 0.9
        assert j["source"] == "model"
