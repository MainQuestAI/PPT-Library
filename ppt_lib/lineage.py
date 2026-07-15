"""Deck and slide lineage inference and management (v1.7-D).

Infers version, copy, and modification relationships between assets.
Supports manual confirm/reject and cycle detection.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from ppt_lib.asset_schema import add_lineage_edge, get_lineage_edges


@dataclass(frozen=True)
class LineageInference:
    """An inferred lineage relationship."""

    source_asset_id: str
    target_asset_id: str
    edge_type: str
    confidence: float
    evidence: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        return {
            "source_asset_id": self.source_asset_id,
            "target_asset_id": self.target_asset_id,
            "edge_type": self.edge_type,
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class LineagePath:
    """A path through the lineage graph."""

    asset_ids: list[str]
    edge_types: list[str]
    total_confidence: float

    def to_json(self) -> dict[str, object]:
        return {
            "asset_ids": self.asset_ids,
            "edge_types": self.edge_types,
            "total_confidence": round(self.total_confidence, 4),
        }


def infer_lineage_from_text_similarity(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    threshold: float = 0.7,
    max_results: int = 20,
) -> list[LineageInference]:
    """Infer lineage edges based on text similarity between slides.

    Slides with high text overlap are likely revisions or copies.
    """
    from ppt_lib.near_duplicate import compute_text_similarity

    cursor = conn.cursor()

    # Get the target slide's text
    cursor.execute(
        """SELECT s.id, s.text_content, COALESCE(aim.canonical_asset_id, 'legacy_' || s.id)
           FROM slides s
           LEFT JOIN asset_identity_map aim ON aim.legacy_slide_id = s.id
           WHERE COALESCE(aim.canonical_asset_id, 'legacy_' || s.id) = ?
           LIMIT 1""",
        (asset_id,),
    )
    target_row = cursor.fetchone()
    if not target_row:
        return []

    target_id, target_text, _ = target_row

    # Find similar slides
    cursor.execute(
        """SELECT s.id, s.text_content, COALESCE(aim.canonical_asset_id, 'legacy_' || s.id)
           FROM slides s
           LEFT JOIN asset_identity_map aim ON aim.legacy_slide_id = s.id
           WHERE s.text_content IS NOT NULL AND s.text_content != ''
           LIMIT ?""",
        (max_results * 5,),
    )

    inferences: list[LineageInference] = []
    for _slide_id, text, other_asset_id in cursor.fetchall():
        if other_asset_id == asset_id:
            continue

        sim = compute_text_similarity(target_text or "", text)
        if sim >= threshold:
            edge_type = "revision" if sim >= 0.9 else "derived" if sim >= 0.8 else "copy"
            inferences.append(LineageInference(
                source_asset_id=other_asset_id,
                target_asset_id=asset_id,
                edge_type=edge_type,
                confidence=sim,
                evidence={
                    "method": "text_similarity",
                    "text_similarity": round(sim, 4),
                },
            ))

    inferences.sort(key=lambda i: i.confidence, reverse=True)
    return inferences[:max_results]


def apply_inferred_lineage(
    conn: sqlite3.Connection,
    inferences: list[LineageInference],
    *,
    min_confidence: float = 0.7,
) -> int:
    """Apply inferred lineage edges to the database."""
    count = 0
    for inference in inferences:
        if inference.confidence < min_confidence:
            continue
        add_lineage_edge(
            conn,
            inference.source_asset_id,
            inference.target_asset_id,
            inference.edge_type,
            confidence=inference.confidence,
            source="auto",
            metadata=inference.evidence,
        )
        count += 1
    return count


def detect_cycles(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    max_depth: int = 10,
) -> list[LineagePath]:
    """Detect cycles in the lineage graph starting from an asset.

    Uses per-path membership check (``current in path``) instead of a shared
    visited set, so reconvergent paths are correctly explored.
    """
    cycles: list[LineagePath] = []

    def _dfs(current: str, path: list[str], edge_types: list[str], depth: int) -> None:
        if depth > max_depth:
            return
        if current in path:
            # Found a cycle: path from cycle_start back to current
            cycle_start = path.index(current)
            cycle_path = path[cycle_start:] + [current]
            cycle_types = edge_types[cycle_start:]
            cycles.append(LineagePath(
                asset_ids=cycle_path,
                edge_types=cycle_types,
                total_confidence=1.0,
            ))
            return

        edges = get_lineage_edges(conn, current, direction="outgoing")
        for edge in edges:
            _dfs(
                edge.target_asset_id,
                path + [current],
                edge_types + [edge.edge_type],
                depth + 1,
            )

    _dfs(asset_id, [], [], 0)
    return cycles


def get_lineage_chain(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    direction: str = "both",
    max_depth: int = 5,
) -> list[LineagePath]:
    """Get all lineage paths from an asset."""
    paths: list[LineagePath] = []

    def _traverse(
        current: str,
        path: list[str],
        types: list[str],
        visited: set[str],
        depth: int,
        dir_: str,
    ) -> None:
        if depth > max_depth or current in visited:
            terminal_path = path + [current]
            if len(terminal_path) > 1:
                confidences = [1.0] * len(types)
                paths.append(LineagePath(
                    asset_ids=terminal_path,
                    edge_types=types,
                    total_confidence=sum(confidences) / len(confidences) if confidences else 0,
                ))
            return

        visited = visited | {current}
        edges = get_lineage_edges(conn, current, direction=dir_)
        if not edges and len(path) > 1:
            paths.append(LineagePath(
                asset_ids=path + [current] if current not in path else path,
                edge_types=types,
                total_confidence=1.0,
            ))
            return

        for edge in edges:
            next_id = edge.target_asset_id if dir_ == "outgoing" else edge.source_asset_id
            _traverse(
                next_id,
                path + [current],
                types + [edge.edge_type],
                visited,
                depth + 1,
                dir_,
            )

    if direction in ("outgoing", "both"):
        _traverse(asset_id, [], [], set(), 0, "outgoing")
    if direction in ("incoming", "both"):
        _traverse(asset_id, [], [], set(), 0, "incoming")

    return paths


def compute_change_summary(
    conn: sqlite3.Connection,
    asset_id_a: str,
    asset_id_b: str,
) -> dict[str, object]:
    """Compute a change summary between two related assets."""
    cursor = conn.cursor()

    # Get text content for both assets
    cursor.execute(
        """SELECT s.text_content FROM slides s
           LEFT JOIN asset_identity_map aim ON aim.legacy_slide_id = s.id
           WHERE COALESCE(aim.canonical_asset_id, 'legacy_' || s.id) = ?
           LIMIT 1""",
        (asset_id_a,),
    )
    row_a = cursor.fetchone()
    text_a = row_a[0] if row_a else ""

    cursor.execute(
        """SELECT s.text_content FROM slides s
           LEFT JOIN asset_identity_map aim ON aim.legacy_slide_id = s.id
           WHERE COALESCE(aim.canonical_asset_id, 'legacy_' || s.id) = ?
           LIMIT 1""",
        (asset_id_b,),
    )
    row_b = cursor.fetchone()
    text_b = row_b[0] if row_b else ""

    from ppt_lib.near_duplicate import compute_text_similarity
    similarity = compute_text_similarity(text_a or "", text_b or "")

    words_a = set((text_a or "").lower().split())
    words_b = set((text_b or "").lower().split())
    added = words_b - words_a
    removed = words_a - words_b

    return {
        "asset_a": asset_id_a,
        "asset_b": asset_id_b,
        "similarity": round(similarity, 4),
        "words_added": len(added),
        "words_removed": len(removed),
        "words_unchanged": len(words_a & words_b),
    }
