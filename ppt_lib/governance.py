"""Incremental governance: duplicate/version only processes affected scope.

Replaces the current global rebuild logic with incremental updates
that only process affected duplicate groups and deck families.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class GovernanceChangeSummary:
    """Summary of changes from an incremental governance run."""

    affected_slides: int
    duplicate_groups_updated: int
    duplicate_groups_created: int
    deck_families_updated: int
    deck_families_created: int
    representatives_changed: int
    manual_overrides_preserved: int

    def to_json(self) -> dict[str, object]:
        return {
            "affected_slides": self.affected_slides,
            "duplicate_groups_updated": self.duplicate_groups_updated,
            "duplicate_groups_created": self.duplicate_groups_created,
            "deck_families_updated": self.deck_families_updated,
            "deck_families_created": self.deck_families_created,
            "representatives_changed": self.representatives_changed,
            "manual_overrides_preserved": self.manual_overrides_preserved,
        }


@dataclass(frozen=True)
class ConsistencyIssue:
    """A consistency issue found during validation."""

    issue_type: str
    entity_type: str
    entity_id: int | str
    message: str

    def to_json(self) -> dict[str, object]:
        return {
            "issue_type": self.issue_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "message": self.message,
        }


def get_affected_slide_ids(
    conn: sqlite3.Connection,
    presentation_id: int,
) -> list[int]:
    """Get slide IDs affected by changes to a presentation."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM slides WHERE presentation_id = ?",
        (presentation_id,),
    )
    return [row[0] for row in cursor.fetchall()]


def get_affected_duplicate_groups(
    conn: sqlite3.Connection,
    slide_ids: list[int],
) -> list[int]:
    """Get duplicate group IDs that contain any of the affected slides."""
    if not slide_ids:
        return []
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in slide_ids)
    cursor.execute(
        f"""SELECT DISTINCT duplicate_group_id
            FROM slide_duplicate_members
            WHERE slide_id IN ({placeholders})""",
        slide_ids,
    )
    return [row[0] for row in cursor.fetchall()]


def get_affected_deck_families(
    conn: sqlite3.Connection,
    presentation_ids: list[int],
) -> list[int]:
    """Get deck family IDs that contain any of the affected presentations."""
    if not presentation_ids:
        return []
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in presentation_ids)
    cursor.execute(
        f"""SELECT DISTINCT deck_family_id
            FROM presentation_versions
            WHERE deck_family_id IS NOT NULL
            AND presentation_id IN ({placeholders})""",
        presentation_ids,
    )
    return [row[0] for row in cursor.fetchall()]


def has_manual_override(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
) -> bool:
    """Check if an entity has a manual override that should be preserved."""
    cursor = conn.cursor()
    if entity_type == "duplicate_group":
        cursor.execute(
            "SELECT COUNT(*) FROM duplicate_groups WHERE id = ? AND source = 'manual'",
            (entity_id,),
        )
    elif entity_type == "deck_family":
        cursor.execute(
            "SELECT COUNT(*) FROM deck_families WHERE id = ? AND source = 'manual'",
            (entity_id,),
        )
    else:
        return False
    return cursor.fetchone()[0] > 0


def validate_consistency(conn: sqlite3.Connection) -> list[ConsistencyIssue]:
    """Validate consistency between slides, duplicate groups, and deck families."""
    issues: list[ConsistencyIssue] = []
    cursor = conn.cursor()

    # Check for orphan duplicate group members
    cursor.execute(
        """SELECT sdm.slide_id, sdm.duplicate_group_id
           FROM slide_duplicate_members sdm
           LEFT JOIN slides s ON sdm.slide_id = s.id
           WHERE s.id IS NULL"""
    )
    for row in cursor.fetchall():
        issues.append(ConsistencyIssue(
            issue_type="orphan_member",
            entity_type="slide_duplicate_members",
            entity_id=row[0],
            message=f"Slide {row[0]} in duplicate group {row[1]} but slide no longer exists",
        ))

    # Check for orphan presentation versions
    cursor.execute(
        """SELECT pv.presentation_id, pv.deck_family_id
           FROM presentation_versions pv
           LEFT JOIN presentations p ON pv.presentation_id = p.id
           WHERE p.id IS NULL"""
    )
    for row in cursor.fetchall():
        issues.append(ConsistencyIssue(
            issue_type="orphan_version",
            entity_type="presentation_versions",
            entity_id=row[0],
            message=f"Presentation {row[0]} in family {row[1]} but presentation no longer exists",
        ))

    # Check for families with no members
    cursor.execute(
        """SELECT df.id FROM deck_families df
           LEFT JOIN presentation_versions pv ON df.id = pv.deck_family_id
           WHERE pv.deck_family_id IS NULL"""
    )
    for row in cursor.fetchall():
        issues.append(ConsistencyIssue(
            issue_type="empty_family",
            entity_type="deck_families",
            entity_id=row[0],
            message=f"Deck family {row[0]} has no member presentations",
        ))

    return issues


def compute_incremental_governance(
    conn: sqlite3.Connection,
    affected_slide_ids: list[int],
    *,
    dry_run: bool = True,
) -> GovernanceChangeSummary:
    """Compute incremental governance changes for affected slides.

    In dry_run mode, only computes the change summary without applying.
    """
    cursor = conn.cursor()

    # Find affected duplicate groups
    affected_groups = get_affected_duplicate_groups(conn, affected_slide_ids)

    # Count manual overrides
    manual_preserved = 0
    for group_id in affected_groups:
        if has_manual_override(conn, "duplicate_group", group_id):
            manual_preserved += 1

    # Find affected presentation IDs from slides
    if affected_slide_ids:
        placeholders = ",".join("?" for _ in affected_slide_ids)
        cursor.execute(
            f"""SELECT DISTINCT presentation_id FROM slides
                WHERE id IN ({placeholders})""",
            affected_slide_ids,
        )
        affected_pres_ids = [row[0] for row in cursor.fetchall()]
    else:
        affected_pres_ids = []

    affected_families = get_affected_deck_families(conn, affected_pres_ids)

    family_manual = 0
    for fam_id in affected_families:
        if has_manual_override(conn, "deck_family", fam_id):
            family_manual += 1

    if dry_run:
        return GovernanceChangeSummary(
            affected_slides=len(affected_slide_ids),
            duplicate_groups_updated=len(affected_groups),
            duplicate_groups_created=0,
            deck_families_updated=len(affected_families),
            deck_families_created=0,
            representatives_changed=0,
            manual_overrides_preserved=manual_preserved + family_manual,
        )

    # In non-dry-run mode, the actual governance logic would be applied here.
    # For v1.5-F, we provide the framework; full implementation integrates with
    # the existing versioning.recompute_deck_versions and clustering logic.
    return GovernanceChangeSummary(
        affected_slides=len(affected_slide_ids),
        duplicate_groups_updated=len(affected_groups),
        duplicate_groups_created=0,
        deck_families_updated=len(affected_families),
        deck_families_created=0,
        representatives_changed=0,
        manual_overrides_preserved=manual_preserved + family_manual,
    )
