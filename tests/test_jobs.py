"""Tests for job engine (1.5-E)."""

from __future__ import annotations

import sqlite3

import pytest

from ppt_lib.jobs import (
    STANDARD_STAGES,
    Job,
    JobEngine,
    JobStatus,
    StageStatus,
)


def _create_db() -> sqlite3.Connection:
    """Create in-memory DB with job tables."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            idempotency_key TEXT UNIQUE,
            source_id TEXT,
            source_locator TEXT,
            source_content_hash TEXT,
            pipeline_config_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'created',
            current_stage TEXT,
            total_units INTEGER DEFAULT 0,
            completed_units INTEGER DEFAULT 0,
            failed_units INTEGER DEFAULT 0,
            attempt INTEGER DEFAULT 1,
            cancel_requested INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            error_json TEXT,
            warning_json TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE job_stages (
            stage_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            stage_name TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            artifact_path TEXT,
            error_json TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE job_events (
            event_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_json TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE job_checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            stage_name TEXT NOT NULL,
            checkpoint_data_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE staged_assets (
            staged_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            slide_revision_id TEXT,
            asset_data_json TEXT NOT NULL,
            committed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )"""
    )
    return conn


class TestJobCreation:
    def test_create_job(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "config_hash_001")
        assert job.job_type == "index"
        assert job.status == JobStatus.CREATED
        assert job.attempt == 1
        assert job.total_units == 0

    def test_create_job_with_idempotency(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job1 = engine.create_job("index", "hash1", idempotency_key="key1")
        job2 = engine.create_job("index", "hash1", idempotency_key="key1")
        assert job1.job_id == job2.job_id

    def test_create_job_different_idempotency_keys(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job1 = engine.create_job("index", "hash1", idempotency_key="key1")
        job2 = engine.create_job("index", "hash2", idempotency_key="key2")
        assert job1.job_id != job2.job_id


class TestJobLifecycle:
    def test_start_job(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        started = engine.start_job(job.job_id)
        assert started.status == JobStatus.RUNNING
        assert started.started_at is not None

    def test_complete_job(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.start_job(job.job_id)
        completed = engine.complete_job(job.job_id)
        assert completed.status == JobStatus.COMPLETED
        assert completed.finished_at is not None

    def test_fail_job(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.start_job(job.job_id)
        failed = engine.fail_job(job.job_id, "test error")
        assert failed.status == JobStatus.FAILED
        assert failed.error_json is not None

    def test_cancel_job(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.start_job(job.job_id)
        engine.request_cancel(job.job_id)
        cancelled = engine.cancel_job(job.job_id)
        assert cancelled.status == JobStatus.CANCELLED
        assert cancelled.cancel_requested is True

    def test_retry_job(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.start_job(job.job_id)
        engine.fail_job(job.job_id, "test error")
        retried = engine.retry_job(job.job_id)
        assert retried.status == JobStatus.RUNNING
        assert retried.attempt == 2
        assert retried.error_json is None

    def test_retry_non_failed_raises(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.start_job(job.job_id)
        with pytest.raises(ValueError, match="Can only retry"):
            engine.retry_job(job.job_id)

    def test_check_cancel(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.start_job(job.job_id)
        assert engine.check_cancel(job.job_id) is False
        engine.request_cancel(job.job_id)
        assert engine.check_cancel(job.job_id) is True


class TestJobProgress:
    def test_set_total_units(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.set_total_units(job.job_id, 100)
        updated = engine.get(job.job_id)
        assert updated.total_units == 100  # type: ignore[union-attr]

    def test_advance_progress(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.set_total_units(job.job_id, 100)
        engine.advance_progress(job.job_id, completed=10, failed=1)
        updated = engine.get(job.job_id)
        assert updated.completed_units == 10  # type: ignore[union-attr]
        assert updated.failed_units == 1  # type: ignore[union-attr]

    def test_progress_pct(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.set_total_units(job.job_id, 100)
        engine.advance_progress(job.job_id, completed=50)
        updated = engine.get(job.job_id)
        assert updated.progress_pct == 50.0  # type: ignore[union-attr]

    def test_progress_pct_zero_total(self):
        job = Job(
            job_id="test", job_type="index", idempotency_key=None,
            pipeline_config_hash="h", status="created", current_stage=None,
            total_units=0, completed_units=0, failed_units=0, attempt=1,
            cancel_requested=False, created_at="now", updated_at=None,
            started_at=None, finished_at=None, error_json=None, warning_json=None,
        )
        assert job.progress_pct == 0.0


class TestJobStages:
    def test_start_and_complete_stage(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.start_job(job.job_id)
        stage = engine.start_stage(job.job_id, "extract")
        assert stage.status == StageStatus.RUNNING
        assert stage.stage_name == "extract"

        engine.complete_stage(stage.stage_id, artifact_path="/tmp/artifacts")
        stages = engine.list_stages(job.job_id)
        assert len(stages) == 1
        assert stages[0].status == StageStatus.COMPLETED
        assert stages[0].artifact_path == "/tmp/artifacts"

    def test_fail_stage(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.start_job(job.job_id)
        stage = engine.start_stage(job.job_id, "render")
        engine.fail_stage(stage.stage_id, "render timeout")
        stages = engine.list_stages(job.job_id)
        assert stages[0].status == StageStatus.FAILED

    def test_set_stage_updates_job(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.set_stage(job.job_id, "embed")
        updated = engine.get(job.job_id)
        assert updated.current_stage == "embed"  # type: ignore[union-attr]


class TestJobEvents:
    def test_events_emitted(self):
        conn = _create_db()
        engine = JobEngine(conn)
        job = engine.create_job("index", "hash1")
        engine.start_job(job.job_id)
        engine.start_stage(job.job_id, "extract")
        engine.complete_job(job.job_id)

        events = engine.list_events(job.job_id)
        event_types = [e.event_type for e in events]
        assert "job.created" in event_types
        assert "job.started" in event_types
        assert "job.stage.started" in event_types
        assert "job.completed" in event_types


class TestJobQueries:
    def test_list_jobs(self):
        conn = _create_db()
        engine = JobEngine(conn)
        engine.create_job("index", "hash1")
        engine.create_job("enrich", "hash2")
        jobs = engine.list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_by_status(self):
        conn = _create_db()
        engine = JobEngine(conn)
        j1 = engine.create_job("index", "hash1")
        engine.create_job("index", "hash2")
        engine.start_job(j1.job_id)
        engine.complete_job(j1.job_id)
        jobs = engine.list_jobs(status=JobStatus.COMPLETED)
        assert len(jobs) == 1
        assert jobs[0].job_id == j1.job_id

    def test_list_jobs_by_type(self):
        conn = _create_db()
        engine = JobEngine(conn)
        engine.create_job("index", "hash1")
        engine.create_job("enrich", "hash2")
        jobs = engine.list_jobs(job_type="index")
        assert len(jobs) == 1

    def test_get_nonexistent(self):
        conn = _create_db()
        engine = JobEngine(conn)
        assert engine.get("nonexistent") is None


class TestJobToJSON:
    def test_job_to_json(self):
        job = Job(
            job_id="j1", job_type="index", idempotency_key="key1",
            pipeline_config_hash="hash", status="running", current_stage="extract",
            total_units=100, completed_units=50, failed_units=2, attempt=1,
            cancel_requested=False, created_at="now", updated_at="now",
            started_at="now", finished_at=None, error_json=None, warning_json=None,
        )
        j = job.to_json()
        assert j["job_id"] == "j1"
        assert j["status"] == "running"
        assert j["progress_pct"] == 50.0

    def test_job_is_terminal(self):
        for status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            job = Job(
                job_id="j", job_type="t", idempotency_key=None,
                pipeline_config_hash="h", status=status.value, current_stage=None,
                total_units=0, completed_units=0, failed_units=0, attempt=1,
                cancel_requested=False, created_at="now", updated_at=None,
                started_at=None, finished_at=None, error_json=None, warning_json=None,
            )
            assert job.is_terminal

        for status in [JobStatus.CREATED, JobStatus.RUNNING]:
            job = Job(
                job_id="j", job_type="t", idempotency_key=None,
                pipeline_config_hash="h", status=status.value, current_stage=None,
                total_units=0, completed_units=0, failed_units=0, attempt=1,
                cancel_requested=False, created_at="now", updated_at=None,
                started_at=None, finished_at=None, error_json=None, warning_json=None,
            )
            assert not job.is_terminal


class TestStandardStages:
    def test_standard_stages_defined(self):
        assert len(STANDARD_STAGES) == 9
        assert "discover" in STANDARD_STAGES
        assert "extract" in STANDARD_STAGES
        assert "commit" in STANDARD_STAGES
        assert "finalize" in STANDARD_STAGES
