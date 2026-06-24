"""Asset health detectors and finding lifecycle (v1.7-G).

Runs health detectors on assets and manages the finding lifecycle:
detect → triage → resolve/dismiss → rescan.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class HealthDetector:
    """A health detector configuration."""

    name: str
    detector_type: str  # "duplicate" | "orphan" | "outdated" | "missing_metadata" | "empty_content"
    severity: str  # "info" | "warning" | "error" | "critical"
    enabled: bool = True
    description: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "detector_type": self.detector_type,
            "severity": self.severity,
            "enabled": self.enabled,
            "description": self.description,
        }


@dataclass(frozen=True)
class HealthReport:
    """A complete health report for the asset library."""

    generated_at: str
    total_assets: int
    detectors_run: int
    findings_created: int
    findings_resolved: int
    findings_by_severity: dict[str, int]
    findings_by_type: dict[str, int]

    def to_json(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "total_assets": self.total_assets,
            "detectors_run": self.detectors_run,
            "findings_created": self.findings_created,
            "findings_resolved": self.findings_resolved,
            "findings_by_severity": self.findings_by_severity,
            "findings_by_type": self.findings_by_type,
        }


# Built-in detectors
DEFAULT_DETECTORS = [
    HealthDetector("empty_content", "empty_content", "warning",
        description="Slides with no text content"),
    HealthDetector("orphan_asset", "orphan", "warning",
        description="Assets with no presentation link"),
    HealthDetector("missing_metadata", "missing_metadata", "info",
        description="Assets missing key metadata fields"),
    HealthDetector("high_duplicate_count", "duplicate", "info",
        description="Assets with many duplicates"),
]


def ensure_health_tables(conn: sqlite3.Connection) -> None:
    """Ensure health finding tables exist."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS health_findings (
            finding_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            finding_type TEXT NOT NULL,
            message TEXT NOT NULL,
            suggested_action TEXT,
            state TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        )"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_health_state ON health_findings(state)"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_health_severity ON health_findings(severity)"""
    )
    conn.commit()


def run_detector_empty_content(
    conn: sqlite3.Connection,
    *,
    severity: str = "warning",
) -> int:
    """Detect slides with empty text content."""
    ensure_health_tables(conn)
    cursor = conn.cursor()
    now = datetime.now(UTC).isoformat()
    count = 0

    cursor.execute(
        """SELECT id FROM slides
           WHERE text_content IS NULL OR text_content = '' OR TRIM(text_content) = ''"""
    )
    for (slide_id,) in cursor.fetchall():
        # Dedup: skip if an open finding already exists for this slide+type
        dedup = conn.execute(
            """SELECT 1 FROM health_findings
               WHERE asset_id = ? AND finding_type = 'empty_content' AND state = 'open'
               LIMIT 1""",
            (str(slide_id),),
        ).fetchone()
        if dedup:
            continue
        finding_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO health_findings
               (finding_id, asset_id, severity, finding_type, message,
                suggested_action, state, created_at)
               VALUES (?, ?, ?, 'empty_content', ?, ?, 'open', ?)""",
            (
                finding_id,
                str(slide_id),
                severity,
                f"Slide {slide_id} has no text content",
                "Run OCR/vision recognition or manually add text",
                now,
            ),
        )
        count += 1

    conn.commit()
    return count


def run_detector_orphan_assets(
    conn: sqlite3.Connection,
    *,
    severity: str = "warning",
) -> int:
    """Detect assets with no presentation link (orphans)."""
    ensure_health_tables(conn)
    cursor = conn.cursor()
    now = datetime.now(UTC).isoformat()
    count = 0

    cursor.execute(
        """SELECT id FROM slides
           WHERE presentation_id IS NULL
              OR presentation_id NOT IN (SELECT id FROM presentations)"""
    )
    for (slide_id,) in cursor.fetchall():
        # Dedup: skip if an open finding already exists for this slide+type
        dedup = conn.execute(
            """SELECT 1 FROM health_findings
               WHERE asset_id = ? AND finding_type = 'orphan' AND state = 'open'
               LIMIT 1""",
            (str(slide_id),),
        ).fetchone()
        if dedup:
            continue
        finding_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO health_findings
               (finding_id, asset_id, severity, finding_type, message,
                suggested_action, state, created_at)
               VALUES (?, ?, ?, 'orphan', ?, ?, 'open', ?)""",
            (
                finding_id,
                str(slide_id),
                severity,
                f"Slide {slide_id} has no valid presentation link",
                "Re-index source file or remove orphan record",
                now,
            ),
        )
        count += 1

    conn.commit()
    return count


def run_all_detectors(
    conn: sqlite3.Connection,
    *,
    detectors: list[HealthDetector] | None = None,
) -> HealthReport:
    """Run all enabled detectors and return a health report."""
    detectors = detectors or DEFAULT_DETECTORS
    enabled = [d for d in detectors if d.enabled]
    now = datetime.now(UTC).isoformat()
    total_created = 0

    for detector in enabled:
        if detector.detector_type == "empty_content":
            total_created += run_detector_empty_content(conn, severity=detector.severity)
        elif detector.detector_type == "orphan":
            total_created += run_detector_orphan_assets(conn, severity=detector.severity)

    # Count existing findings
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM slides")
    total_assets = cursor.fetchone()[0]

    cursor.execute(
        "SELECT severity, COUNT(*) FROM health_findings WHERE state = 'open' GROUP BY severity"
    )
    by_severity = dict(cursor.fetchall())

    cursor.execute(
        "SELECT finding_type, COUNT(*) FROM health_findings WHERE state = 'open' GROUP BY finding_type"
    )
    by_type = dict(cursor.fetchall())

    cursor.execute(
        "SELECT COUNT(*) FROM health_findings WHERE state = 'resolved'"
    )
    resolved = cursor.fetchone()[0]

    return HealthReport(
        generated_at=now,
        total_assets=total_assets,
        detectors_run=len(enabled),
        findings_created=total_created,
        findings_resolved=resolved,
        findings_by_severity=by_severity,
        findings_by_type=by_type,
    )


def resolve_finding(
    conn: sqlite3.Connection,
    finding_id: str,
    *,
    state: str = "resolved",
) -> bool:
    """Resolve or dismiss a health finding."""
    ensure_health_tables(conn)
    now = datetime.now(UTC).isoformat()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE health_findings SET state = ?, resolved_at = ? WHERE finding_id = ?",
        (state, now, finding_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_open_findings(
    conn: sqlite3.Connection,
    *,
    severity: str | None = None,
    finding_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    """Get open health findings, optionally filtered."""
    ensure_health_tables(conn)
    cursor = conn.cursor()

    conditions = ["state = 'open'"]
    params: list[Any] = []
    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if finding_type:
        conditions.append("finding_type = ?")
        params.append(finding_type)

    where = " AND ".join(conditions)
    params.append(limit)

    cursor.execute(
        f"""SELECT finding_id, asset_id, severity, finding_type, message,
                   suggested_action, created_at
            FROM health_findings
            WHERE {where}
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 1
                    WHEN 'error' THEN 2
                    WHEN 'warning' THEN 3
                    ELSE 4
                END,
                created_at DESC
            LIMIT ?""",
        params,
    )
    findings: list[dict[str, object]] = []
    for row in cursor.fetchall():
        findings.append({
            "finding_id": row[0],
            "asset_id": row[1],
            "severity": row[2],
            "finding_type": row[3],
            "message": row[4],
            "suggested_action": row[5],
            "created_at": row[6],
        })
    return findings
