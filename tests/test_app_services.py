"""Tests for application service layer (v1.8-A)."""

from __future__ import annotations

import sqlite3

from ppt_lib.asset_schema import create_asset_schema_tables
from ppt_lib.services.app_services import (
    AssetService,
    HealthService,
    JobService,
    LibraryService,
    ReviewService,
    SearchService,
    ServiceResult,
)


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE slides (
            id INTEGER PRIMARY KEY,
            presentation_id INTEGER,
            text_content TEXT,
            title TEXT,
            metadata_json TEXT DEFAULT '{}',
            slide_revision_id TEXT,
            canonical_asset_id TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE presentations (
            id INTEGER PRIMARY KEY,
            path TEXT,
            filename TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE embeddings (
            slide_id INTEGER,
            presentation_id INTEGER,
            embedding BLOB
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
        """CREATE TABLE feedback_events (
            event_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            reason TEXT,
            context_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE _meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )"""
    )
    conn.execute("INSERT INTO _meta VALUES ('schema_version', '5')")
    create_asset_schema_tables(conn)
    return conn


class TestServiceResult:
    def test_success(self):
        r = ServiceResult(True, "ok", data={"key": "value"})
        assert r.success is True
        j = r.to_json()
        assert j["success"] is True

    def test_failure(self):
        r = ServiceResult(False, "failed", errors=[{"code": "E1", "message": "err"}])
        assert r.success is False
        j = r.to_json()
        assert "errors" in j


class TestSearchService:
    def test_search_empty(self):
        conn = _create_db()
        svc = SearchService(conn)
        result = svc.search("architecture")
        assert result.success is True
        assert result.data is not None
        assert "candidates" in result.data


class TestAssetService:
    def test_get_asset_not_found(self):
        conn = _create_db()
        svc = AssetService(conn)
        result = svc.get_asset("nonexistent")
        assert result.success is False

    def test_get_asset_found(self):
        conn = _create_db()
        conn.execute(
            "INSERT INTO slide_assets VALUES ('a1', 'slide', 'now', 'now', '{}')"
        )
        svc = AssetService(conn)
        result = svc.get_asset("a1")
        assert result.success is True
        assert result.data["asset_id"] == "a1"

    def test_list_assets_empty(self):
        conn = _create_db()
        svc = AssetService(conn)
        result = svc.list_assets()
        assert result.success is True
        assert result.data["total"] == 0

    def test_list_assets_with_data(self):
        conn = _create_db()
        conn.execute("INSERT INTO slide_assets VALUES ('a1', 'slide', 'now', 'now', '{}')")
        conn.execute("INSERT INTO slide_assets VALUES ('a2', 'deck', 'now', 'now', '{}')")
        svc = AssetService(conn)
        result = svc.list_assets()
        assert result.success is True
        assert result.data["total"] == 2


class TestHealthService:
    def test_run_scan(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, '', 'T1', '{}', NULL, NULL)")
        svc = HealthService(conn)
        result = svc.run_scan()
        assert result.success is True

    def test_get_findings_empty(self):
        conn = _create_db()
        svc = HealthService(conn)
        result = svc.get_findings()
        assert result.success is True
        assert result.data["count"] == 0

    def test_resolve_nonexistent(self):
        conn = _create_db()
        svc = HealthService(conn)
        result = svc.resolve_finding("nonexistent")
        assert result.success is False


class TestReviewService:
    def test_run_classification(self):
        conn = _create_db()
        conn.execute("INSERT INTO slides VALUES (1, 1, 'architecture diagram microservices', 'T1', '{}', NULL, NULL)")
        conn.execute("INSERT INTO asset_identity_map VALUES ('a1', 'srev_1', 1)")
        svc = ReviewService(conn)
        result = svc.run_classification()
        assert result.success is True
        assert result.data["saved"] >= 1

    def test_get_status(self):
        conn = _create_db()
        svc = ReviewService(conn)
        result = svc.get_status()
        assert result.success is True
        assert "total_slides" in result.data


class TestJobService:
    def test_list_jobs_empty(self):
        conn = _create_db()
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
        svc = JobService(conn)
        result = svc.list_jobs()
        assert result.success is True

    def test_get_job_not_found(self):
        conn = _create_db()
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
        svc = JobService(conn)
        result = svc.get_job("nonexistent")
        assert result.success is False


class TestLibraryService:
    def test_get_status(self):
        conn = _create_db()
        svc = LibraryService(conn)
        result = svc.get_status()
        assert result.success is True
        assert result.data["schema_version"] == 5

    def test_services_available(self):
        conn = _create_db()
        svc = LibraryService(conn)
        assert isinstance(svc.search, SearchService)
        assert isinstance(svc.assets, AssetService)
        assert isinstance(svc.health, HealthService)
        assert isinstance(svc.review, ReviewService)
        assert isinstance(svc.jobs, JobService)
