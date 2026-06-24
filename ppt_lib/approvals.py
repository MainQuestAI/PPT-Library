"""Approval workflows for enterprise governance (v2.0-D).

Manages review requests, approvals, rejections, and promotions
with health and policy gate integration.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class ReviewType(StrEnum):
    EXPORT = "export"
    DELETE = "delete"
    PROMOTION = "promotion"
    CLASSIFICATION = "classification"
    SHARE = "share"


@dataclass(frozen=True)
class ReviewRequest:
    """A request for review/approval."""

    request_id: str
    review_type: ReviewType
    asset_id: str
    requester_id: str
    status: ApprovalStatus
    reason: str
    created_at: str
    reviewer_id: str | None = None
    reviewed_at: str | None = None
    review_comment: str | None = None

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {
            "request_id": self.request_id,
            "review_type": self.review_type,
            "asset_id": self.asset_id,
            "requester_id": self.requester_id,
            "status": self.status,
            "reason": self.reason,
            "created_at": self.created_at,
        }
        if self.reviewer_id:
            d["reviewer_id"] = self.reviewer_id
        if self.reviewed_at:
            d["reviewed_at"] = self.reviewed_at
        if self.review_comment:
            d["review_comment"] = self.review_comment
        return d


def ensure_review_tables(conn: sqlite3.Connection) -> None:
    """Create review workflow tables."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS review_requests (
            request_id TEXT PRIMARY KEY,
            review_type TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            requester_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            reviewer_id TEXT,
            reviewed_at TEXT,
            review_comment TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_status ON review_requests(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_review_asset ON review_requests(asset_id)"
    )
    conn.commit()


def create_review_request(
    conn: sqlite3.Connection,
    review_type: ReviewType,
    asset_id: str,
    requester_id: str,
    *,
    reason: str = "",
) -> ReviewRequest:
    """Create a new review request."""
    ensure_review_tables(conn)
    request_id = f"rev_{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC).isoformat()

    conn.execute(
        """INSERT INTO review_requests
           (request_id, review_type, asset_id, requester_id, status, reason, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
        (request_id, review_type, asset_id, requester_id, reason, now),
    )
    conn.commit()

    return ReviewRequest(
        request_id=request_id,
        review_type=review_type,
        asset_id=asset_id,
        requester_id=requester_id,
        status=ApprovalStatus.PENDING,
        reason=reason,
        created_at=now,
    )


def approve_request(
    conn: sqlite3.Connection,
    request_id: str,
    reviewer_id: str,
    *,
    comment: str = "",
) -> bool:
    """Approve a pending review request."""
    ensure_review_tables(conn)
    now = datetime.now(UTC).isoformat()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE review_requests
           SET status = 'approved', reviewer_id = ?, reviewed_at = ?, review_comment = ?
           WHERE request_id = ? AND status = 'pending'""",
        (reviewer_id, now, comment, request_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def reject_request(
    conn: sqlite3.Connection,
    request_id: str,
    reviewer_id: str,
    *,
    comment: str = "",
) -> bool:
    """Reject a pending review request."""
    ensure_review_tables(conn)
    now = datetime.now(UTC).isoformat()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE review_requests
           SET status = 'rejected', reviewer_id = ?, reviewed_at = ?, review_comment = ?
           WHERE request_id = ? AND status = 'pending'""",
        (reviewer_id, now, comment, request_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def revoke_request(
    conn: sqlite3.Connection,
    request_id: str,
) -> bool:
    """Revoke a previously approved request."""
    ensure_review_tables(conn)
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE review_requests
           SET status = 'revoked'
           WHERE request_id = ? AND status = 'approved'""",
        (request_id,),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_pending_requests(
    conn: sqlite3.Connection,
    *,
    review_type: ReviewType | None = None,
    limit: int = 50,
) -> list[ReviewRequest]:
    """Get pending review requests."""
    ensure_review_tables(conn)
    cursor = conn.cursor()

    conditions = ["status = 'pending'"]
    params: list[Any] = []
    if review_type:
        conditions.append("review_type = ?")
        params.append(review_type)

    where = " AND ".join(conditions)
    params.append(limit)

    cursor.execute(
        f"""SELECT request_id, review_type, asset_id, requester_id, status,
                   reason, created_at, reviewer_id, reviewed_at, review_comment
            FROM review_requests WHERE {where}
            ORDER BY created_at DESC LIMIT ?""",
        params,
    )
    return _rows_to_requests(cursor.fetchall())


def get_request(
    conn: sqlite3.Connection,
    request_id: str,
) -> ReviewRequest | None:
    """Get a specific review request."""
    ensure_review_tables(conn)
    cursor = conn.cursor()
    cursor.execute(
        """SELECT request_id, review_type, asset_id, requester_id, status,
                  reason, created_at, reviewer_id, reviewed_at, review_comment
           FROM review_requests WHERE request_id = ?""",
        (request_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return _row_to_request(row)


def get_review_summary(conn: sqlite3.Connection) -> dict[str, object]:
    """Get summary of review requests."""
    ensure_review_tables(conn)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM review_requests")
    total = cursor.fetchone()[0]

    cursor.execute(
        "SELECT status, COUNT(*) FROM review_requests GROUP BY status"
    )
    by_status = dict(cursor.fetchall())

    cursor.execute(
        "SELECT review_type, COUNT(*) FROM review_requests GROUP BY review_type"
    )
    by_type = dict(cursor.fetchall())

    return {
        "total": total,
        "by_status": by_status,
        "by_type": by_type,
    }


def _row_to_request(row: tuple) -> ReviewRequest:
    return ReviewRequest(
        request_id=row[0],
        review_type=ReviewType(row[1]),
        asset_id=row[2],
        requester_id=row[3],
        status=ApprovalStatus(row[4]),
        reason=row[5],
        created_at=row[6],
        reviewer_id=row[7],
        reviewed_at=row[8],
        review_comment=row[9],
    )


def _rows_to_requests(rows: list[tuple]) -> list[ReviewRequest]:
    return [_row_to_request(row) for row in rows]
