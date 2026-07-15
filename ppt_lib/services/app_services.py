"""Application service layer for PPT Library (v1.8-A).

Provides a unified service interface for CLI, API, and Workbench.
All write operations go through services; no direct SQL from UI/API.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from ppt_lib.embedding import EmbeddingProvider
from ppt_lib.reranker import EgressPolicy, RerankerProvider
from ppt_lib.settings import Settings
from ppt_lib.vector_backend import VectorBackend


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


@dataclass(frozen=True)
class _SearchFilters:
    industry: frozenset[str] | None
    scenario: frozenset[str] | None
    narrative_role: frozenset[str] | None
    page_role: frozenset[str] | None
    review_state: frozenset[str] | None
    include_versions: bool

    @property
    def has_value_filters(self) -> bool:
        return any(
            values is not None
            for values in (
                self.industry,
                self.scenario,
                self.narrative_role,
                self.page_role,
                self.review_state,
            )
        )


class SearchService:
    """Search service wrapping FTS5 and vector search."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings | None = None,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        vector_backend: VectorBackend | None = None,
        reranker: RerankerProvider | None = None,
        egress_policy: EgressPolicy | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._embedding_provider = embedding_provider
        self._vector_backend = vector_backend
        self._reranker = reranker
        self._egress_policy = egress_policy

    def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        profile_name: str = "default",
    ) -> ServiceResult:
        payload = self.search_v2(query, top_k=top_k, profile_name=profile_name, explain=False)
        data = payload["data"]
        assert isinstance(data, dict)

        return ServiceResult(
            success=True,
            message=f"Found {len(data.get('candidates', []))} candidates",
            data={**data, "profile": profile_name, "query": query},
        )

    def search_v2(
        self,
        query: str,
        *,
        top_k: int = 10,
        profile_name: str = "default",
        request_id: str | None = None,
        run_id: str | None = None,
        explain: bool = True,
        filters: dict[str, object] | None = None,
        context: dict[str, object] | None = None,
    ) -> dict[str, object]:
        from ppt_lib.contracts.registry import build_envelope_v2
        from ppt_lib.embedding import build_embedding_provider
        from ppt_lib.fts_search import get_fts_document_count
        from ppt_lib.query_trace import (
            FallbackTrace,
            FusionTrace,
            LexicalBackendTrace,
            RerankerTrace,
            TraceBuilder,
            VectorBackendTrace,
        )
        from ppt_lib.reranker import RerankCandidate, apply_rerank
        from ppt_lib.search_fusion import get_profile, run_hybrid_search

        if not query.strip():
            raise ValueError("Search query must not be empty")
        if top_k < 1 or top_k > 100:
            raise ValueError("top_k must be between 1 and 100")
        profile = get_profile(profile_name)
        if profile is None:
            raise ValueError(f"Unknown search profile: {profile_name}")
        normalized_filters = _normalize_search_filters(
            filters,
            default_include_versions=profile.include_versions,
        )

        started = time.monotonic()
        trace_builder = TraceBuilder(query, profile.name, profile.version, request_id=request_id)
        warnings: list[dict[str, str]] = []
        query_embedding = None
        provider = self._embedding_provider
        if provider is None and self._settings is not None:
            try:
                provider = build_embedding_provider(self._settings)
            except Exception as exc:
                warning = {"code": "SEARCH_EMBEDDING_UNAVAILABLE", "message": f"{type(exc).__name__}: {exc}"}
                warnings.append(warning)
                trace_builder.add_warning(warning["code"], warning["message"])
        if provider is not None:
            try:
                query_embedding = provider.encode(query)
            except Exception as exc:
                warning = {"code": "SEARCH_EMBEDDING_FAILED", "message": f"{type(exc).__name__}: {exc}"}
                warnings.append(warning)
                trace_builder.add_warning(warning["code"], warning["message"])

        total_slides = int(self._conn.execute("SELECT COUNT(*) FROM slides").fetchone()[0])
        recall_size = max(top_k * 3, profile.lexical_top_k, profile.vector_top_k)
        if total_slides > 0:
            recall_size = min(recall_size, total_slides)

        run = None
        prepared: list[tuple[Any, dict[str, Any], float]] = []
        lexical_duration_ms = 0
        vector_duration_ms = 0
        fusion_duration_ms = 0
        while True:
            run = run_hybrid_search(
                self._conn,
                query,
                query_embedding,
                profile=profile,
                top_k=recall_size,
                vector_backend=self._vector_backend,
            )
            lexical_duration_ms += run.lexical_duration_ms
            vector_duration_ms += run.vector_duration_ms
            fusion_duration_ms += run.fusion_duration_ms
            hydrated = _hydrate_search_candidates(
                self._conn,
                [candidate.slide_id for candidate in run.candidates],
            )
            maximum_fused = max((candidate.fused_score for candidate in run.candidates), default=1.0)
            prepared = []
            for candidate in run.candidates:
                row = hydrated.get(candidate.slide_id)
                if row is None or not _matches_filters(row, normalized_filters):
                    continue
                normalized_fused = candidate.fused_score / maximum_fused if maximum_fused > 0 else 0.0
                business_score = _business_score(normalized_fused, row, context) if profile.ranking == "business" else normalized_fused
                prepared.append((candidate, row, business_score))

            should_expand = (
                (normalized_filters.has_value_filters or not normalized_filters.include_versions)
                and len(prepared) < top_k
                and len(run.candidates) >= recall_size
                and recall_size < total_slides
            )
            if not should_expand:
                break
            recall_size = min(total_slides, max(recall_size + 1, recall_size * 2))

        assert run is not None
        fts_count = get_fts_document_count(self._conn) if _table_exists(self._conn, "slides_fts") else 0
        trace_builder.set_lexical_trace(
            LexicalBackendTrace(
                backend_name="fts5",
                candidate_count=len(run.lexical_results),
                duration_ms=lexical_duration_ms,
                fts_document_count=fts_count,
                query_sanitized=query.strip(),
            )
        )
        trace_builder.set_vector_trace(
            VectorBackendTrace(
                backend_name=run.vector_status.backend_name,
                candidate_count=len(run.vector_results),
                duration_ms=vector_duration_ms,
                index_count=run.vector_status.index_count,
                dimension=run.vector_status.dimension,
                model_version=run.vector_status.model_version,
                available=run.vector_status.available,
                reason=run.fallback_reason,
            )
        )
        trace_builder.set_fusion_trace(
            FusionTrace(
                method="rrf",
                rrf_k=profile.rrf_k,
                input_lexical_count=len(run.lexical_results),
                input_vector_count=len(run.vector_results),
                output_count=len(run.candidates),
                duration_ms=fusion_duration_ms,
            )
        )
        if run.fallback_reason:
            trace_builder.set_fallback_trace(
                FallbackTrace(
                    backend="vector",
                    original="configured_embedding_backend",
                    fallback="fts5",
                    reason=run.fallback_reason,
                )
            )

        prepared.sort(key=lambda item: (-item[2], int(item[1]["slide_id"])))

        rerank_inputs = [
            RerankCandidate(
                slide_id=int(row["slide_id"]),
                title=str(row["title"]) if row["title"] is not None else None,
                text=str(row["text_content"] or ""),
                score=business_score,
            )
            for _candidate, row, business_score in prepared
        ]
        reranked, rerank_trace = apply_rerank(
            query,
            rerank_inputs,
            provider=self._reranker,
            egress_policy=self._egress_policy,
            top_n=top_k,
        )
        trace_builder.set_reranker_trace(
            RerankerTrace(
                provider=str(rerank_trace.get("provider", "noop")),
                model=None,
                input_count=len(rerank_inputs),
                output_count=len(reranked),
                duration_ms=_trace_duration_ms(rerank_trace),
                egress=str(rerank_trace.get("egress", "none")),
                fallback_used=bool(rerank_trace.get("fallback_used", False)),
            )
        )

        prepared_by_id = {int(row["slide_id"]): (candidate, row, score) for candidate, row, score in prepared}
        response_candidates: list[dict[str, object]] = []
        for result in reranked:
            candidate, row, business_score = prepared_by_id[result.slide_id]
            response_candidates.append(
                {
                    "candidate_id": f"candidate_{result.slide_id}",
                    "canonical_asset_id": str(row["canonical_asset_id"] or f"legacy_{result.slide_id}"),
                    "slide_revision_id": str(row["slide_revision_id"] or f"srev_legacy_{result.slide_id}"),
                    "title": str(row["title"] or ""),
                    "summary": str(row["ai_summary"] or row["text_content"] or "")[:500],
                    "score": round(max(0.0, min(1.0, float(result.rerank_score))), 6),
                    "score_breakdown": {
                        "lexical_score": candidate.lexical_score,
                        "vector_score": candidate.vector_score,
                        "rrf_score": candidate.fused_score,
                        "business_score": business_score,
                        "rerank_score": float(result.rerank_score),
                    },
                    "provenance": {
                        "legacy_slide_id": result.slide_id,
                        "source_file": str(row["source_file"] or ""),
                        "page_number": int(row["slide_index"]) + 1,
                        "source": str(row["source"] or ""),
                    },
                    "preview_uri": str(row["preview_uri"]) if row["preview_uri"] else None,
                    "warnings": [],
                }
            )

        trace = trace_builder.build()
        duration_ms = int((time.monotonic() - started) * 1000)
        meta = build_envelope_v2(
            "search",
            "ppt_library.search_response.v2",
            request_id=trace.request_id,
            run_id=run_id,
            query_trace_id=trace.query_trace_id,
            duration_ms=duration_ms,
        )
        return {
            "_meta": meta,
            "data": {
                "candidates": response_candidates,
                "trace": trace.to_json() if explain else None,
            },
            "_warnings": warnings,
            "_errors": [],
        }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(
        conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            (table,),
        ).fetchone()[0]
    )


