"""Tests for application service layer (v1.8-A)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ppt_lib.asset_schema import create_asset_schema_tables
from ppt_lib.contracts.registry import ContractRegistry
from ppt_lib.db import PresentationRecord, SlideRecord, connect, init_db, upsert_presentation, upsert_slide
from ppt_lib.embedding import FakeEmbeddingProvider
from ppt_lib.fts_search import index_from_slides, lexical_search
from ppt_lib.services.app_services import (
    AssetService,
    HealthService,
    JobService,
    LibraryService,
    ReviewService,
    SearchService,
    ServiceResult,
)
from ppt_lib.settings import Settings


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


def _add_search_slide(
    conn: sqlite3.Connection,
    tmp_path: Path,
    ordinal: int,
    *,
    industry: str | None = None,
    scenario: str | None = None,
    narrative_role: str | None = None,
    body_text: str = "shared architecture reference",
) -> tuple[int, int]:
    path = tmp_path / f"deck-{ordinal:03d}.pptx"
    presentation_id = upsert_presentation(
        conn,
        PresentationRecord(path, path.name, None, 1, f"hash-{ordinal}", 1, float(ordinal)),
    )
    slide_id = upsert_slide(
        conn,
        SlideRecord(
            presentation_id,
            0,
            f"Architecture {ordinal:03d}",
            body_text,
            None,
            None,
            "text_extraction",
            [],
            {},
        ),
    )
    conn.execute(
        "UPDATE slides SET industry = ?, scenario = ?, narrative_role = ? WHERE id = ?",
        (industry, scenario, narrative_role, slide_id),
    )
    conn.commit()
    return presentation_id, slide_id


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

    def test_search_accepts_settings_as_legacy_positional_argument(self, tmp_path: Path):
        conn = _create_db()
        svc = SearchService(conn, Settings(home_dir=tmp_path, embedding_provider="fake"))

        result = svc.search("architecture")

        assert result.success is True

    def test_search_v2_runs_real_init_db_pipeline(self, tmp_path: Path):
        conn = connect(tmp_path / "index.db")
        init_db(conn)
        presentation_id = upsert_presentation(
            conn,
            PresentationRecord(tmp_path / "deck.pptx", "deck.pptx", None, 1, "h", 1, 1.0),
        )
        provider = FakeEmbeddingProvider()
        upsert_slide(
            conn,
            SlideRecord(
                presentation_id,
                0,
                "Architecture",
                "cloud architecture reference",
                provider.encode("cloud architecture"),
                None,
                "text_extraction",
                [],
                {},
            ),
        )
        index_from_slides(conn)
        settings = Settings(home_dir=tmp_path, embedding_provider="fake")
        svc = SearchService(conn, settings=settings, embedding_provider=provider)

        payload = svc.search_v2("cloud architecture", request_id="req_test", explain=True)

        assert payload["_meta"]["contract"] == "ppt_library.search_response.v2"
        assert payload["_meta"]["request_id"] == "req_test"
        candidate = payload["data"]["candidates"][0]
        assert candidate["canonical_asset_id"]
        assert candidate["slide_revision_id"]
        assert 0.0 <= candidate["score"] <= 1.0
        assert payload["data"]["trace"]["vector_backend"]["candidate_count"] == 1
        assert ContractRegistry().validate("search-response.v2", payload) == []

    def test_search_v2_applies_declared_array_filters(self, tmp_path: Path):
        conn = connect(tmp_path / "index.db")
        init_db(conn)
        _, target_slide_id = _add_search_slide(
            conn,
            tmp_path,
            1,
            industry="automotive",
            scenario="proposal",
            narrative_role="solution_architecture",
        )
        _add_search_slide(
            conn,
            tmp_path,
            2,
            industry="retail",
            scenario="proposal",
            narrative_role="solution_architecture",
        )
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """INSERT INTO asset_identity_map
               (canonical_asset_id, slide_revision_id, legacy_slide_id, identity_status,
                algorithm_version, created_at, updated_at)
               VALUES (?, ?, ?, 'resolved', 'test', ?, ?)""",
            ("asset-target", "revision-target", target_slide_id, now, now),
        )
        conn.execute(
            """INSERT INTO slide_importance
               (slide_id, importance_score, page_role, needs_visual, status, updated_at)
               VALUES (?, 0.9, 'architecture', 0, 'completed', ?)""",
            (target_slide_id, now),
        )
        conn.execute(
            """INSERT INTO classification_values
               (asset_id, field_name, value, confidence, source, review_state, created_at)
               VALUES ('asset-target', 'page_role', 'architecture', 1.0, 'manual', 'approved', ?)""",
            (now,),
        )
        index_from_slides(conn)

        payload = SearchService(conn).search_v2(
            "shared architecture",
            top_k=10,
            filters={
                "industry": ["automotive", "financial_services"],
                "scenario": ["proposal"],
                "narrative_role": ["solution_architecture"],
                "page_role": ["architecture"],
                "review_state": ["approved"],
                "include_versions": False,
            },
        )

        candidates = payload["data"]["candidates"]
        assert [candidate["provenance"]["legacy_slide_id"] for candidate in candidates] == [target_slide_id]

    def test_search_v2_rejects_unknown_filter_instead_of_ignoring_it(self, tmp_path: Path):
        conn = connect(tmp_path / "index.db")
        init_db(conn)

        with pytest.raises(ValueError, match=r"Unsupported search filter\(s\): confidentiality"):
            SearchService(conn).search_v2(
                "architecture",
                filters={"confidentiality": ["public"]},
            )

    def test_search_v2_expands_recall_until_filtered_candidate_is_found(self, tmp_path: Path):
        conn = connect(tmp_path / "index.db")
        init_db(conn)
        target_slide_id = 0
        for ordinal in range(1, 26):
            _, slide_id = _add_search_slide(
                conn,
                tmp_path,
                ordinal,
                industry="target" if ordinal == 25 else "other",
                body_text=("needle " + "filler " * 100 if ordinal == 25 else "needle needle needle"),
            )
            if ordinal == 25:
                target_slide_id = slide_id
        index_from_slides(conn)
        assert target_slide_id not in {result.slide_id for result in lexical_search(conn, "needle", top_k=20)}

        payload = SearchService(conn).search_v2(
            "needle",
            top_k=1,
            filters={"industry": ["target"]},
        )

        candidates = payload["data"]["candidates"]
        assert candidates[0]["provenance"]["legacy_slide_id"] == target_slide_id
        assert payload["data"]["trace"]["lexical_backend"]["candidate_count"] == 25

    @pytest.mark.parametrize("profile_name", ["default", "deck_master"])
    def test_search_v2_profile_excludes_non_representative_versions_by_default(
        self,
        tmp_path: Path,
        profile_name: str,
    ):
        conn = connect(tmp_path / "index.db")
        init_db(conn)
        representative_presentation_id, representative_slide_id = _add_search_slide(conn, tmp_path, 1)
        old_presentation_id, old_slide_id = _add_search_slide(conn, tmp_path, 2)
        conn.execute(
            """INSERT INTO deck_families
               (family_key, representative_presentation_id, presentation_count)
               VALUES ('family-1', ?, 2)""",
            (representative_presentation_id,),
        )
        family_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.executemany(
            """INSERT INTO presentation_versions
               (presentation_id, deck_family_id, version_role, version_rank, is_representative)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (representative_presentation_id, family_id, "final", 2, 1),
                (old_presentation_id, family_id, "draft", 1, 0),
            ],
        )
        index_from_slides(conn)

        service = SearchService(conn)
        default_payload = service.search_v2("shared architecture", top_k=10, profile_name=profile_name)
        all_versions_payload = service.search_v2(
            "shared architecture",
            top_k=10,
            profile_name=profile_name,
            filters={"include_versions": True},
        )

        default_ids = {candidate["provenance"]["legacy_slide_id"] for candidate in default_payload["data"]["candidates"]}
        all_version_ids = {candidate["provenance"]["legacy_slide_id"] for candidate in all_versions_payload["data"]["candidates"]}
        assert default_ids == {representative_slide_id}
        assert all_version_ids == {representative_slide_id, old_slide_id}


class TestAssetService:
    def test_get_asset_not_found(self):
        conn = _create_db()
        svc = AssetService(conn)
        result = svc.get_asset("nonexistent")
        assert result.success is False

    def test_get_asset_found(self):
        conn = _create_db()
        conn.execute("INSERT INTO slide_assets VALUES ('a1', 'slide', 'now', 'now', '{}')")
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
        assert result.data["embeddings_count"] == 0

    def test_services_available(self):
        conn = _create_db()
        svc = LibraryService(conn)
        assert isinstance(svc.search, SearchService)
        assert isinstance(svc.assets, AssetService)
        assert isinstance(svc.health, HealthService)
        assert isinstance(svc.review, ReviewService)
        assert isinstance(svc.jobs, JobService)

    def test_passes_settings_to_search_service(self, tmp_path: Path):
        conn = _create_db()
        settings = Settings(home_dir=tmp_path, embedding_provider="fake")

        svc = LibraryService(conn, settings)

        assert svc.search.search("architecture").success is True
