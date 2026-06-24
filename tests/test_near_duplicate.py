"""Tests for near duplicate classifier (v1.7-C)."""

from __future__ import annotations

import sqlite3

from ppt_lib.near_duplicate import (
    ClassifierMetrics,
    DuplicateGroup,
    DuplicatePair,
    classify_pair,
    compute_multi_signal_similarity,
    compute_text_similarity,
    detect_near_duplicates,
    get_review_queue,
    manual_classify,
    save_duplicate_pairs,
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


class TestClassifyPair:
    def test_exact(self):
        assert classify_pair(0.98) == "exact"

    def test_near(self):
        assert classify_pair(0.85) == "near"

    def test_client_variant(self):
        assert classify_pair(0.70) == "client_variant"

    def test_distinct(self):
        assert classify_pair(0.3) == "distinct"

    def test_custom_thresholds(self):
        assert classify_pair(0.9, exact_threshold=0.92) == "near"


class TestTextSimilarity:
    def test_identical(self):
        assert compute_text_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert compute_text_similarity("hello world", "foo bar baz") == 0.0

    def test_partial_overlap(self):
        sim = compute_text_similarity(
            "architecture microservices deployment",
            "architecture containers deployment",
        )
        assert 0.3 < sim < 0.8

    def test_empty_texts(self):
        assert compute_text_similarity("", "") == 1.0

    def test_one_empty(self):
        assert compute_text_similarity("hello", "") == 0.0

    def test_case_insensitive(self):
        assert compute_text_similarity("Hello World", "hello world") == 1.0


class TestMultiSignalSimilarity:
    def test_combined_score(self):
        combined, signals = compute_multi_signal_similarity(0.8, 0.6)
        assert combined == 0.7
        assert signals["text"] == 0.8
        assert signals["visual"] == 0.6

    def test_custom_weights(self):
        combined, _ = compute_multi_signal_similarity(
            0.8, 0.6, text_weight=0.8, visual_weight=0.2,
        )
        assert abs(combined - 0.76) < 0.001


class TestDuplicatePair:
    def test_to_json(self):
        p = DuplicatePair("a1", "a2", 0.85, {"text": 0.9, "visual": 0.8}, "near")
        j = p.to_json()
        assert j["similarity"] == 0.85
        assert j["classification"] == "near"


class TestDuplicateGroup:
    def test_to_json(self):
        g = DuplicateGroup("g1", "a1", ["a1", "a2", "a3"], "near")
        j = g.to_json()
        assert j["group_id"] == "g1"
        assert len(j["members"]) == 3


class TestDetectNearDuplicates:
    def test_detect_identical_slides(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 'architecture overview deployment', 'Title1')")
        conn.execute("INSERT INTO slides VALUES (2, 'architecture overview deployment', 'Title2')")
        conn.execute("INSERT INTO asset_identity_map VALUES ('asset_1', 'srev_1', 1)")
        conn.execute("INSERT INTO asset_identity_map VALUES ('asset_2', 'srev_2', 2)")
        pairs = detect_near_duplicates(conn, threshold=0.9)
        assert len(pairs) >= 1
        assert pairs[0].classification in ("exact", "near")

    def test_detect_different_slides(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 'architecture overview', 'Title1')")
        conn.execute("INSERT INTO slides VALUES (2, 'machine learning pipeline', 'Title2')")
        conn.execute("INSERT INTO asset_identity_map VALUES ('asset_1', 'srev_1', 1)")
        conn.execute("INSERT INTO asset_identity_map VALUES ('asset_2', 'srev_2', 2)")
        pairs = detect_near_duplicates(conn, threshold=0.8)
        assert len(pairs) == 0

    def test_skips_same_asset(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 'same text', 'T1')")
        conn.execute("INSERT INTO slides VALUES (2, 'same text', 'T2')")
        conn.execute("INSERT INTO asset_identity_map VALUES ('asset_1', 'srev_1', 1)")
        conn.execute("INSERT INTO asset_identity_map VALUES ('asset_1', 'srev_2', 2)")
        pairs = detect_near_duplicates(conn, threshold=0.8)
        assert len(pairs) == 0

    def test_empty_db(self):
        conn = _create_db()
        pairs = detect_near_duplicates(conn)
        assert pairs == []


class TestSaveAndReview:
    def test_save_and_get(self):
        conn = _create_db()
        pairs = [
            DuplicatePair("a1", "a2", 0.9, {"text": 0.9}, "near"),
            DuplicatePair("a3", "a4", 0.85, {"text": 0.85}, "pending"),
        ]
        count = save_duplicate_pairs(conn, pairs)
        assert count == 2

        queue = get_review_queue(conn, classification="pending")
        assert len(queue) == 1
        assert queue[0].asset_id_a == "a3"

    def test_manual_classify(self):
        conn = _create_db()
        pairs = [DuplicatePair("a1", "a2", 0.9, {}, "pending")]
        save_duplicate_pairs(conn, pairs)
        manual_classify(conn, "a1", "a2", "exact")
        queue = get_review_queue(conn, classification="pending")
        assert len(queue) == 0

    def test_get_review_empty_table(self):
        conn = _create_db()
        queue = get_review_queue(conn)
        assert queue == []


class TestClassifierMetrics:
    def test_to_json(self):
        m = ClassifierMetrics(
            pairs_evaluated=100,
            exact_matches=10,
            near_duplicates=20,
            client_variants=5,
            distinct=65,
            precision=0.92,
            recall=0.88,
        )
        j = m.to_json()
        assert j["pairs_evaluated"] == 100
        assert j["precision"] == 0.92