def _trace_duration_ms(trace: dict[str, object]) -> int:
    duration = trace.get("duration_ms")
    return duration if isinstance(duration, int) else 0


def _hydrate_search_candidates(conn: sqlite3.Connection, slide_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not slide_ids:
        return {}
    placeholders = ",".join("?" for _ in slide_ids)
    rows = conn.execute(
        f"""SELECT s.id, s.title, s.text_content, s.ai_summary, s.slide_index, s.source,
                   s.win_rate, s.reuse_count, s.quality_rating, s.industry, s.scenario,
                   s.narrative_role, p.path, sc.file_path,
                   aim.canonical_asset_id, aim.slide_revision_id,
                   si.importance_score, si.page_role,
                   pv.deck_family_id, pv.version_role, pv.is_representative,
                   (SELECT GROUP_CONCAT(DISTINCT cv.review_state)
                      FROM classification_values cv
                     WHERE cv.asset_id = aim.canonical_asset_id)
            FROM slides s
            JOIN presentations p ON p.id = s.presentation_id
            LEFT JOIN screenshots sc ON sc.hash = s.screenshot_hash
            LEFT JOIN asset_identity_map aim ON aim.legacy_slide_id = s.id
            LEFT JOIN slide_importance si ON si.slide_id = s.id
            LEFT JOIN presentation_versions pv ON pv.presentation_id = s.presentation_id
            WHERE s.id IN ({placeholders})""",
        slide_ids,
    ).fetchall()
    return {
        int(row[0]): {
            "slide_id": int(row[0]),
            "title": row[1],
            "text_content": row[2],
            "ai_summary": row[3],
            "slide_index": int(row[4]),
            "source": row[5],
            "win_rate": row[6],
            "reuse_count": row[7],
            "quality_rating": row[8],
            "industry": row[9],
            "scenario": row[10],
            "narrative_role": row[11],
            "source_file": row[12],
            "preview_uri": row[13],
            "canonical_asset_id": row[14],
            "slide_revision_id": row[15],
            "importance_score": row[16],
            "page_role": row[17],
            "deck_family_id": row[18],
            "version_role": row[19],
            "is_representative_version": bool(row[20]) if row[20] is not None else None,
            "review_states": _review_states(row[21]),
        }
        for row in rows
    }


def _normalize_search_filters(
    filters: dict[str, object] | None,
    *,
    default_include_versions: bool,
) -> _SearchFilters:
    raw_filters = filters or {}
    allowed = {"industry", "scenario", "narrative_role", "page_role", "review_state", "include_versions"}
    unsupported = sorted(set(raw_filters) - allowed)
    if unsupported:
        raise ValueError(f"Unsupported search filter(s): {', '.join(unsupported)}")

    normalized: dict[str, frozenset[str] | None] = {}
    for field in ("industry", "scenario", "narrative_role", "page_role", "review_state"):
        raw_value = raw_filters.get(field)
        if raw_value is None:
            normalized[field] = None
            continue
        values = [raw_value] if isinstance(raw_value, str) else raw_value
        if not isinstance(values, list) or not values:
            raise ValueError(f"Search filter '{field}' must be a non-empty string array")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"Search filter '{field}' must contain non-empty strings")
        normalized[field] = frozenset(value.strip() for value in values)

    include_versions = raw_filters.get("include_versions", default_include_versions)
    if not isinstance(include_versions, bool):
        raise ValueError("Search filter 'include_versions' must be a boolean")
    return _SearchFilters(
        industry=normalized["industry"],
        scenario=normalized["scenario"],
        narrative_role=normalized["narrative_role"],
        page_role=normalized["page_role"],
        review_state=normalized["review_state"],
        include_versions=include_versions,
    )


