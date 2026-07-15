from __future__ import annotations

import sqlite3
from pathlib import Path

from ppt_lib.contracts import get_registry
from ppt_lib.db import SCHEMA_VERSION
from ppt_lib.labels import NARRATIVE_ROLES
from ppt_lib.searcher import load_search_rows
from ppt_lib.settings import Settings

ROLE_MINIMUM = 10
PREVIEW_READY_RATIO = 0.9
BUSINESS_DEAL_MINIMUM = 5
BUSINESS_USAGE_MINIMUM = 20


def build_readiness(conn: sqlite3.Connection, settings: Settings) -> dict[str, object]:
    active_source_count = _scalar(conn, "SELECT COUNT(*) FROM library_sources WHERE is_active = 1")
    active_presentation_count = _scalar(
        conn,
        """
        SELECT COUNT(DISTINCT psl.presentation_id)
        FROM presentation_source_links psl
        JOIN library_sources ls ON ls.id = psl.library_source_id
        WHERE ls.is_active = 1
        """,
    )
    active_slide_count = _active_slide_scalar(conn, "COUNT(DISTINCT s.id)")
    valid_embedding_count = _active_slide_scalar(
        conn,
        "COUNT(DISTINCT CASE WHEN s.embedding IS NOT NULL AND length(s.embedding) = ? THEN s.id END)",
        (settings.embedding_dimensions * 4,),
    )
    invalid_embedding_count = _active_slide_scalar(
        conn,
        "COUNT(DISTINCT CASE WHEN s.embedding IS NOT NULL AND length(s.embedding) != ? THEN s.id END)",
        (settings.embedding_dimensions * 4,),
    )
    retrievable_rows = load_search_rows(conn, settings.embedding_dimensions, scope="active")
    retrievable_slide_count = len(retrievable_rows)
    role_counts = {role: 0 for role in NARRATIVE_ROLES}
    for row in retrievable_rows:
        role = row["metadata"].get("narrative_role")
        if role in role_counts:
            role_counts[str(role)] += 1
    screenshot_paths = _active_screenshot_paths(conn)
    preview_ready_count = sum(1 for path in screenshot_paths if path.is_file())
    preview_ratio = preview_ready_count / active_slide_count if active_slide_count else 0.0

    provider_status = _semantic_provider_status(settings)
    runtime_ready = SCHEMA_VERSION >= 5
    contract_names = {
        "deck-master-bridge-plan.v1",
        "deck-master-selection.v1",
        "deck-master-selection.v2",
        "readiness.v1",
    }
    registry = get_registry()
    contract_ready = all(registry.has(name) for name in contract_names)
    semantic_search_ready = (
        active_source_count > 0
        and active_presentation_count > 0
        and retrievable_slide_count > 0
        and invalid_embedding_count == 0
        and provider_status != "unavailable"
    )
    role_selection_ready = all(role_counts.get(role, 0) >= ROLE_MINIMUM for role in NARRATIVE_ROLES)
    preview_status = _preview_status(active_slide_count, preview_ratio)

    deals_with_outcome = _scalar(conn, "SELECT COUNT(*) FROM deals WHERE outcome IN ('won', 'lost')")
    usage_count = _scalar(conn, "SELECT COUNT(*) FROM slide_usage")
    business_ranking_status = (
        "ready"
        if deals_with_outcome >= BUSINESS_DEAL_MINIMUM and usage_count >= BUSINESS_USAGE_MINIMUM
        else "cold_start"
    )
    active_orphan_count = _active_orphan_count(conn)
    active_failed_job_count = _active_failed_job_count(conn)

    reason_codes: list[str] = []
    if active_source_count == 0:
        reason_codes.append("ACTIVE_SOURCE_EMPTY")
    if active_source_count and active_presentation_count == 0:
        reason_codes.append("ACTIVE_CORPUS_UNLINKED")
    if invalid_embedding_count:
        reason_codes.append("ACTIVE_EMBEDDING_DIMENSION_MISMATCH")
    if provider_status == "unavailable":
        reason_codes.append("SEMANTIC_PROVIDER_UNAVAILABLE")
    if not role_selection_ready:
        reason_codes.append("ROLE_SELECTION_COVERAGE_LOW")
    if preview_status != "ready":
        reason_codes.append("PREVIEW_COVERAGE_LOW")
    if business_ranking_status == "cold_start":
        reason_codes.append("BUSINESS_RANKING_COLD_START")
    if active_failed_job_count:
        reason_codes.append("ACTIVE_INDEX_FAILURES")
    if active_orphan_count:
        reason_codes.append("ACTIVE_ORPHAN_PRESENTATIONS")

    if active_source_count == 0 or active_presentation_count == 0:
        data_hygiene_status = "blocked"
    elif active_failed_job_count or active_orphan_count or invalid_embedding_count or preview_status != "ready":
        data_hygiene_status = "degraded"
    else:
        data_hygiene_status = "clean"

    if not runtime_ready or not contract_ready or not semantic_search_ready:
        overall_status = "blocked"
    elif not role_selection_ready or preview_status != "ready":
        overall_status = "degraded_ready"
    else:
        overall_status = "ready"

    return {
        "schema_version": "ppt_library_readiness.v1",
        "runtime_ready": runtime_ready,
        "contract_ready": contract_ready,
        "semantic_search_ready": semantic_search_ready,
        "semantic_provider_status": provider_status,
        "role_selection_ready": role_selection_ready,
        "preview_status": preview_status,
        "business_ranking_status": business_ranking_status,
        "data_hygiene_status": data_hygiene_status,
        "overall_status": overall_status,
        "active_corpus": {
            "source_count": active_source_count,
            "presentation_count": active_presentation_count,
            "slide_count": active_slide_count,
            "valid_embedding_count": valid_embedding_count,
            "invalid_embedding_count": invalid_embedding_count,
            "retrievable_slide_count": retrievable_slide_count,
            "preview_ready_count": preview_ready_count,
            "preview_coverage": round(preview_ratio, 4),
            "role_minimum": ROLE_MINIMUM,
            "role_counts": role_counts,
            "failed_job_count": active_failed_job_count,
            "orphan_presentation_count": active_orphan_count,
        },
        "business_signals": {
            "deals_with_outcome": deals_with_outcome,
            "usage_count": usage_count,
            "deal_minimum": BUSINESS_DEAL_MINIMUM,
            "usage_minimum": BUSINESS_USAGE_MINIMUM,
        },
        "reason_codes": reason_codes,
    }


