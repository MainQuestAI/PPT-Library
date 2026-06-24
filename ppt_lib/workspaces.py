"""Multi-workspace isolation for team mode (v2.0-B).

Provides workspace management with strict data isolation:
metadata, vectors, blobs, audit logs are all workspace-scoped.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class Workspace:
    """A workspace with isolated data."""

    workspace_id: str
    name: str
    description: str = ""
    created_at: str = ""
    owner_user_id: str = ""
    slide_count: int = 0
    presentation_count: int = 0
    settings: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "owner_user_id": self.owner_user_id,
            "slide_count": self.slide_count,
            "presentation_count": self.presentation_count,
        }


def ensure_workspace_tables(conn: sqlite3.Connection) -> None:
    """Create workspace management tables."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            owner_user_id TEXT DEFAULT '',
            settings_json TEXT DEFAULT '{}'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS workspace_membership (
            workspace_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            joined_at TEXT NOT NULL,
            PRIMARY KEY (workspace_id, user_id)
        )"""
    )
    conn.commit()


def create_workspace(
    conn: sqlite3.Connection,
    name: str,
    *,
    description: str = "",
    owner_user_id: str = "",
) -> Workspace:
    """Create a new workspace."""
    ensure_workspace_tables(conn)
    workspace_id = f"ws_{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()

    conn.execute(
        """INSERT INTO workspaces
           (workspace_id, name, description, created_at, owner_user_id, settings_json)
           VALUES (?, ?, ?, ?, ?, '{}')""",
        (workspace_id, name, description, now, owner_user_id),
    )

    # Add owner as member
    if owner_user_id:
        conn.execute(
            """INSERT INTO workspace_membership (workspace_id, user_id, role, joined_at)
               VALUES (?, ?, 'owner', ?)""",
            (workspace_id, owner_user_id, now),
        )

    conn.commit()

    return Workspace(
        workspace_id=workspace_id,
        name=name,
        description=description,
        created_at=now,
        owner_user_id=owner_user_id,
    )


def list_workspaces(conn: sqlite3.Connection) -> list[Workspace]:
    """List all workspaces."""
    ensure_workspace_tables(conn)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT w.workspace_id, w.name, w.description, w.created_at,
                  w.owner_user_id
           FROM workspaces w
           ORDER BY w.created_at DESC"""
    )
    return [
        Workspace(
            workspace_id=row[0],
            name=row[1],
            description=row[2],
            created_at=row[3],
            owner_user_id=row[4],
        )
        for row in cursor.fetchall()
    ]


def get_workspace(conn: sqlite3.Connection, workspace_id: str) -> Workspace | None:
    """Get a workspace by ID."""
    ensure_workspace_tables(conn)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT workspace_id, name, description, created_at, owner_user_id
           FROM workspaces WHERE workspace_id = ?""",
        (workspace_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return Workspace(
        workspace_id=row[0],
        name=row[1],
        description=row[2],
        created_at=row[3],
        owner_user_id=row[4],
    )


def add_member(
    conn: sqlite3.Connection,
    workspace_id: str,
    user_id: str,
    *,
    role: str = "viewer",
) -> bool:
    """Add a user to a workspace."""
    ensure_workspace_tables(conn)
    now = datetime.now(UTC).isoformat()
    try:
        conn.execute(
            """INSERT INTO workspace_membership (workspace_id, user_id, role, joined_at)
               VALUES (?, ?, ?, ?)""",
            (workspace_id, user_id, role, now),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def remove_member(
    conn: sqlite3.Connection,
    workspace_id: str,
    user_id: str,
) -> bool:
    """Remove a user from a workspace."""
    ensure_workspace_tables(conn)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM workspace_membership WHERE workspace_id = ? AND user_id = ?",
        (workspace_id, user_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_members(
    conn: sqlite3.Connection,
    workspace_id: str,
) -> list[dict[str, str]]:
    """Get all members of a workspace."""
    ensure_workspace_tables(conn)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT user_id, role, joined_at
           FROM workspace_membership
           WHERE workspace_id = ?
           ORDER BY joined_at""",
        (workspace_id,),
    )
    return [
        {"user_id": row[0], "role": row[1], "joined_at": row[2]}
        for row in cursor.fetchall()
    ]


def check_workspace_access(
    conn: sqlite3.Connection,
    workspace_id: str,
    user_id: str,
) -> str | None:
    """Check if a user has access to a workspace. Returns their role or None."""
    ensure_workspace_tables(conn)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT role FROM workspace_membership
           WHERE workspace_id = ? AND user_id = ?""",
        (workspace_id, user_id),
    )
    row = cursor.fetchone()
    return row[0] if row else None