def _review_states(raw_value: object) -> frozenset[str]:
    if not raw_value:
        return frozenset({"unreviewed"})
    states = frozenset(str(raw_value).split(","))
    if "pending" in states:
        return states | {"needs_review"}
    return states


def _matches_filters(row: dict[str, Any], filters: _SearchFilters) -> bool:
    for field in ("industry", "scenario", "narrative_role", "page_role"):
        expected = getattr(filters, field)
        if expected is not None and str(row.get(field) or "") not in expected:
            return False
    if filters.review_state is not None:
        review_states = row.get("review_states")
        if not isinstance(review_states, frozenset) or review_states.isdisjoint(filters.review_state):
            return False
    if not filters.include_versions and row.get("is_representative_version") is False:
        return False
    return True


def _business_score(base_score: float, row: dict[str, Any], context: dict[str, object] | None) -> float:
    score = base_score * 0.8
    win_rate = row.get("win_rate")
    if isinstance(win_rate, (int, float)):
        score += max(0.0, min(1.0, float(win_rate))) * 0.08
    reuse_count = row.get("reuse_count")
    if isinstance(reuse_count, int):
        score += min(reuse_count, 10) / 10 * 0.04
    quality = row.get("quality_rating")
    if isinstance(quality, int):
        score += max(0, min(quality, 5)) / 5 * 0.04
    importance = row.get("importance_score")
    if isinstance(importance, (int, float)):
        score += max(0.0, min(1.0, float(importance))) * 0.04
    if context:
        for field in ("industry", "scenario", "narrative_role"):
            expected = context.get(field)
            if expected is not None and str(row.get(field) or "") == str(expected):
                score += 0.02
    return max(0.0, min(1.0, score))


