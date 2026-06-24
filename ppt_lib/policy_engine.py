"""Policy engine for enterprise governance (v2.0-A).

Enforces organizational policies on asset operations:
egress control, confidentiality, export restrictions, retention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PolicyAction(StrEnum):
    """Actions that can be controlled by policies."""

    SEARCH = "search"
    EXPORT = "export"
    EXTERNAL_EGRESS = "external_egress"
    DELETE = "delete"
    CLASSIFY = "classify"
    SHARE = "share"


class PolicyEffect(StrEnum):
    """Policy decision."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class Confidentiality(StrEnum):
    """Asset confidentiality levels."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass(frozen=True)
class PolicyRule:
    """A single policy rule."""

    rule_id: str
    name: str
    action: PolicyAction
    effect: PolicyEffect
    conditions: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "action": self.action,
            "effect": self.effect,
            "conditions": self.conditions,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class PolicyDecision:
    """The result of evaluating a policy."""

    effect: PolicyEffect
    matched_rules: list[str]
    reason: str
    requires_approval: bool = False
    approver_role: str | None = None

    def to_json(self) -> dict[str, object]:
        d: dict[str, object] = {
            "effect": self.effect,
            "matched_rules": self.matched_rules,
            "reason": self.reason,
        }
        if self.requires_approval:
            d["requires_approval"] = True
            d["approver_role"] = self.approver_role
        return d


# Default enterprise policies
DEFAULT_POLICIES: list[PolicyRule] = [
    PolicyRule(
        rule_id="egress-confidential",
        name="Block external egress for confidential assets",
        action=PolicyAction.EXTERNAL_EGRESS,
        effect=PolicyEffect.DENY,
        conditions={"confidentiality_min": Confidentiality.CONFIDENTIAL},
        reason="Confidential assets cannot be sent to external services",
    ),
    PolicyRule(
        rule_id="export-restricted",
        name="Require approval for restricted asset export",
        action=PolicyAction.EXPORT,
        effect=PolicyEffect.REQUIRE_APPROVAL,
        conditions={"confidentiality": Confidentiality.RESTRICTED},
        reason="Restricted asset export requires admin approval",
    ),
    PolicyRule(
        rule_id="delete-approval",
        name="Require approval for asset deletion",
        action=PolicyAction.DELETE,
        effect=PolicyEffect.REQUIRE_APPROVAL,
        conditions={},
        reason="Asset deletion requires admin approval",
    ),
    PolicyRule(
        rule_id="allow-search",
        name="Allow search by default",
        action=PolicyAction.SEARCH,
        effect=PolicyEffect.ALLOW,
        conditions={},
        reason="Search is allowed for all authenticated users",
    ),
]


class PolicyEngine:
    """Evaluates policies against requested actions."""

    def __init__(
        self,
        policies: list[PolicyRule] | None = None,
    ) -> None:
        self._policies = list(policies) if policies is not None else list(DEFAULT_POLICIES)

    @property
    def policies(self) -> list[PolicyRule]:
        return list(self._policies)

    def add_policy(self, rule: PolicyRule) -> None:
        self._policies.append(rule)

    def remove_policy(self, rule_id: str) -> bool:
        before = len(self._policies)
        self._policies = [p for p in self._policies if p.rule_id != rule_id]
        return len(self._policies) < before

    def evaluate(
        self,
        action: PolicyAction,
        *,
        asset_confidentiality: Confidentiality = Confidentiality.INTERNAL,
        user_role: str = "viewer",
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """Evaluate all matching policies for an action.

        Priority: DENY > REQUIRE_APPROVAL > ALLOW
        """
        matched: list[PolicyRule] = []

        for policy in self._policies:
            if policy.action != action:
                continue
            if self._matches_conditions(policy, asset_confidentiality, context):
                matched.append(policy)

        if not matched:
            # Default deny for unknown actions
            return PolicyDecision(
                effect=PolicyEffect.DENY,
                matched_rules=[],
                reason="No matching policy — default deny",
            )

        # Priority: DENY > REQUIRE_APPROVAL > ALLOW
        deny_rules = [r for r in matched if r.effect == PolicyEffect.DENY]
        approval_rules = [r for r in matched if r.effect == PolicyEffect.REQUIRE_APPROVAL]
        allow_rules = [r for r in matched if r.effect == PolicyEffect.ALLOW]

        if deny_rules:
            return PolicyDecision(
                effect=PolicyEffect.DENY,
                matched_rules=[r.rule_id for r in deny_rules],
                reason=deny_rules[0].reason,
            )

        if approval_rules:
            return PolicyDecision(
                effect=PolicyEffect.REQUIRE_APPROVAL,
                matched_rules=[r.rule_id for r in approval_rules],
                reason=approval_rules[0].reason,
                requires_approval=True,
                approver_role="admin",
            )

        return PolicyDecision(
            effect=PolicyEffect.ALLOW,
            matched_rules=[r.rule_id for r in allow_rules],
            reason=allow_rules[0].reason if allow_rules else "Allowed by default",
        )

    def _matches_conditions(
        self,
        policy: PolicyRule,
        confidentiality: Confidentiality,
        context: dict[str, Any] | None,
    ) -> bool:
        """Check if policy conditions match the given context."""
        if not policy.conditions:
            return True  # No conditions = always matches

        # Check confidentiality conditions
        conf_min = policy.conditions.get("confidentiality_min")
        if conf_min:
            levels = list(Confidentiality)
            if levels.index(confidentiality) < levels.index(Confidentiality(conf_min)):
                return False

        conf_exact = policy.conditions.get("confidentiality")
        if conf_exact and Confidentiality(conf_exact) != confidentiality:
            return False

        return True

    def to_json(self) -> dict[str, object]:
        return {
            "policy_count": len(self._policies),
            "policies": [p.to_json() for p in self._policies],
        }
