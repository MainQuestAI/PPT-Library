"""Near duplicate classifier for slide assets (v1.7-C).

Multi-signal near duplicate detection using text similarity,
visual fingerprint similarity, and structural comparison.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DuplicatePair:
    """A candidate near-duplicate pair."""

    asset_id_a: str
    asset_id_b: str
    similarity: float
    signals: dict[str, object] = field(default_factory=dict)
    classification: str = "pending"  # pending | exact | near | client_variant | distinct
    source: str = "auto"  # auto | manual

    def to_json(self) -> dict[str, object]:
        return {
            "asset_id_a": self.asset_id_a,
            "asset_id_b": self.asset_id_b,
            "similarity": round(self.similarity, 4),
            "signals": {
                k: (round(v, 4) if isinstance(v, (int, float)) else v)
                for k, v in self.signals.items()
            },
            "classification": self.classification,
            "source": self.source,
        }


@dataclass(frozen=True)
class DuplicateGroup:
    """A group of near-duplicate assets."""

    group_id: str
    canonical_asset_id: str
    members: list[str]
    classification: str = "near"
    source: str = "auto"

    def to_json(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "canonical_asset_id": self.canonical_asset_id,
            "members": self.members,
            "classification": self.classification,
            "source": self.source,
        }


@dataclass(frozen=True)
class ClassifierMetrics:
    """Metrics for the duplicate classifier."""

    pairs_evaluated: int
    exact_matches: int
    near_duplicates: int
    client_variants: int
    distinct: int
    precision: float
    recall: float

    def to_json(self) -> dict[str, object]:
        return {
            "pairs_evaluated": self.pairs_evaluated,
            "exact_matches": self.exact_matches,
            "near_duplicates": self.near_duplicates,
            "client_variants": self.client_variants,
            "distinct": self.distinct,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
        }


# Default thresholds
EXACT_THRESHOLD = 0.95
NEAR_THRESHOLD = 0.80
CLIENT_VARIANT_THRESHOLD = 0.65


def classify_pair(
    similarity: float,
    *,
    exact_threshold: float = EXACT_THRESHOLD,
    near_threshold: float = NEAR_THRESHOLD,
    client_variant_threshold: float = CLIENT_VARIANT_THRESHOLD,
) -> str:
    """Classify a pair based on similarity score."""
    if similarity >= exact_threshold:
        return "exact"
    if similarity >= near_threshold:
        return "near"
    if similarity >= client_variant_threshold:
        return "client_variant"
    return "distinct"


def compute_text_similarity(text_a: str, text_b: str) -> float:
    """Compute text similarity using Jaccard coefficient on word sets."""
    if not text_a and not text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0

    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())

    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def compute_multi_signal_similarity(
    text_sim: float,
    visual_sim: float,
    *,
    text_weight: float = 0.5,
    visual_weight: float = 0.5,
) -> tuple[float, dict[str, float]]:
    """Combine text and visual similarity into a multi-signal score."""
    signals = {
        "text": text_sim,
        "visual": visual_sim,
    }
    combined = text_sim * text_weight + visual_sim * visual_weight
    return combined, signals


def _load_visual_hashes(conn: sqlite3.Connection) -> dict[int, str]:
    """Load visual_hash per slide_id from slide_revisions.

    Returns empty dict if the table is missing or no data, in which case
    near-duplicate detection degrades to text-only.
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT aim.legacy_slide_id, sr.visual_hash
               FROM slide_revisions sr
               JOIN asset_identity_map aim
                 ON aim.slide_revision_id = sr.slide_revision_id
               WHERE sr.visual_hash IS NOT NULL
                 AND aim.legacy_slide_id IS NOT NULL"""
        )
        return {row[0]: row[1] for row in cursor.fetchall() if row[0] is not None}
    except sqlite3.OperationalError:
        return {}


def detect_near_duplicates(
    conn: sqlite3.Connection,
    *,
    threshold: float = NEAR_THRESHOLD,
    limit: int = 1000,
) -> list[DuplicatePair]:
    """Detect near-duplicate pairs from the database.

    Combines text similarity (Jaccard) with visual fingerprint hash match.
    When visual hashes are unavailable, degrades to text-only and flags it.
    """
    cursor = conn.cursor()

    # Load visual hashes for multi-signal scoring (degrades gracefully)
    visual_hashes = _load_visual_hashes(conn)
    visual_available = bool(visual_hashes)

    # Get all slides with text content
    cursor.execute(
        """SELECT s.id, s.text_content, COALESCE(aim.canonical_asset_id, 'legacy_' || s.id)
           FROM slides s
           LEFT JOIN asset_identity_map aim ON aim.legacy_slide_id = s.id
           WHERE s.text_content IS NOT NULL AND s.text_content != ''
           LIMIT ?""",
        (limit,),
    )
    slides = cursor.fetchall()

    pairs: list[DuplicatePair] = []
    seen: set[tuple[str, str]] = set()

    for i, (id_a, text_a, asset_a) in enumerate(slides):
        for id_b, text_b, asset_b in slides[i + 1:]:
            if asset_a == asset_b:
                continue  # Same asset, skip

            pair_key = tuple(sorted([asset_a, asset_b]))
            if pair_key in seen:
                continue
            seen.add(pair_key)

            text_sim = compute_text_similarity(text_a, text_b)
            if text_sim < threshold:
                continue

            # Visual similarity: exact hash match = 1.0, else 0.0
            hash_a = visual_hashes.get(id_a)
            hash_b = visual_hashes.get(id_b)
            if visual_available and hash_a and hash_b:
                visual_sim = 1.0 if hash_a == hash_b else 0.0
            else:
                visual_sim = text_sim  # degrade: treat text as proxy

            combined, raw_signals = compute_multi_signal_similarity(text_sim, visual_sim)
            signals: dict[str, object] = dict(raw_signals)
            if not visual_available:
                signals["visual"] = "unavailable"
            classification = classify_pair(combined)
            pairs.append(DuplicatePair(
                asset_id_a=pair_key[0],
                asset_id_b=pair_key[1],
                similarity=combined,
                signals=signals,
                classification=classification,
            ))

    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs


def save_duplicate_pairs(
    conn: sqlite3.Connection,
    pairs: list[DuplicatePair],
) -> int:
    """Save duplicate pairs to the database."""
    import json
    import uuid
    from datetime import UTC, datetime

    count = 0
    now = datetime.now(UTC).isoformat()

    # Ensure table exists
    conn.execute(
        """CREATE TABLE IF NOT EXISTS near_duplicate_pairs (
            pair_id TEXT PRIMARY KEY,
            asset_id_a TEXT NOT NULL,
            asset_id_b TEXT NOT NULL,
            similarity REAL NOT NULL,
            signals_json TEXT DEFAULT '{}',
            classification TEXT NOT NULL DEFAULT 'pending',
            source TEXT NOT NULL DEFAULT 'auto',
            created_at TEXT NOT NULL
        )"""
    )

    for pair in pairs:
        pair_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO near_duplicate_pairs
               (pair_id, asset_id_a, asset_id_b, similarity, signals_json,
                classification, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pair_id, pair.asset_id_a, pair.asset_id_b,
                pair.similarity, json.dumps(pair.signals),
                pair.classification, pair.source, now,
            ),
        )
        count += 1

    conn.commit()
    return count


def get_review_queue(
    conn: sqlite3.Connection,
    *,
    classification: str = "pending",
    limit: int = 50,
) -> list[DuplicatePair]:
    """Get duplicate pairs pending review."""
    import json
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT asset_id_a, asset_id_b, similarity, signals_json,
                      classification, source
               FROM near_duplicate_pairs
               WHERE classification = ?
               ORDER BY similarity DESC
               LIMIT ?""",
            (classification, limit),
        )
    except sqlite3.OperationalError:
        return []

    pairs: list[DuplicatePair] = []
    for row in cursor.fetchall():
        pairs.append(DuplicatePair(
            asset_id_a=row[0],
            asset_id_b=row[1],
            similarity=row[2],
            signals=json.loads(row[3]) if row[3] else {},
            classification=row[4],
            source=row[5],
        ))
    return pairs


def manual_classify(
    conn: sqlite3.Connection,
    asset_id_a: str,
    asset_id_b: str,
    classification: str,
) -> bool:
    """Manually classify a duplicate pair. Returns True if a row was updated."""
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE near_duplicate_pairs
           SET classification = ?, source = 'manual'
           WHERE (asset_id_a = ? AND asset_id_b = ?)
              OR (asset_id_a = ? AND asset_id_b = ?)""",
        (classification, asset_id_a, asset_id_b, asset_id_b, asset_id_a),
    )
    conn.commit()
    return cursor.rowcount > 0