class AssetService:
    """Asset management service."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_asset(self, asset_id: str) -> ServiceResult:
        from ppt_lib.asset_schema import get_lineage_edges

        cursor = self._conn.cursor()

        # Get asset info
        cursor.execute(
            "SELECT canonical_asset_id, asset_type, created_at, updated_at, labels_json FROM slide_assets WHERE canonical_asset_id = ?",
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
            "SELECT field_name, value, confidence, source, review_state FROM classification_values WHERE asset_id = ?",
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
            "SELECT event_type, COUNT(*) FROM feedback_events WHERE asset_id = ? GROUP BY event_type",
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
                "SELECT canonical_asset_id, asset_type, created_at FROM slide_assets ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            assets = [{"asset_id": r[0], "asset_type": r[1], "created_at": r[2]} for r in cursor.fetchall()]
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

    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings | None = None,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        vector_backend: VectorBackend | None = None,
        reranker: RerankerProvider | None = None,
        egress_policy: EgressPolicy | None = None,
    ) -> None:
        self._conn = conn
        self.search = SearchService(
            conn,
            settings=settings,
            embedding_provider=embedding_provider,
            vector_backend=vector_backend,
            reranker=reranker,
            egress_policy=egress_policy,
        )
        self.assets = AssetService(conn)
        self.health = HealthService(conn)
        self.review = ReviewService(conn)
        self.jobs = JobService(conn)

    def get_status(self) -> ServiceResult:
        """Get overall library status."""
        cursor = self._conn.cursor()

        # Basic stats
        stats: dict[str, object] = {}
        for table in ["slides", "presentations"]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM [{table}]")
                stats[f"{table}_count"] = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                stats[f"{table}_count"] = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM slides WHERE embedding IS NOT NULL")
            stats["embeddings_count"] = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            stats["embeddings_count"] = 0

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
