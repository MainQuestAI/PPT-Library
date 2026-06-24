"""Audit log for workbench operations (v1.8-G).

Records all write operations for traceability.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class AuditEntry:
    """A single audit log entry."""

    entry_id: str
    timestamp: str
    action: str
    entity_type: str
    entity_id: str
    actor: str
    details: dict[str, object]

    def to_json(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "timestamp": self.timestamp,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "actor": self.actor,
            "details": self.details,
        }


def ensure_audit_table(conn: sqlite3.Connection) -> None:
    """Create audit log table if not exists."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS audit_log (
            entry_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'system',
            details_json TEXT DEFAULT '{}'
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)"
    )
    conn.commit()


def log_action(
    conn: sqlite3.Connection,
    action: str,
    entity_type: str,
    entity_id: str,
    *,
    actor: str = "system",
    details: dict[str, object] | None = None,
) -> AuditEntry:
    """Record an audit log entry."""
    import json
    ensure_audit_table(conn)
    now = datetime.now(UTC).isoformat()
    entry_id = str(uuid.uuid4())

    conn.execute(
        """INSERT INTO audit_log
           (entry_id, timestamp, action, entity_type, entity_id, actor, details_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (entry_id, now, action, entity_type, entity_id, actor, json.dumps(details or {})),
    )
    conn.commit()

    return AuditEntry(
        entry_id=entry_id,
        timestamp=now,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        details=details or {},
    )


def get_audit_log(
    conn: sqlite3.Connection,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    limit: int = 50,
) -> list[AuditEntry]:
    """Query audit log entries with optional filters."""
    import json
    ensure_audit_table(conn)
    cursor = conn.cursor()

    conditions: list[str] = []
    params: list[Any] = []
    if entity_type:
        conditions.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        conditions.append("entity_id = ?")
        params.append(entity_id)
    if action:
        conditions.append("action = ?")
        params.append(action)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)

    cursor.execute(
        f"""SELECT entry_id, timestamp, action, entity_type, entity_id,
                   actor, details_json
            FROM audit_log{where}
            ORDER BY timestamp DESC LIMIT ?""",
        params,
    )

    entries: list[AuditEntry] = []
    for row in cursor.fetchall():
        entries.append(AuditEntry(
            entry_id=row[0],
            timestamp=row[1],
            action=row[2],
            entity_type=row[3],
            entity_id=row[4],
            actor=row[5],
            details=json.loads(row[6]) if row[6] else {},
        ))
    return entries


def get_audit_summary(conn: sqlite3.Connection) -> dict[str, object]:
    """Get summary statistics for audit log."""
    ensure_audit_table(conn)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM audit_log")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT action, COUNT(*) FROM audit_log GROUP BY action")
    by_action = dict(cursor.fetchall())

    cursor.execute("SELECT entity_type, COUNT(*) FROM audit_log GROUP BY entity_type")
    by_entity = dict(cursor.fetchall())

    cursor.execute("SELECT actor, COUNT(*) FROM audit_log GROUP BY actor")
    by_actor = dict(cursor.fetchall())

    return {
        "total_entries": total,
        "by_action": by_action,
        "by_entity_type": by_entity,
        "by_actor": by_actor,
    }
