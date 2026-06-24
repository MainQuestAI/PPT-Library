"""Tests for classification pipeline (v1.7-E)."""

from __future__ import annotations

import sqlite3

from ppt_lib.classification import (
    CLASSIFICATION_FIELDS,
    ClassificationBenchmark,
    ClassificationSuggestion,
    approve_classification,
    classify_batch,
    classify_deterministic,
    get_classification_status,
    reject_classification,
    save_classifications,
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
    return conn


class TestClassificationFields:
    def test_fields_defined(self):
        assert "page_archetype" in CLASSIFICATION_FIELDS
        assert "narrative_role" in CLASSIFICATION_FIELDS
        assert "industry" in CLASSIFICATION_FIELDS


class TestClassifyDeterministic:
    def test_architecture_diagram(self):
        suggestions = classify_deterministic(
            "This slide shows the system architecture diagram with microservices",
            asset_id="a1",
        )
        archetypes = [s for s in suggestions if s.field_name == "page_archetype"]
        assert len(archetypes) == 1
        assert archetypes[0].value == "diagram"
        assert "architecture" in archetypes[0].matched_keywords

    def test_problem_narrative(self):
        suggestions = classify_deterministic(
            "The main challenge is the risk of data loss and gap in coverage",
            asset_id="a1",
        )
        roles = [s for s in suggestions if s.field_name == "narrative_role"]
        assert len(roles) == 1
        assert roles[0].value == "problem"

    def test_solution_narrative(self):
        suggestions = classify_deterministic(
            "Our solution approach is to implement a new strategy",
            asset_id="a1",
        )
        roles = [s for s in suggestions if s.field_name == "narrative_role"]
        assert len(roles) >= 1
        assert roles[0].value == "solution"

    def test_default_content(self):
        suggestions = classify_deterministic(
            "Some generic text about a random topic",
            asset_id="a1",
        )
        archetypes = [s for s in suggestions if s.field_name == "page_archetype"]
        # No strong keyword match, no archetype suggestion
        if archetypes:
            assert archetypes[0].confidence < 0.5

    def test_empty_text(self):
        suggestions = classify_deterministic("", asset_id="a1")
        assert suggestions == []

    def test_confidence_increases_with_matches(self):
        s1 = classify_deterministic("architecture diagram", asset_id="a1")
        s2 = classify_deterministic(
            "architecture diagram flow process system",
            asset_id="a2",
        )
        c1 = next((s.confidence for s in s1 if s.field_name == "page_archetype"), 0)
        c2 = next((s.confidence for s in s2 if s.field_name == "page_archetype"), 0)
        assert c2 >= c1


class TestClassificationSuggestion:
    def test_to_json(self):
        s = ClassificationSuggestion("a1", "page_archetype", "diagram", 0.8, "deterministic", ["architecture"])
        j = s.to_json()
        assert j["value"] == "diagram"
        assert j["confidence"] == 0.8
        assert j["source"] == "deterministic"


class TestClassifyBatch:
    def test_classify_unclassified(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 'architecture diagram microservices', 'T1')")
        conn.execute("INSERT INTO slides VALUES (2, 'challenge risk problem gap', 'T2')")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1)")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a2', 'srev_2', 2)")
        suggestions = classify_batch(conn, limit=10)
        assert len(suggestions) >= 2

    def test_overwrite_mode(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 'architecture diagram', 'T1')")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1)")
        suggestions = classify_batch(conn, overwrite=True)
        assert len(suggestions) >= 1


class TestSaveAndReview:
    def test_save(self):
        conn = _create_db()
        suggestions = [
            ClassificationSuggestion("a1", "page_archetype", "diagram", 0.8, "deterministic"),
            ClassificationSuggestion("a1", "narrative_role", "solution", 0.7, "deterministic"),
        ]
        count = save_classifications(conn, suggestions)
        assert count == 2

    def test_approve(self):
        conn = _create_db()
        suggestions = [ClassificationSuggestion("a1", "page_archetype", "diagram", 0.8, "deterministic")]
        save_classifications(conn, suggestions)
        ok = approve_classification(conn, "a1", "page_archetype")
        assert ok is True

    def test_reject(self):
        conn = _create_db()
        suggestions = [ClassificationSuggestion("a1", "page_archetype", "diagram", 0.8, "deterministic")]
        save_classifications(conn, suggestions)
        ok = reject_classification(conn, "a1", "page_archetype")
        assert ok is True


class TestClassificationStatus:
    def test_empty_db(self):
        conn = _create_db()
        status = get_classification_status(conn)
        assert status["total_slides"] == 0
        assert status["coverage_pct"] == 0.0

    def test_with_classifications(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 'architecture diagram', 'T1')")
        conn.execute("INSERT INTO slides VALUES (2, 'challenge risk', 'T2')")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1)")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a2', 'srev_2', 2)")
        suggestions = classify_batch(conn)
        save_classifications(conn, suggestions)
        status = get_classification_status(conn)
        assert status["classified_slides"] >= 1
        assert status["coverage_pct"] > 0


class TestClassificationBenchmark:
    def test_accuracy(self):
        b = ClassificationBenchmark("page_archetype", 100, 85, 10)
        assert abs(b.accuracy - 85 / 90) < 0.001

    def test_all_abstained(self):
        b = ClassificationBenchmark("page_archetype", 100, 0, 100)
        assert b.accuracy == 0.0

    def test_to_json(self):
        b = ClassificationBenchmark("page_archetype", 100, 85, 10)
        j = b.to_json()
        assert j["total"] == 100
        assert j["accuracy"] > 0
