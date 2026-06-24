"""Classification and suggestion pipeline (v1.7-E).

Provides deterministic and model-based classification for slide assets
with provenance tracking and review state management.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Standard classification schema
CLASSIFICATION_FIELDS = [
    "page_archetype",   # title | content | diagram | chart | table | image | divider | appendix
    "narrative_role",   # problem | solution | evidence | proof | call_to_action | context
    "industry",         # technology | finance | healthcare | retail | manufacturing | ...
    "scenario",         # proposal | pitch | review | report | training | ...
    "page_role",        # cover | agenda | section_header | content | summary | appendix
    "client_type",      # enterprise | smb | startup | government | nonprofit
    "confidentiality",  # public | internal | confidential | restricted
]

# Deterministic classification rules (keyword-based)
ARCHETYPE_RULES: dict[str, list[str]] = {
    "title": ["title", "cover", "introduction", "welcome"],
    "diagram": ["architecture", "diagram", "flow", "process", "system"],
    "chart": ["chart", "graph", "metrics", "statistics", "growth"],
    "table": ["table", "comparison", "matrix", "grid"],
    "image": ["image", "photo", "screenshot", "visual"],
    "divider": ["section", "divider", "separator"],
    "appendix": ["appendix", "reference", "glossary", "notes"],
    "content": ["content", "details", "body", "description", "explanation"],
}

NARRATIVE_RULES: dict[str, list[str]] = {
    "problem": ["challenge", "problem", "issue", "pain", "gap", "risk"],
    "solution": ["solution", "approach", "strategy", "answer", "proposal"],
    "evidence": ["data", "evidence", "result", "case study", "proof", "metric"],
    "call_to_action": ["next step", "action", "recommendation", "timeline", "roadmap"],
    "context": ["background", "overview", "context", "landscape", "market"],
}


@dataclass(frozen=True)
class ClassificationSuggestion:
    """A classification suggestion with provenance."""

    asset_id: str
    field_name: str
    value: str
    confidence: float
    source: str  # "deterministic" | "model" | "manual"
    matched_keywords: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "field_name": self.field_name,
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "matched_keywords": self.matched_keywords,
        }


@dataclass(frozen=True)
class ClassificationBenchmark:
    """Classification accuracy metrics."""

    field_name: str
    total: int
    correct: int
    abstained: int

    @property
    def accuracy(self) -> float:
        evaluated = self.total - self.abstained
        return self.correct / evaluated if evaluated > 0 else 0.0

    def to_json(self) -> dict[str, object]:
        return {
            "field_name": self.field_name,
            "total": self.total,
            "correct": self.correct,
            "abstained": self.abstained,
            "accuracy": round(self.accuracy, 4),
        }


def classify_deterministic(
    text: str,
    *,
    asset_id: str = "",
) -> list[ClassificationSuggestion]:
    """Apply deterministic keyword-based classification rules.

    Returns suggestions for page_archetype and narrative_role.
    """
    suggestions: list[ClassificationSuggestion] = []
    text_lower = text.lower()

    # Page archetype
    best_archetype = "content"  # default
    best_count = 0
    matched_archetype: list[str] = []
    for archetype, keywords in ARCHETYPE_RULES.items():
        matched = [kw for kw in keywords if kw in text_lower]
        if len(matched) > best_count:
            best_count = len(matched)
            best_archetype = archetype
            matched_archetype = matched

    if best_count > 0:
        confidence = min(1.0, 0.3 + best_count * 0.15)
        suggestions.append(ClassificationSuggestion(
            asset_id=asset_id,
            field_name="page_archetype",
            value=best_archetype,
            confidence=confidence,
            source="deterministic",
            matched_keywords=matched_archetype,
        ))

    # Narrative role
    best_role = ""
    best_role_count = 0
    matched_role: list[str] = []
    for role, keywords in NARRATIVE_RULES.items():
        matched = [kw for kw in keywords if kw in text_lower]
        if len(matched) > best_role_count:
            best_role_count = len(matched)
            best_role = role
            matched_role = matched

    if best_role and best_role_count > 0:
        confidence = min(1.0, 0.3 + best_role_count * 0.15)
        suggestions.append(ClassificationSuggestion(
            asset_id=asset_id,
            field_name="narrative_role",
            value=best_role,
            confidence=confidence,
            source="deterministic",
            matched_keywords=matched_role,
        ))

    return suggestions


def classify_batch(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
    overwrite: bool = False,
) -> list[ClassificationSuggestion]:
    """Run deterministic classification on unclassified slides."""
    cursor = conn.cursor()
    all_suggestions: list[ClassificationSuggestion] = []

    # Ensure classification_values table exists for the NOT EXISTS subquery
    conn.execute(
        """CREATE TABLE IF NOT EXISTS classification_values (
            asset_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            source TEXT NOT NULL DEFAULT 'deterministic',
            review_state TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            PRIMARY KEY (asset_id, field_name, source)
        )"""
    )
    conn.commit()

    if overwrite:
        cursor.execute(
            """SELECT s.id, s.text_content, COALESCE(aim.canonical_asset_id, 'legacy_' || s.id)
               FROM slides s
               LEFT JOIN asset_identity_map aim ON aim.legacy_slide_id = s.id
               WHERE s.text_content IS NOT NULL AND s.text_content != ''
               LIMIT ?""",
            (limit,),
        )
    else:
        cursor.execute(
            """SELECT s.id, s.text_content, COALESCE(aim.canonical_asset_id, 'legacy_' || s.id)
               FROM slides s
               LEFT JOIN asset_identity_map aim ON aim.legacy_slide_id = s.id
               WHERE s.text_content IS NOT NULL AND s.text_content != ''
                 AND NOT EXISTS (
                     SELECT 1 FROM classification_values cv
                     WHERE cv.asset_id = COALESCE(aim.canonical_asset_id, 'legacy_' || s.id)
                       AND cv.source = 'deterministic'
                 )
               LIMIT ?""",
            (limit,),
        )

    for _slide_id, text, asset_id in cursor.fetchall():
        suggestions = classify_deterministic(text or "", asset_id=asset_id)
        all_suggestions.extend(suggestions)

    return all_suggestions


def save_classifications(
    conn: sqlite3.Connection,
    suggestions: list[ClassificationSuggestion],
) -> int:
    """Save classification suggestions to the database."""
    now = datetime.now(UTC).isoformat()
    count = 0

    # Ensure table exists
    conn.execute(
        """CREATE TABLE IF NOT EXISTS classification_values (
            asset_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            source TEXT NOT NULL DEFAULT 'deterministic',
            review_state TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            PRIMARY KEY (asset_id, field_name, source)
        )"""
    )

    for suggestion in suggestions:
        conn.execute(
            """INSERT INTO classification_values
               (asset_id, field_name, value, confidence, source, review_state, created_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?)
               ON CONFLICT(asset_id, field_name, source) DO UPDATE SET
                   value = excluded.value,
                   confidence = excluded.confidence,
                   review_state = 'pending',
                   created_at = excluded.created_at""",
            (
                suggestion.asset_id,
                suggestion.field_name,
                suggestion.value,
                suggestion.confidence,
                suggestion.source,
                now,
            ),
        )
        count += 1

    conn.commit()
    return count


def approve_classification(
    conn: sqlite3.Connection,
    asset_id: str,
    field_name: str,
    *,
    source: str = "deterministic",
) -> bool:
    """Approve a classification value."""
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE classification_values
           SET review_state = 'approved'
           WHERE asset_id = ? AND field_name = ? AND source = ?""",
        (asset_id, field_name, source),
    )
    conn.commit()
    return cursor.rowcount > 0


