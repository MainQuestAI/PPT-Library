"""Job engine: state machine, stages, checkpoints, idempotency.

Implements the core job lifecycle for long-running tasks like indexing.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# Standard pipeline stages
STANDARD_STAGES = [
    "discover",
    "extract",
    "render",
    "recognize",
    "embed",
    "stage",
    "commit",
    "govern",
    "finalize",
]


@dataclass(frozen=True)
class Job:
    """A job record."""

    job_id: str
    job_type: str
    idempotency_key: str | None
    pipeline_config_hash: str
    status: str
    current_stage: str | None
    total_units: int
    completed_units: int
    failed_units: int
    attempt: int
    cancel_requested: bool
    created_at: str
    updated_at: str | None
    started_at: str | None
    finished_at: str | None
    error_json: str | None
    warning_json: str | None

    @property
    def is_terminal(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    @property
    def progress_pct(self) -> float:
        if self.total_units == 0:
            return 0.0
        return (self.completed_units / self.total_units) * 100.0

    def to_json(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "job_type": self.job_type,
            "idempotency_key": self.idempotency_key,
            "pipeline_config_hash": self.pipeline_config_hash,
            "status": self.status,
            "current_stage": self.current_stage,
            "total_units": self.total_units,
            "completed_units": self.completed_units,
            "failed_units": self.failed_units,
            "attempt": self.attempt,
            "cancel_requested": self.cancel_requested,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress_pct": round(self.progress_pct, 2),
        }


@dataclass(frozen=True)
class JobStage:
    """A stage within a job."""

    stage_id: str
    job_id: str
    stage_name: str
    status: str
    started_at: str | None
    finished_at: str | None
    artifact_path: str | None
    error_json: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "stage_id": self.stage_id,
            "job_id": self.job_id,
            "stage_name": self.stage_name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "artifact_path": self.artifact_path,
        }


@dataclass(frozen=True)
class JobEvent:
    """An event emitted during job execution."""

    event_id: str
    job_id: str
    event_type: str
    occurred_at: str
    payload: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "job_id": self.job_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "payload": self.payload,
        }


class JobEngine:
    """Manages job lifecycle: create, start, progress, complete, cancel, resume."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # --- Create ---

    def create_job(
        self,
        job_type: str,
        pipeline_config_hash: str,
        *,
        idempotency_key: str | None = None,
        source_id: str | None = None,
        source_locator: str | None = None,
        source_content_hash: str | None = None,
    ) -> Job:
        """Create a new job. Returns existing job if idempotency key matches."""
        now = datetime.now(UTC).isoformat()
        job_id = str(uuid.uuid4())

        # Check idempotency
        if idempotency_key:
            existing = self.get_by_idempotency_key(idempotency_key)
            if existing and not existing.is_terminal:
                return existing
            if existing and existing.status == JobStatus.COMPLETED:
                return existing

        self._conn.execute(
            """INSERT INTO jobs
               (job_id, job_type, idempotency_key, source_id, source_locator,
                source_content_hash, pipeline_config_hash, status, attempt,
                created_at, cancel_requested, total_units, completed_units, failed_units)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 0, 0, 0, 0)""",
            (
                job_id,
                job_type,
                idempotency_key,
                source_id,
                source_locator,
                source_content_hash,
                pipeline_config_hash,
                JobStatus.CREATED,
                now,
            ),
        )
        self._conn.commit()
        self._emit_event(job_id, "job.created", {"job_type": job_type})
        return self.get(job_id)  # type: ignore[return-value]

    # --- Query ---

    def get(self, job_id: str) -> Job | None:
        cursor = self._conn.cursor()
        cursor.execute(
            """SELECT job_id, job_type, idempotency_key, pipeline_config_hash,
                      status, current_stage, total_units, completed_units,
                      failed_units, attempt, cancel_requested, created_at,
                      updated_at, started_at, finished_at, error_json, warning_json
               FROM jobs WHERE job_id = ?""",
            (job_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return Job(
            job_id=row[0],
            job_type=row[1],
            idempotency_key=row[2],
            pipeline_config_hash=row[3],
            status=row[4],
            current_stage=row[5],
            total_units=row[6],
            completed_units=row[7],
            failed_units=row[8],
            attempt=row[9],
            cancel_requested=bool(row[10]),
            created_at=row[11],
            updated_at=row[12],
            started_at=row[13],
            finished_at=row[14],
            error_json=row[15],
            warning_json=row[16],
        )

    def get_by_idempotency_key(self, key: str) -> Job | None:
        cursor = self._conn.cursor()
        cursor.execute(
            """SELECT job_id, job_type, idempotency_key, pipeline_config_hash,
                      status, current_stage, total_units, completed_units,
                      failed_units, attempt, cancel_requested, created_at,
                      updated_at, started_at, finished_at, error_json, warning_json
               FROM jobs WHERE idempotency_key = ?""",
            (key,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return Job(
            job_id=row[0],
            job_type=row[1],
            idempotency_key=row[2],
            pipeline_config_hash=row[3],
            status=row[4],
            current_stage=row[5],
            total_units=row[6],
            completed_units=row[7],
            failed_units=row[8],
            attempt=row[9],
            cancel_requested=bool(row[10]),
            created_at=row[11],
            updated_at=row[12],
            started_at=row[13],
            finished_at=row[14],
            error_json=row[15],
            warning_json=row[16],
        )

    def list_jobs(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 50,
    ) -> list[Job]:
        cursor = self._conn.cursor()
        query = """SELECT job_id, job_type, idempotency_key, pipeline_config_hash,
                          status, current_stage, total_units, completed_units,
                          failed_units, attempt, cancel_requested, created_at,
                          updated_at, started_at, finished_at, error_json, warning_json
                   FROM jobs"""
        conditions: list[str] = []
        params: list[Any] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if job_type:
            conditions.append("job_type = ?")
            params.append(job_type)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, params)
        return [
            Job(
                job_id=row[0],
                job_type=row[1],
                idempotency_key=row[2],
                pipeline_config_hash=row[3],
                status=row[4],
                current_stage=row[5],
                total_units=row[6],
                completed_units=row[7],
                failed_units=row[8],
                attempt=row[9],
                cancel_requested=bool(row[10]),
                created_at=row[11],
                updated_at=row[12],
                started_at=row[13],
                finished_at=row[14],
                error_json=row[15],
                warning_json=row[16],
            )
            for row in cursor.fetchall()
        ]

    # --- Lifecycle ---

    def start_job(self, job_id: str) -> Job:
        """Transition from created to running."""
        job = self.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        if job.status != JobStatus.CREATED:
            raise ValueError(f"Can only start jobs in 'created' state, current: {job.status}")
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE jobs SET status = ?, started_at = ?, updated_at = ? WHERE job_id = ?",
            (JobStatus.RUNNING, now, now, job_id),
        )
        self._conn.commit()
        self._emit_event(job_id, "job.started", {})
        return self.get(job_id)  # type: ignore[return-value]

    def set_total_units(self, job_id: str, total: int) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE jobs SET total_units = ?, updated_at = ? WHERE job_id = ?",
            (total, now, job_id),
        )
        self._conn.commit()

    def advance_progress(self, job_id: str, *, completed: int = 0, failed: int = 0) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """UPDATE jobs
               SET completed_units = completed_units + ?,
                   failed_units = failed_units + ?,
                   updated_at = ?
               WHERE job_id = ?""",
            (completed, failed, now, job_id),
        )
        self._conn.commit()

    def set_stage(self, job_id: str, stage_name: str) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE jobs SET current_stage = ?, updated_at = ? WHERE job_id = ?",
            (stage_name, now, job_id),
        )
        self._conn.commit()

    def complete_job(self, job_id: str) -> Job:
        job = self.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        if job.status != JobStatus.RUNNING:
            raise ValueError(f"Can only complete jobs in 'running' state, current: {job.status}")
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE jobs SET status = ?, finished_at = ?, updated_at = ? WHERE job_id = ?",
            (JobStatus.COMPLETED, now, now, job_id),
        )
        self._conn.commit()
        self._emit_event(job_id, "job.completed", {})
        return self.get(job_id)  # type: ignore[return-value]

    def fail_job(self, job_id: str, error: str, *, error_details: dict[str, object] | None = None) -> Job:
        job = self.get(job_id)
        if not job:
            raise ValueError(f"Job not found: {job_id}")
        if job.status != JobStatus.RUNNING:
            raise ValueError(f"Can only fail jobs in 'running' state, current: {job.status}")
        now = datetime.now(UTC).isoformat()
        error_json = json.dumps({"error": error, "details": error_details or {}})
        self._conn.execute(
            """UPDATE jobs
               SET status = ?, finished_at = ?, updated_at = ?, error_json = ?
               WHERE job_id = ?""",
            (JobStatus.FAILED, now, now, error_json, job_id),
        )
        self._conn.commit()
        self._emit_event(job_id, "job.failed", {"error": error})
        return self.get(job_id)  # type: ignore[return-value]

    def request_cancel(self, job_id: str) -> Job:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE job_id = ?",
            (now, job_id),
        )
        self._conn.commit()
        self._emit_event(job_id, "job.cancel_requested", {})
        return self.get(job_id)  # type: ignore[return-value]

    def cancel_job(self, job_id: str) -> Job:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """UPDATE jobs
               SET status = ?, cancel_requested = 1, finished_at = ?, updated_at = ?
               WHERE job_id = ?""",
            (JobStatus.CANCELLED, now, now, job_id),
        )
        self._conn.commit()
        self._emit_event(job_id, "job.cancelled", {})
        return self.get(job_id)  # type: ignore[return-value]

    def retry_job(self, job_id: str) -> Job:
        """Retry a failed job by incrementing attempt and resetting status."""
        now = datetime.now(UTC).isoformat()
        job = self.get(job_id)
        if job is None:
            raise ValueError(f"Job not found: {job_id}")
        if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            raise ValueError(f"Can only retry failed or cancelled jobs, current status: {job.status}")

        self._conn.execute(
            """UPDATE jobs
               SET status = ?, attempt = attempt + 1, started_at = ?,
                   finished_at = NULL, cancel_requested = 0,
                   error_json = NULL, updated_at = ?
               WHERE job_id = ?""",
            (JobStatus.RUNNING, now, now, job_id),
        )
        self._conn.commit()
        self._emit_event(job_id, "job.retried", {"attempt": job.attempt + 1})
        return self.get(job_id)  # type: ignore[return-value]

    def check_cancel(self, job_id: str) -> bool:
        """Check if cancel has been requested. Returns True if cancel requested."""
        job = self.get(job_id)
        if job is None:
            return True
        return job.cancel_requested

    # --- Stages ---

    def start_stage(self, job_id: str, stage_name: str) -> JobStage:
        now = datetime.now(UTC).isoformat()
        stage_id = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO job_stages
               (stage_id, job_id, stage_name, status, started_at)
               VALUES (?, ?, ?, ?, ?)""",
            (stage_id, job_id, stage_name, StageStatus.RUNNING, now),
        )
        self._conn.execute(
            "UPDATE jobs SET current_stage = ?, updated_at = ? WHERE job_id = ?",
            (stage_name, now, job_id),
        )
        self._conn.commit()
        self._emit_event(job_id, "job.stage.started", {"stage": stage_name})
        return JobStage(
            stage_id=stage_id,
            job_id=job_id,
            stage_name=stage_name,
            status=StageStatus.RUNNING,
            started_at=now,
            finished_at=None,
            artifact_path=None,
            error_json=None,
        )

    def complete_stage(self, stage_id: str, *, artifact_path: str | None = None) -> None:
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """UPDATE job_stages
               SET status = ?, finished_at = ?, artifact_path = ?
               WHERE stage_id = ?""",
            (StageStatus.COMPLETED, now, artifact_path, stage_id),
        )
        self._conn.commit()

    def fail_stage(self, stage_id: str, error: str) -> None:
        now = datetime.now(UTC).isoformat()
        error_json = json.dumps({"error": error})
        self._conn.execute(
            """UPDATE job_stages
               SET status = ?, finished_at = ?, error_json = ?
               WHERE stage_id = ?""",
            (StageStatus.FAILED, now, error_json, stage_id),
        )
        self._conn.commit()

    def list_stages(self, job_id: str) -> list[JobStage]:
        cursor = self._conn.cursor()
        cursor.execute(
            """SELECT stage_id, job_id, stage_name, status, started_at,
                      finished_at, artifact_path, error_json
               FROM job_stages WHERE job_id = ?
               ORDER BY started_at""",
            (job_id,),
        )
        return [
            JobStage(
                stage_id=row[0],
                job_id=row[1],
                stage_name=row[2],
                status=row[3],
                started_at=row[4],
                finished_at=row[5],
                artifact_path=row[6],
                error_json=row[7],
            )
            for row in cursor.fetchall()
        ]

    # --- Events ---

    def list_events(self, job_id: str) -> list[JobEvent]:
        cursor = self._conn.cursor()
        cursor.execute(
            """SELECT event_id, job_id, event_type, occurred_at, payload_json
               FROM job_events WHERE job_id = ?
               ORDER BY occurred_at""",
            (job_id,),
        )
        events: list[JobEvent] = []
        for row in cursor.fetchall():
            payload = json.loads(row[4]) if row[4] else {}
            events.append(
                JobEvent(
                    event_id=row[0],
                    job_id=row[1],
                    event_type=row[2],
                    occurred_at=row[3],
                    payload=payload,
                )
            )
        return events

    def _emit_event(self, job_id: str, event_type: str, payload: dict[str, object]) -> None:
        now = datetime.now(UTC).isoformat()
        event_id = str(uuid.uuid4())
        try:
            self._conn.execute(
                """INSERT INTO job_events
                   (event_id, job_id, event_type, occurred_at, payload_json)
                   VALUES (?, ?, ?, ?, ?)""",
                (event_id, job_id, event_type, now, json.dumps(payload)),
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # Table might not exist yet
