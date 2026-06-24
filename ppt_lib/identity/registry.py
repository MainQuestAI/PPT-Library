"""Identity registry: mapping between canonical IDs and legacy row IDs.

Manages the ``asset_identity_map`` table introduced in schema v5.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from ppt_lib.identity.fingerprint import FINGERPRINT_VERSION


@dataclass(frozen=True)
class IdentityMapping:
    """A single mapping between canonical and revision identity."""

    canonical_asset_id: str
    slide_revision_id: str
    legacy_slide_id: int | None
    identity_status: str  # resolved | needs_review | legacy_unresolved
    algorithm_version: str
    created_at: str
    updated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "canonical_asset_id": self.canonical_asset_id,
            "slide_revision_id": self.slide_revision_id,
            "legacy_slide_id": self.legacy_slide_id,
            "identity_status": self.identity_status,
            "algorithm_version": self.algorithm_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class IdentityCoverageReport:
    """Summary of identity mapping coverage."""

    total_slides: int
    resolved: int
    needs_review: int
    legacy_unresolved: int
    unmapped: int

    @property
    def coverage_pct(self) -> float:
        if self.total_slides == 0:
            return 0.0
        return (self.resolved / self.total_slides) * 100.0

    def to_json(self) -> dict[str, object]:
        return {
            "total_slides": self.total_slides,
            "resolved": self.resolved,
            "needs_review": self.needs_review,
            "legacy_unresolved": self.legacy_unresolved,
            "unmapped": self.unmapped,
            "coverage_pct": round(self.coverage_pct, 2),
        }


def get_identity_coverage(conn: sqlite3.Connection) -> IdentityCoverageReport:
    """Compute identity mapping coverage for the current database."""
    cursor = conn.cursor()

    # Total slides
    cursor.execute("SELECT COUNT(*) FROM slides")
    total_slides = cursor.fetchone()[0]

    # Check if identity table exists
    cursor.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='asset_identity_map'"
    )
    if cursor.fetchone()[0] == 0:
        return IdentityCoverageReport(
            total_slides=total_slides,
            resolved=0,
            needs_review=0,
            legacy_unresolved=0,
            unmapped=total_slides,
        )

    # Count by status
    cursor.execute(
        "SELECT identity_status, COUNT(*) FROM asset_identity_map GROUP BY identity_status"
    )
    status_counts: dict[str, int] = dict(cursor.fetchall())

    resolved = status_counts.get("resolved", 0)
    needs_review = status_counts.get("needs_review", 0)
    legacy_unresolved = status_counts.get("legacy_unresolved", 0)
    mapped = resolved + needs_review + legacy_unresolved
    unmapped = max(0, total_slides - mapped)

    return IdentityCoverageReport(
        total_slides=total_slides,
        resolved=resolved,
        needs_review=needs_review,
        legacy_unresolved=legacy_unresolved,
        unmapped=unmapped,
    )


def upsert_identity_mapping(
    conn: sqlite3.Connection,
    canonical_asset_id: str,
    slide_revision_id: str,
    legacy_slide_id: int | None,
    identity_status: str = "resolved",
    algorithm_version: str = FINGERPRINT_VERSION,
) -> IdentityMapping:
    """Insert or update an identity mapping."""
    now = datetime.now(UTC).isoformat()
    cursor = conn.cursor()

    # Check existing
    cursor.execute(
        "SELECT created_at FROM asset_identity_map "
        "WHERE canonical_asset_id = ? AND slide_revision_id = ?",
        (canonical_asset_id, slide_revision_id),
    )
    row = cursor.fetchone()
    created_at = row[0] if row else now

    conn.execute(
        """INSERT OR REPLACE INTO asset_identity_map
           (canonical_asset_id, slide_revision_id, legacy_slide_id,
            identity_status, algorithm_version, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_asset_id,
            slide_revision_id,
            legacy_slide_id,
            identity_status,
            algorithm_version,
            created_at,
            now,
        ),
    )

    return IdentityMapping(
        canonical_asset_id=canonical_asset_id,
        slide_revision_id=slide_revision_id,
        legacy_slide_id=legacy_slide_id,
        identity_status=identity_status,
        algorithm_version=algorithm_version,
        created_at=created_at,
        updated_at=now,
    )


def get_identity_by_revision(
    conn: sqlite3.Connection,
    slide_revision_id: str,
) -> IdentityMapping | None:
    """Look up identity by slide revision ID."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT canonical_asset_id, slide_revision_id, legacy_slide_id,
                  identity_status, algorithm_version, created_at, updated_at
           FROM asset_identity_map
           WHERE slide_revision_id = ?""",
        (slide_revision_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return IdentityMapping(*row)


def get_identity_by_canonical(
    conn: sqlite3.Connection,
    canonical_asset_id: str,
) -> list[IdentityMapping]:
    """Look up all revisions for a canonical asset."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT canonical_asset_id, slide_revision_id, legacy_slide_id,
                  identity_status, algorithm_version, created_at, updated_at
           FROM asset_identity_map
           WHERE canonical_asset_id = ?
           ORDER BY updated_at DESC""",
        (canonical_asset_id,),
    )
    return [IdentityMapping(*row) for row in cursor.fetchall()]


def export_identity_registry(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Export the full identity registry as JSON-serializable list."""
    cursor = conn.cursor()
    cursor.execute(
        """SELECT canonical_asset_id, slide_revision_id, legacy_slide_id,
                  identity_status, algorithm_version, created_at, updated_at
           FROM asset_identity_map
           ORDER BY canonical_asset_id, slide_revision_id"""
    )
    return [IdentityMapping(*row).to_json() for row in cursor.fetchall()]


def import_identity_registry(
    conn: sqlite3.Connection,
    data: list[dict[str, object]],
    *,
    dry_run: bool = False,
) -> int:
    """Import identity mappings from exported JSON data.

    Returns the number of records imported (or that would be imported).
    """
    count = 0
    for record in data:
        if not dry_run:
            raw_legacy_id = record.get("legacy_slide_id")
            legacy_id: int | None = None
            if isinstance(raw_legacy_id, int):
                legacy_id = raw_legacy_id
            elif isinstance(raw_legacy_id, str):
                legacy_id = int(raw_legacy_id)
            upsert_identity_mapping(
                conn,
                canonical_asset_id=str(record["canonical_asset_id"]),
                slide_revision_id=str(record["slide_revision_id"]),
                legacy_slide_id=legacy_id,
                identity_status=str(record.get("identity_status", "resolved")),
                algorithm_version=str(record.get("algorithm_version", FINGERPRINT_VERSION)),
            )
        count += 1
    return count
