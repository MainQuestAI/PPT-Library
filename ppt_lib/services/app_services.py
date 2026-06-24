"""Application service layer for PPT Library (v1.8-A).

Provides a unified service interface for CLI, API, and Workbench.
All write operations go through services; no direct SQL from UI/API.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceResult:
    """Standard result from a service operation."""

    success: bool
    message: str
    data: dict[str, object] | None = None
    errors: list[dict[str, str]] | None = None

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {
            "success": self.success,
            "message": self.message,
        }
        if self.data is not None:
            d["data"] = self.data
        if self.errors:
            d["errors"] = self.errors
        return d


class SearchService:
    """Search service wrapping FTS5 and vector search."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        profile_name: str = "default",
    ) -> ServiceResult:
        from ppt_lib.search_fusion import (
            DECK_MASTER_PROFILE,
            DEFAULT_PROFILE,
            hybrid_search,
        )

        profile = DECK_MASTER_PROFILE if profile_name == "deck_master" else DEFAULT_PROFILE

        candidates = hybrid_search(
            self._conn,
            query,
            profile=profile,
            top_k=top_k,
        )

        return ServiceResult(
            success=True,
            message=f"Found {len(candidates)} candidates",
            data={
                "candidates": [c.to_json() for c in candidates],
                "profile": profile_name,
                "query": query,
            },
        )


class AssetService:
    """Asset management service."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_asset(self, asset_id: str) -> ServiceResult:
        from ppt_lib.asset_schema import get_lineage_edges

        cursor = self._conn.cursor()

        # Get asset info
        cursor.execute(
            "SELECT canonical_asset_id, asset_type, created_at, updated_at, labels_json "
            "FROM slide_assets WHERE canonical_asset_id = ?",
            (asset_id,),
        )
        row = cursor.fetchone()
        if not row:
            return ServiceResult(
                success=False,
                message=f"Asset not found: {asset_id}",
            )

        # Get classifications
        cursor.execute(
            "SELECT field_name, value, confidence, source, review_state "
            "FROM classification_values WHERE asset_id = ?",
            (asset_id,),
        )
        classifications = [
            {
                "field_name": r[0],
                "value": r[1],
                "confidence": r[2],
                "source": r[3],
                "review_state": r[4],
            }
            for r in cursor.fetchall()
        ]

        # Get feedback
        from ppt_lib.ranking_v2 import compute_asset_score
        cursor.execute(
            "SELECT event_type, COUNT(*) FROM feedback_events "
            "WHERE asset_id = ? GROUP BY event_type",
            (asset_id,),
        )
        feedback_counts = dict(cursor.fetchall())
        score = compute_asset_score(
            selection_count=feedback_counts.get("selected", 0),
            rejection_count=feedback_counts.get("rejected", 0),
            approval_count=feedback_counts.get("approved", 0),
        )

        # Get lineage
        edges = get_lineage_edges(self._conn, asset_id, direction="both")

        return ServiceResult(
            success=True,
            message=f"Asset {asset_id} retrieved",
            data={
                "asset_id": row[0],
                "asset_type": row[1],
                "created_at": row[2],
                "updated_at": row[3],
                "classifications": classifications,
                "feedback": feedback_counts,
                "score": score.to_json(),
                "lineage_edges": [e.to_json() for e in edges],
            },
        )

    def list_assets(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> ServiceResult:
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT canonical_asset_id, asset_type, created_at "
                "FROM slide_assets ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            assets = [
                {"asset_id": r[0], "asset_type": r[1], "created_at": r[2]}
                for r in cursor.fetchall()
            ]
            cursor.execute("SELECT COUNT(*) FROM slide_assets")
            total = cursor.fetchone()[0]

            return ServiceResult(
                success=True,
                message=f"Listed {len(assets)} assets (total: {total})",
                data={"assets": assets, "total": total, "limit": limit, "offset": offset},
            )
        except sqlite3.OperationalError:
            return ServiceResult(success=False, message="Asset tables not available")


class HealthService:
    """Asset health management service."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def run_scan(self) -> ServiceResult:
        from ppt_lib.asset_health import run_all_detectors
        report = run_all_detectors(self._conn)
        return ServiceResult(
            success=True,
            message=f"Health scan complete: {report.findings_created} findings",
            data=report.to_json(),
        )

    def get_findings(
        self,
        *,
        severity: str | None = None,
        limit: int = 50,
    ) -> ServiceResult:
        from ppt_lib.asset_health import get_open_findings
        findings = get_open_findings(self._conn, severity=severity, limit=limit)
        return ServiceResult(
            success=True,
            message=f"{len(findings)} open findings",
            data={"findings": findings, "count": len(findings)},
        )

    def resolve_finding(self, finding_id: str) -> ServiceResult:
        from ppt_lib.asset_health import resolve_finding
        ok = resolve_finding(self._conn, finding_id)
        if ok:
            return ServiceResult(success=True, message=f"Finding {finding_id} resolved")
        return ServiceResult(success=False, message=f"Finding not found: {finding_id}")


