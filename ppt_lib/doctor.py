from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ppt_lib.config import settings_summary
from ppt_lib.db import connect, get_stats, init_db, list_failed_jobs, list_orphan_presentations
from ppt_lib.diagnostics import run_diagnostics
from ppt_lib.settings import Settings


def run_doctor(settings: Settings) -> dict[str, object]:
    diagnostics = run_diagnostics(settings).to_json()
    assert settings.db_path is not None
    conn = connect(settings.db_path)
    init_db(conn)
    stats = get_stats(conn)
    failed_jobs = list_failed_jobs(conn)
    orphans = list_orphan_presentations(conn)
    index = {
        "stats": asdict(stats),
        "failed_jobs": [asdict(job) for job in failed_jobs],
        "orphan_presentations": [asdict(item) for item in orphans],
    }
    status = _summary_status(diagnostics, index)
    return {
        "summary": {
            "status": status,
            "can_index": diagnostics.get("can_index", False),
            "can_use_vision": diagnostics.get("can_use_vision", False),
        },
        "config": settings_summary(settings),
        "diagnostics": diagnostics,
        "index": index,
        "recommendations": _recommendations(status, diagnostics, index),
    }


def _summary_status(diagnostics: dict[str, Any], index: dict[str, Any]) -> str:
    stats = index.get("stats", {})
    failed_jobs = int(stats.get("failed_job_count", 0)) if isinstance(stats, dict) else 0
    chains = diagnostics.get("chains", {})
    embedding = chains.get("embedding", {}) if isinstance(chains, dict) else {}
    embedding_status = embedding.get("status") if isinstance(embedding, dict) else None
    if failed_jobs > 0 or diagnostics.get("can_index") is False or embedding_status == "error":
        return "error"
    orphan_count = int(stats.get("orphan_presentation_count", 0)) if isinstance(stats, dict) else 0
    if orphan_count > 0 or diagnostics.get("can_use_vision") is False or embedding_status in {"warning", "skipped"}:
        return "warning"
    return "ok"


def _recommendations(status: str, diagnostics: dict[str, Any], index: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    stats = index.get("stats", {})
    if isinstance(stats, dict) and int(stats.get("failed_job_count", 0)) > 0:
        recommendations.append("Inspect failed_jobs from ppt-lib status before relying on search results.")
    if isinstance(stats, dict) and int(stats.get("orphan_presentation_count", 0)) > 0:
        recommendations.append("Run ppt-lib prune --dry-run to review orphan index records.")
    chains = diagnostics.get("chains", {})
    embedding = chains.get("embedding", {}) if isinstance(chains, dict) else {}
    if isinstance(embedding, dict) and embedding.get("status") in {"error", "warning", "skipped"}:
        recommendations.append("Check embedding provider configuration before semantic search.")
    if diagnostics.get("can_use_vision") is False:
        recommendations.append("Vision is unavailable; text extraction fallback remains available.")
    if not recommendations and status == "ok":
        recommendations.append("No blocking issues found.")
    return recommendations
