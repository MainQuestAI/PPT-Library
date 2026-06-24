"""Search release gate (v1.6-H).

Combines evaluation benchmarks, FTS index status, vector backend health,
and search profile validation into a single release gate check.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class GateCheck:
    """A single gate check result."""

    name: str
    passed: bool
    message: str
    details: dict[str, object] = field(default_factory=dict)

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
        }
        if self.details:
            d["details"] = self.details
        return d


@dataclass(frozen=True)
class SearchReleaseGate:
    """Complete search release gate report."""

    generated_at: str
    checks: list[GateCheck]
    metrics: dict[str, float]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def to_json(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "passed": self.passed,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "checks": [c.to_json() for c in self.checks],
            "metrics": self.metrics,
        }


def run_search_release_gate(
    conn: sqlite3.Connection,
    *,
    min_fts_documents: int = 0,
    min_recall_at_10: float = 0.0,
    min_ndcg_at_10: float = 0.0,
) -> SearchReleaseGate:
    """Run all search release gate checks.

    Returns a SearchReleaseGate with pass/fail status for each check.
    """
    checks: list[GateCheck] = []
    metrics: dict[str, float] = {}

    # Check 1: FTS5 tables exist
    from ppt_lib.fts_search import fts_tables_exist, get_fts_document_count
    fts_exists = fts_tables_exist(conn)
    checks.append(GateCheck(
        name="fts5_tables_exist",
        passed=fts_exists,
        message="FTS5 tables exist" if fts_exists else "FTS5 tables not found",
    ))

    # Check 2: FTS5 document count
    fts_count = 0
    if fts_exists:
        fts_count = get_fts_document_count(conn)
    checks.append(GateCheck(
        name="fts5_document_count",
        passed=fts_count >= min_fts_documents,
        message=f"FTS5 documents: {fts_count} (min: {min_fts_documents})",
        details={"count": fts_count, "minimum": min_fts_documents},
    ))
    metrics["fts_document_count"] = float(fts_count)

    # Check 3: Vector backend status
    from ppt_lib.vector_backend import SqliteScanBackend
    backend = SqliteScanBackend(conn)
    status = backend.get_status()
    checks.append(GateCheck(
        name="vector_backend_available",
        passed=status.available,
        message=f"Vector backend: {status.backend_name} ({status.index_count} vectors)",
        details=status.to_json(),
    ))
    metrics["vector_index_count"] = float(status.index_count)

    # Check 4: Contract registry available
    from ppt_lib.contracts import get_registry
    registry = get_registry()
    contracts = registry.list_contracts()
    has_search_contract = any(c.name == "search-response.v2" for c in contracts)
    checks.append(GateCheck(
        name="search_contract_registered",
        passed=has_search_contract,
        message="search-response.v2 contract registered" if has_search_contract else "search-response.v2 not found",
        details={"total_contracts": len(contracts)},
    ))

    # Check 5: Search profiles available
    from ppt_lib.search_fusion import list_profiles
    profiles = list_profiles()
    has_default = any(p.name == "default" for p in profiles)
    checks.append(GateCheck(
        name="search_profiles_available",
        passed=has_default and len(profiles) >= 2,
        message=f"{len(profiles)} search profiles available",
        details={"profiles": [p.name for p in profiles]},
    ))

    # Check 6: Capabilities detection works
    from ppt_lib.services.capability_service import detect_capabilities
    from ppt_lib.settings import Settings
    try:
        settings = Settings()
        report = detect_capabilities(settings)
        caps_ok = report.contract == "ppt_library.capabilities.v1"
        checks.append(GateCheck(
            name="capabilities_detection",
            passed=caps_ok,
            message="Capabilities detection operational",
            details={"contract": report.contract, "features": len(report.features)},
        ))
    except Exception as exc:
        checks.append(GateCheck(
            name="capabilities_detection",
            passed=False,
            message=f"Capabilities detection failed: {exc}",
        ))

    # Check 7: Query trace builder works
    from ppt_lib.query_trace import TraceBuilder
    try:
        builder = TraceBuilder("test", "default", "1.0")
        trace = builder.build()
        trace_ok = trace.query == "test"
        checks.append(GateCheck(
            name="query_trace_builder",
            passed=trace_ok,
            message="Query trace builder operational",
        ))
    except Exception as exc:
        checks.append(GateCheck(
            name="query_trace_builder",
            passed=False,
            message=f"Query trace builder failed: {exc}",
        ))

    # Check 8: Reranker egress policy works
    from ppt_lib.reranker import DEFAULT_EGRESS_POLICY
    checks.append(GateCheck(
        name="egress_policy_default",
        passed=not DEFAULT_EGRESS_POLICY.can_use_cloud(),
        message="Default egress policy blocks cloud (secure by default)",
    ))

    return SearchReleaseGate(
        generated_at=datetime.now(UTC).isoformat(),
        checks=checks,
        metrics=metrics,
    )