class ReviewService:
    """Classification review service."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def run_classification(self, *, limit: int = 100) -> ServiceResult:
        from ppt_lib.classification import classify_batch, save_classifications
        suggestions = classify_batch(self._conn, limit=limit)
        saved = save_classifications(self._conn, suggestions)
        return ServiceResult(
            success=True,
            message=f"Classified {saved} suggestions",
            data={"suggestions_generated": len(suggestions), "saved": saved},
        )

    def approve(self, asset_id: str, field_name: str) -> ServiceResult:
        from ppt_lib.classification import approve_classification
        ok = approve_classification(self._conn, asset_id, field_name)
        if ok:
            return ServiceResult(success=True, message=f"Approved {field_name} for {asset_id}")
        return ServiceResult(success=False, message="Classification not found")

    def reject(self, asset_id: str, field_name: str) -> ServiceResult:
        from ppt_lib.classification import reject_classification
        ok = reject_classification(self._conn, asset_id, field_name)
        if ok:
            return ServiceResult(success=True, message=f"Rejected {field_name} for {asset_id}")
        return ServiceResult(success=False, message="Classification not found")

    def get_status(self) -> ServiceResult:
        from ppt_lib.classification import get_classification_status
        status = get_classification_status(self._conn)
        return ServiceResult(
            success=True,
            message="Classification status retrieved",
            data=status,
        )


class JobService:
    """Job management service."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_jobs(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> ServiceResult:
        from ppt_lib.jobs import JobEngine
        engine = JobEngine(self._conn)
        jobs = engine.list_jobs(status=status, limit=limit)
        return ServiceResult(
            success=True,
            message=f"Listed {len(jobs)} jobs",
            data={"jobs": [j.to_json() for j in jobs]},
        )

    def get_job(self, job_id: str) -> ServiceResult:
        from ppt_lib.jobs import JobEngine
        engine = JobEngine(self._conn)
        job = engine.get(job_id)
        if job:
            return ServiceResult(
                success=True,
                message=f"Job {job_id} retrieved",
                data=job.to_json(),
            )
        return ServiceResult(success=False, message=f"Job not found: {job_id}")

    def cancel_job(self, job_id: str) -> ServiceResult:
        from ppt_lib.jobs import JobEngine
        engine = JobEngine(self._conn)
        job = engine.get(job_id)
        if not job:
            return ServiceResult(success=False, message=f"Job not found: {job_id}")
        engine.request_cancel(job_id)
        return ServiceResult(success=True, message=f"Cancel requested for {job_id}")


class LibraryService:
    """Top-level service aggregator."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self.search = SearchService(conn)
        self.assets = AssetService(conn)
        self.health = HealthService(conn)
        self.review = ReviewService(conn)
        self.jobs = JobService(conn)

    def get_status(self) -> ServiceResult:
        """Get overall library status."""
        cursor = self._conn.cursor()

        # Basic stats
        stats: dict[str, object] = {}
        for table in ["slides", "presentations", "embeddings"]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                stats[f"{table}_count"] = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                stats[f"{table}_count"] = 0

        # Schema version
        try:
            cursor.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
            row = cursor.fetchone()
            stats["schema_version"] = int(row[0]) if row else 0
        except sqlite3.OperationalError:
            stats["schema_version"] = 0

        return ServiceResult(
            success=True,
            message="Library status",
            data=stats,
        )
