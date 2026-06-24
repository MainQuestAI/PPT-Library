"""Server-Sent Events for real-time job and health monitoring (v1.8-F).

Provides SSE generators for streaming job progress and health findings
to the workbench dashboard.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class SSEEvent:
    """A single Server-Sent Event."""

    event: str
    data: dict[str, object]
    event_id: str | None = None
    retry_ms: int | None = None

    def format(self) -> str:
        """Format as SSE wire format."""
        lines: list[str] = []
        if self.event_id:
            lines.append(f"id: {self.event_id}")
        if self.event:
            lines.append(f"event: {self.event}")
        if self.retry_ms is not None:
            lines.append(f"retry: {self.retry_ms}")
        lines.append(f"data: {json.dumps(self.data)}")
        lines.append("")
        lines.append("")
        return "\n".join(lines)


def generate_job_events(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    poll_interval: float = 1.0,
    max_events: int = 1000,
    max_polls: int | None = None,
) -> Generator[SSEEvent, None, None]:
    """Generate SSE events for a job's progress.

    Yields events until the job reaches a terminal state or ``max_polls``
    iterations (defaults to ``max_events``) to guarantee termination even
    when job status is stable.
    """
    from ppt_lib.jobs import JobEngine

    engine = JobEngine(conn)
    event_count = 0
    poll_count = 0
    last_status = ""
    poll_limit = max_polls if max_polls is not None else max_events

    while poll_count < poll_limit:
        poll_count += 1
        job = engine.get(job_id)
        if not job:
            yield SSEEvent(
                event="error",
                data={"error": "job_not_found", "job_id": job_id},
            )
            return

        # Emit progress event if status changed or progress updated
        status_key = f"{job.status}:{job.completed_units}:{job.current_stage}"
        if status_key != last_status:
            last_status = status_key
            yield SSEEvent(
                event="job.progress",
                data={
                    "job_id": job.job_id,
                    "status": job.status,
                    "current_stage": job.current_stage or "",
                    "completed_units": job.completed_units,
                    "total_units": job.total_units,
                    "failed_units": job.failed_units,
                    "progress_pct": round(job.progress_pct, 1),
                    "cancel_requested": job.cancel_requested,
                },
                event_id=str(event_count),
            )
            event_count += 1

        # Terminal state — emit final event and stop
        if job.is_terminal:
            yield SSEEvent(
                event="job.completed" if job.status == "completed" else f"job.{job.status}",
                data={
                    "job_id": job.job_id,
                    "status": job.status,
                    "completed_units": job.completed_units,
                    "total_units": job.total_units,
                    "failed_units": job.failed_units,
                    "finished_at": job.finished_at or "",
                    "error": job.error_json,
                },
                event_id=str(event_count),
            )
            return

        time.sleep(poll_interval)


def generate_health_stream(
    conn: sqlite3.Connection,
    *,
    poll_interval: float = 5.0,
    max_events: int = 100,
    max_polls: int | None = None,
) -> Generator[SSEEvent, None, None]:
    """Generate SSE events for health findings updates.

    ``max_polls`` is a hard limit on poll iterations (defaults to ``max_events``)
    so the generator always terminates even when findings count is stable.
    """
    event_count = 0
    poll_count = 0
    last_count = -1
    poll_limit = max_polls if max_polls is not None else max_events

    while poll_count < poll_limit:
        poll_count += 1
        try:
            from ppt_lib.asset_health import get_open_findings
            findings = get_open_findings(conn, limit=200)
            current_count = len(findings)

            if current_count != last_count:
                last_count = current_count
                severity_counts: dict[str, int] = {}
                for f in findings:
                    sev_raw = f.get("severity", "unknown")
                    sev = str(sev_raw) if sev_raw else "unknown"
                    severity_counts[sev] = severity_counts.get(sev, 0) + 1

                yield SSEEvent(
                    event="health.update",
                    data={
                        "open_findings": current_count,
                        "by_severity": severity_counts,
                        "generated_at": datetime.now(UTC).isoformat(),
                    },
                    event_id=str(event_count),
                )
                event_count += 1
        except Exception as exc:
            yield SSEEvent(
                event="health.error",
                data={"error": str(exc)},
                event_id=str(event_count),
            )
            event_count += 1

        time.sleep(poll_interval)


def format_sse_stream(events: Generator[SSEEvent, None, None]) -> str:
    """Format a generator of SSE events into a complete string.

    Useful for testing; production use would stream incrementally.
    """
    return "".join(event.format() for event in events)