def reject_classification(
    conn: sqlite3.Connection,
    asset_id: str,
    field_name: str,
    *,
    source: str = "deterministic",
) -> bool:
    """Reject a classification value."""
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE classification_values
           SET review_state = 'rejected'
           WHERE asset_id = ? AND field_name = ? AND source = ?""",
        (asset_id, field_name, source),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_classification_status(
    conn: sqlite3.Connection,
) -> dict[str, object]:
    """Get classification coverage status."""
    cursor = conn.cursor()
    status: dict[str, object] = {}

    cursor.execute("SELECT COUNT(*) FROM slides")
    total = cursor.fetchone()[0]
    status["total_slides"] = total

    try:
        cursor.execute(
            "SELECT COUNT(DISTINCT asset_id) FROM classification_values"
        )
        classified = cursor.fetchone()[0]
        status["classified_slides"] = classified
        status["coverage_pct"] = round(classified / total * 100, 2) if total > 0 else 0.0

        cursor.execute(
            "SELECT review_state, COUNT(*) FROM classification_values GROUP BY review_state"
        )
        status["by_review_state"] = dict(cursor.fetchall())

        cursor.execute(
            "SELECT field_name, COUNT(*) FROM classification_values GROUP BY field_name"
        )
        status["by_field"] = dict(cursor.fetchall())
    except sqlite3.OperationalError:
        status["classified_slides"] = 0
        status["coverage_pct"] = 0.0

    return status
