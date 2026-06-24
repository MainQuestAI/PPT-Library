"""Enterprise GA release gate (v2.0-H).

Validates that all enterprise features are operational for GA release:
workspaces, RBAC, policy engine, connectors, analytics, approvals.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class GAReleaseGate:
    """Enterprise GA release gate report."""

    generated_at: str
    checks: list[dict[str, object]]
    passed: bool

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c["passed"])

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c["passed"])

    def to_json(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "passed": self.passed,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "checks": self.checks,
        }


def run_ga_release_gate(conn: sqlite3.Connection) -> GAReleaseGate:
    """Run all enterprise GA release gate checks."""
    checks: list[dict[str, object]] = []

    # Check 1: RBAC module
    try:
        from ppt_lib.rbac import ROLE_PERMISSIONS, Permission, Role, UserContext
        user = UserContext("test", Role.ADMIN)
        ok = user.has_permission(Permission.SEARCH)
        all_roles = len(ROLE_PERMISSIONS) >= 4
        checks.append({
            "name": "rbac_operational",
            "passed": ok and all_roles,
            "message": f"RBAC: {len(ROLE_PERMISSIONS)} roles, admin can search: {ok}",
        })
    except Exception as exc:
        checks.append({"name": "rbac_operational", "passed": False, "message": str(exc)})

    # Check 2: Policy engine
    try:
        from ppt_lib.policy_engine import PolicyAction, PolicyEffect, PolicyEngine
        engine = PolicyEngine()
        decision = engine.evaluate(PolicyAction.SEARCH)
        ok = decision.effect == PolicyEffect.ALLOW
        checks.append({
            "name": "policy_engine_operational",
            "passed": ok,
            "message": f"Policy engine: {len(engine.policies)} policies, search={decision.effect}",
        })
    except Exception as exc:
        checks.append({"name": "policy_engine_operational", "passed": False, "message": str(exc)})

    # Check 3: Workspace support
    try:
        from ppt_lib.workspaces import create_workspace, list_workspaces
        ws = create_workspace(conn, "GA Test Workspace", owner_user_id="test_user")
        wss = list_workspaces(conn)
        ok = ws.workspace_id.startswith("ws_") and len(wss) >= 1
        checks.append({
            "name": "workspaces_operational",
            "passed": ok,
            "message": f"Workspaces: created {ws.workspace_id}, total: {len(wss)}",
        })
    except Exception as exc:
        checks.append({"name": "workspaces_operational", "passed": False, "message": str(exc)})

    # Check 4: Approval workflows
    try:
        from ppt_lib.approvals import ReviewType, create_review_request
        req = create_review_request(conn, ReviewType.EXPORT, "test_asset", "test_user")
        ok = req.request_id.startswith("rev_")
        checks.append({
            "name": "approvals_operational",
            "passed": ok,
            "message": f"Approvals: created {req.request_id}",
        })
    except Exception as exc:
        checks.append({"name": "approvals_operational", "passed": False, "message": str(exc)})

    # Check 5: Analytics
    try:
        from ppt_lib.analytics import generate_analytics_report
        report = generate_analytics_report(conn)
        ok = report.generated_at != ""
        checks.append({
            "name": "analytics_operational",
            "passed": ok,
            "message": f"Analytics: report generated at {report.generated_at}",
        })
    except Exception as exc:
        checks.append({"name": "analytics_operational", "passed": False, "message": str(exc)})

    # Check 6: Connector SDK
    try:
        from ppt_lib.connectors import ConnectorRegistry
        registry = ConnectorRegistry()
        ok = isinstance(registry.list_connectors(), list)
        checks.append({
            "name": "connectors_operational",
            "passed": ok,
            "message": "Connector registry operational",
        })
    except Exception as exc:
        checks.append({"name": "connectors_operational", "passed": False, "message": str(exc)})

    # Check 7: Repository interfaces
    try:
        from ppt_lib.repositories import RepositoryFactory, SlideRepository
        factory = RepositoryFactory(conn)
        repo = factory.slides()
        ok = isinstance(repo, SlideRepository)
        checks.append({
            "name": "repositories_operational",
            "passed": ok,
            "message": "Repository factory operational",
        })
    except Exception as exc:
        checks.append({"name": "repositories_operational", "passed": False, "message": str(exc)})

    # Check 8: Audit log
    try:
        from ppt_lib.audit import get_audit_summary, log_action
        entry = log_action(conn, "ga_check", "system", "ga_gate")
        summary = get_audit_summary(conn)
        ok = entry.entry_id != "" and isinstance(summary["total_entries"], int)
        checks.append({
            "name": "audit_operational",
            "passed": ok,
            "message": f"Audit: logged {entry.entry_id}, total: {summary['total_entries']}",
        })
    except Exception as exc:
        checks.append({"name": "audit_operational", "passed": False, "message": str(exc)})

    # Check 9: SSE events
    try:
        from ppt_lib.sse import SSEEvent
        event = SSEEvent(event="test", data={"check": True})
        formatted = event.format()
        ok = "event: test" in formatted
        checks.append({
            "name": "sse_operational",
            "passed": ok,
            "message": "SSE event formatting operational",
        })
    except Exception as exc:
        checks.append({"name": "sse_operational", "passed": False, "message": str(exc)})

    # Check 10: All v1.5-v1.7 features still operational
    try:
        from ppt_lib.classification import CLASSIFICATION_FIELDS
        from ppt_lib.contracts import get_registry
        from ppt_lib.ranking_v2 import compute_asset_score
        from ppt_lib.search_fusion import DEFAULT_PROFILE
        contract_registry = get_registry()
        score = compute_asset_score(5, 1, 2)
        ok = (
            len(contract_registry.list_contracts()) >= 7
            and DEFAULT_PROFILE.name == "default"
            and score.shrunk_score > 0
            and len(CLASSIFICATION_FIELDS) >= 7
        )
        checks.append({
            "name": "core_features_intact",
            "passed": ok,
            "message": "v1.5-v1.7 core features verified",
        })
    except Exception as exc:
        checks.append({"name": "core_features_intact", "passed": False, "message": str(exc)})

    all_passed = all(c["passed"] for c in checks)

    return GAReleaseGate(
        generated_at=datetime.now(UTC).isoformat(),
        checks=checks,
        passed=all_passed,
    )