def _active_slide_scalar(
    conn: sqlite3.Connection,
    expression: str,
    params: tuple[object, ...] = (),
) -> int:
    return _scalar(
        conn,
        f"""
        SELECT {expression}
        FROM slides s
        JOIN presentation_source_links psl ON psl.presentation_id = s.presentation_id
        JOIN library_sources ls ON ls.id = psl.library_source_id
        WHERE ls.is_active = 1
        """,
        params,
    )


def _active_screenshot_paths(conn: sqlite3.Connection) -> list[Path]:
    rows = conn.execute(
        """
        SELECT DISTINCT s.id, sc.file_path
        FROM slides s
        JOIN presentation_source_links psl ON psl.presentation_id = s.presentation_id
        JOIN library_sources ls ON ls.id = psl.library_source_id
        JOIN screenshots sc ON sc.hash = s.screenshot_hash
        WHERE ls.is_active = 1 AND sc.file_path IS NOT NULL
        """
    ).fetchall()
    return [Path(row[1]) for row in rows if row[1]]


def _active_orphan_count(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT DISTINCT p.path
        FROM presentations p
        JOIN presentation_source_links psl ON psl.presentation_id = p.id
        JOIN library_sources ls ON ls.id = psl.library_source_id
        WHERE ls.is_active = 1
        """
    ).fetchall()
    return sum(1 for row in rows if not Path(row[0]).exists())


def _active_failed_job_count(conn: sqlite3.Connection) -> int:
    source_rows = conn.execute(
        "SELECT name, metadata_json FROM library_sources WHERE is_active = 1"
    ).fetchall()
    source_paths = [_source_path(name, metadata_raw) for name, metadata_raw in source_rows]
    failed_paths = [Path(row[0]).expanduser().resolve(strict=False) for row in conn.execute(
        "SELECT file_path FROM index_jobs WHERE status = 'failed'"
    ).fetchall()]
    return sum(1 for failed_path in failed_paths if any(_path_in_source(failed_path, source) for source in source_paths))


def _source_path(name: str, metadata_raw: str | None) -> Path:
    import json

    try:
        metadata = json.loads(metadata_raw) if metadata_raw else {}
    except json.JSONDecodeError:
        metadata = {}
    raw_path = metadata.get("path") if isinstance(metadata, dict) else None
    return Path(str(raw_path or name)).expanduser().resolve(strict=False)


def _path_in_source(path: Path, source: Path) -> bool:
    if path == source:
        return True
    if source.suffix.lower() in {".ppt", ".pptx", ".pptm"}:
        return False
    return source in path.parents


def _semantic_provider_status(settings: Settings) -> str:
    if settings.embedding_provider in {"lmstudio", "fake"}:
        return "configured"
    if settings.embedding_provider == "openai" and (settings.embedding_api_key or settings.openai_api_key or settings.embedding_api_url):
        return "configured"
    return "unavailable"


def _preview_status(slide_count: int, coverage: float) -> str:
    if slide_count == 0 or coverage == 0:
        return "missing"
    return "ready" if coverage >= PREVIEW_READY_RATIO else "degraded"


def _scalar(conn: sqlite3.Connection, query: str, params: tuple[object, ...] = ()) -> int:
    row = conn.execute(query, params).fetchone()
    return int(row[0] or 0) if row else 0
