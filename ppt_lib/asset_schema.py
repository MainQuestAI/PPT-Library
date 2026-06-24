"""Asset/Revision/Lineage schema for v1.7-A.

Extends the v1.5 identity model into a full asset/revision model with
lineage edges, classification, feedback, and health tracking.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlideAsset:
    """A logical slide asset that persists across revisions."""

    canonical_asset_id: str
    asset_type: str  # "slide" | "deck"
    created_at: str
    updated_at: str
    labels: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "canonical_asset_id": self.canonical_asset_id,
            "asset_type": self.asset_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "labels": self.labels,
        }


@dataclass(frozen=True)
class SlideRevision:
    """A specific content revision of a slide asset."""

    slide_revision_id: str
    canonical_asset_id: str
    fingerprint: str
    algorithm_version: str
    text_hash: str
    visual_hash: str | None
    layout_hash: str | None
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "slide_revision_id": self.slide_revision_id,
            "canonical_asset_id": self.canonical_asset_id,
            "fingerprint": self.fingerprint,
            "algorithm_version": self.algorithm_version,
            "text_hash": self.text_hash,
            "visual_hash": self.visual_hash,
            "layout_hash": self.layout_hash,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class LineageEdge:
    """A directed edge in the asset lineage graph."""

    edge_id: str
    source_asset_id: str
    target_asset_id: str
    edge_type: str  # "revision" | "copy" | "derived" | "superseded"
    confidence: float  # 0.0-1.0
    source: str  # "auto" | "manual"
    created_at: str
    metadata: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "source_asset_id": self.source_asset_id,
            "target_asset_id": self.target_asset_id,
            "edge_type": self.edge_type,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ClassificationValue:
    """A classification value with provenance."""

    asset_id: str
    field_name: str  # "page_archetype" | "narrative_role" | "industry" | ...
    value: str
    confidence: float
    source: str  # "deterministic" | "model" | "manual"
    review_state: str  # "pending" | "approved" | "rejected"
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "field_name": self.field_name,
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "review_state": self.review_state,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class FeedbackEvent:
    """A user feedback event on an asset."""

    event_id: str
    asset_id: str
    event_type: str  # "selected" | "rejected" | "approved" | "flagged"
    reason: str | None
    context: dict[str, object] = field(default_factory=dict)
    created_at: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "asset_id": self.asset_id,
            "event_type": self.event_type,
            "reason": self.reason,
            "context": self.context,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class HealthFinding:
    """A health finding for an asset."""

    finding_id: str
    asset_id: str
    severity: str  # "info" | "warning" | "error" | "critical"
    finding_type: str  # "duplicate" | "orphan" | "outdated" | "missing_metadata"
    message: str
    suggested_action: str | None
    state: str  # "open" | "resolved" | "dismissed"
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "asset_id": self.asset_id,
            "severity": self.severity,
            "finding_type": self.finding_type,
            "message": self.message,
            "suggested_action": self.suggested_action,
            "state": self.state,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------


def create_asset_schema_tables(conn: sqlite3.Connection) -> None:
    """Create v1.7 asset schema tables (schema version 6)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS slide_assets (
            canonical_asset_id TEXT PRIMARY KEY,
            asset_type TEXT NOT NULL DEFAULT 'slide',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            labels_json TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS slide_revisions (
            slide_revision_id TEXT PRIMARY KEY,
            canonical_asset_id TEXT NOT NULL REFERENCES slide_assets(canonical_asset_id),
            fingerprint TEXT NOT NULL,
            algorithm_version TEXT NOT NULL,
            text_hash TEXT NOT NULL DEFAULT '',
            visual_hash TEXT,
            layout_hash TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS lineage_edges (
            edge_id TEXT PRIMARY KEY,
            source_asset_id TEXT NOT NULL,
            target_asset_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            source TEXT NOT NULL DEFAULT 'auto',
            created_at TEXT NOT NULL,
            metadata_json TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS classification_values (
            asset_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            source TEXT NOT NULL DEFAULT 'deterministic',
            review_state TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            PRIMARY KEY (asset_id, field_name, source)
        );

        CREATE TABLE IF NOT EXISTS feedback_events (
            event_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            reason TEXT,
            context_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS health_findings (
            finding_id TEXT PRIMARY KEY,
            asset_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            finding_type TEXT NOT NULL,
            message TEXT NOT NULL,
            suggested_action TEXT,
            state TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_revisions_canonical
            ON slide_revisions(canonical_asset_id);
        CREATE INDEX IF NOT EXISTS idx_lineage_source
            ON lineage_edges(source_asset_id);
        CREATE INDEX IF NOT EXISTS idx_lineage_target
            ON lineage_edges(target_asset_id);
        CREATE INDEX IF NOT EXISTS idx_lineage_type
            ON lineage_edges(edge_type);
        CREATE INDEX IF NOT EXISTS idx_classification_asset
            ON classification_values(asset_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_asset
            ON feedback_events(asset_id);
        CREATE INDEX IF NOT EXISTS idx_health_asset
            ON health_findings(asset_id);
        CREATE INDEX IF NOT EXISTS idx_health_state
            ON health_findings(state);
        CREATE INDEX IF NOT EXISTS idx_health_severity
            ON health_findings(severity);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def upsert_slide_asset(
    conn: sqlite3.Connection,
    canonical_asset_id: str,
    *,
    asset_type: str = "slide",
    labels: dict[str, str] | None = None,
) -> SlideAsset:
    """Insert or update a slide asset."""
    import json
    now = datetime.now(UTC).isoformat()
    labels_json = json.dumps(labels or {})

    conn.execute(
        """INSERT INTO slide_assets (canonical_asset_id, asset_type, created_at, updated_at, labels_json)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(canonical_asset_id) DO UPDATE SET
               updated_at = excluded.updated_at,
               labels_json = excluded.labels_json""",
        (canonical_asset_id, asset_type, now, now, labels_json),
    )
    conn.commit()

    cursor = conn.cursor()
    cursor.execute(
        "SELECT created_at FROM slide_assets WHERE canonical_asset_id = ?",
        (canonical_asset_id,),
    )
    created = cursor.fetchone()[0]

    return SlideAsset(
        canonical_asset_id=canonical_asset_id,
        asset_type=asset_type,
        created_at=created,
        updated_at=now,
        labels=labels or {},
    )


def insert_slide_revision(
    conn: sqlite3.Connection,
    revision: SlideRevision,
) -> None:
    """Insert a slide revision."""
    conn.execute(
        """INSERT OR IGNORE INTO slide_revisions
           (slide_revision_id, canonical_asset_id, fingerprint, algorithm_version,
            text_hash, visual_hash, layout_hash, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            revision.slide_revision_id,
            revision.canonical_asset_id,
            revision.fingerprint,
            revision.algorithm_version,
            revision.text_hash,
            revision.visual_hash,
            revision.layout_hash,
            revision.created_at,
        ),
    )
    conn.commit()


def add_lineage_edge(
    conn: sqlite3.Connection,
    source_id: str,
    target_id: str,
    edge_type: str,
    *,
    confidence: float = 1.0,
    source: str = "auto",
    metadata: dict[str, object] | None = None,
) -> LineageEdge:
    """Add a lineage edge."""
    import json
    now = datetime.now(UTC).isoformat()
    edge_id = str(uuid.uuid4())

    conn.execute(
        """INSERT INTO lineage_edges
           (edge_id, source_asset_id, target_asset_id, edge_type,
            confidence, source, created_at, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            edge_id, source_id, target_id, edge_type,
            confidence, source, now, json.dumps(metadata or {}),
        ),
    )
    conn.commit()

    return LineageEdge(
        edge_id=edge_id,
        source_asset_id=source_id,
        target_asset_id=target_id,
        edge_type=edge_type,
        confidence=confidence,
        source=source,
        created_at=now,
        metadata=metadata or {},
    )


def get_lineage_edges(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    direction: str = "both",
    edge_type: str | None = None,
) -> list[LineageEdge]:
    """Get lineage edges for an asset."""
    import json
    cursor = conn.cursor()

    conditions: list[str] = []
    params: list[Any] = []

    if direction in ("outgoing", "both"):
        conditions.append("source_asset_id = ?")
        params.append(asset_id)
    if direction in ("incoming", "both"):
        conditions.append("target_asset_id = ?")
        params.append(asset_id)

    if direction == "both":
        where = f"({' OR '.join(conditions[:2])})"
    else:
        where = conditions[0]

    if edge_type:
        where += " AND edge_type = ?"
        params.append(edge_type)

    cursor.execute(
        f"""SELECT edge_id, source_asset_id, target_asset_id, edge_type,
                   confidence, source, created_at, metadata_json
            FROM lineage_edges WHERE {where}
            ORDER BY created_at DESC""",
        params,
    )

    edges: list[LineageEdge] = []
    for row in cursor.fetchall():
        edges.append(LineageEdge(
            edge_id=row[0],
            source_asset_id=row[1],
            target_asset_id=row[2],
            edge_type=row[3],
            confidence=row[4],
            source=row[5],
            created_at=row[6],
            metadata=json.loads(row[7]) if row[7] else {},
        ))
    return edges


def add_feedback_event(
    conn: sqlite3.Connection,
    asset_id: str,
    event_type: str,
    *,
    reason: str | None = None,
    context: dict[str, object] | None = None,
) -> FeedbackEvent:
    """Record a feedback event."""
    import json
    now = datetime.now(UTC).isoformat()
    event_id = str(uuid.uuid4())

    conn.execute(
        """INSERT INTO feedback_events
           (event_id, asset_id, event_type, reason, context_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_id, asset_id, event_type, reason, json.dumps(context or {}), now),
    )
    conn.commit()

    return FeedbackEvent(
        event_id=event_id,
        asset_id=asset_id,
        event_type=event_type,
        reason=reason,
        context=context or {},
        created_at=now,
    )


def get_feedback_aggregates(
    conn: sqlite3.Connection,
    asset_id: str,
) -> dict[str, int]:
    """Get feedback event counts by type for an asset."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT event_type, COUNT(*) FROM feedback_events WHERE asset_id = ? GROUP BY event_type",
        (asset_id,),
    )
    return dict(cursor.fetchall())


def add_health_finding(
    conn: sqlite3.Connection,
    asset_id: str,
    severity: str,
    finding_type: str,
    message: str,
    *,
    suggested_action: str | None = None,
) -> HealthFinding:
    """Record a health finding."""
    now = datetime.now(UTC).isoformat()
    finding_id = str(uuid.uuid4())

    conn.execute(
        """INSERT INTO health_findings
           (finding_id, asset_id, severity, finding_type, message,
            suggested_action, state, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'open', ?)""",
        (finding_id, asset_id, severity, finding_type, message, suggested_action, now),
    )
    conn.commit()

    return HealthFinding(
        finding_id=finding_id,
        asset_id=asset_id,
        severity=severity,
        finding_type=finding_type,
        message=message,
        suggested_action=suggested_action,
        state="open",
        created_at=now,
    )


def resolve_health_finding(
    conn: sqlite3.Connection,
    finding_id: str,
    state: str = "resolved",
) -> None:
    """Resolve or dismiss a health finding."""
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE health_findings SET state = ?, resolved_at = ? WHERE finding_id = ?",
        (state, now, finding_id),
    )
    conn.commit()


def get_health_summary(conn: sqlite3.Connection) -> dict[str, int]:
    """Get health finding counts by severity and state."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT severity, state, COUNT(*) FROM health_findings GROUP BY severity, state"
    )
    summary: dict[str, int] = {}
    for severity, state, count in cursor.fetchall():
        summary[f"{severity}_{state}"] = count
    return summary
