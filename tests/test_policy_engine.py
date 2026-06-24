"""Tests for policy engine (v2.0-A)."""

from __future__ import annotations

from ppt_lib.policy_engine import (
    Confidentiality,
    PolicyAction,
    PolicyDecision,
    PolicyEffect,
    PolicyEngine,
    PolicyRule,
)


class TestPolicyEffect:
    def test_effects(self):
        assert PolicyEffect.ALLOW == "allow"
        assert PolicyEffect.DENY == "deny"
        assert PolicyEffect.REQUIRE_APPROVAL == "require_approval"


class TestConfidentiality:
    def test_levels(self):
        assert Confidentiality.PUBLIC == "public"
        assert Confidentiality.RESTRICTED == "restricted"


class TestPolicyRule:
    def test_to_json(self):
        rule = PolicyRule("r1", "test", PolicyAction.SEARCH, PolicyEffect.ALLOW)
        j = rule.to_json()
        assert j["rule_id"] == "r1"
        assert j["effect"] == "allow"


class TestPolicyEngine:
    def test_default_policies(self):
        engine = PolicyEngine()
        assert len(engine.policies) >= 3

    def test_search_allowed(self):
        engine = PolicyEngine()
        decision = engine.evaluate(PolicyAction.SEARCH)
        assert decision.effect == PolicyEffect.ALLOW

    def test_egress_denied_for_confidential(self):
        engine = PolicyEngine()
        decision = engine.evaluate(
            PolicyAction.EXTERNAL_EGRESS,
            asset_confidentiality=Confidentiality.CONFIDENTIAL,
        )
        assert decision.effect == PolicyEffect.DENY
        assert "egress-confidential" in decision.matched_rules

    def test_egress_allowed_for_public(self):
        engine = PolicyEngine()
        decision = engine.evaluate(
            PolicyAction.EXTERNAL_EGRESS,
            asset_confidentiality=Confidentiality.PUBLIC,
        )
        # No matching deny policy for public
        assert decision.effect != PolicyEffect.DENY or "egress-confidential" not in decision.matched_rules

    def test_export_requires_approval_for_restricted(self):
        engine = PolicyEngine()
        decision = engine.evaluate(
            PolicyAction.EXPORT,
            asset_confidentiality=Confidentiality.RESTRICTED,
        )
        assert decision.effect == PolicyEffect.REQUIRE_APPROVAL
        assert decision.requires_approval is True
        assert decision.approver_role == "admin"

    def test_delete_requires_approval(self):
        engine = PolicyEngine()
        decision = engine.evaluate(PolicyAction.DELETE)
        assert decision.effect == PolicyEffect.REQUIRE_APPROVAL

    def test_unknown_action_default_deny(self):
        engine = PolicyEngine(policies=[])
        decision = engine.evaluate(PolicyAction.SHARE)
        assert decision.effect == PolicyEffect.DENY
        assert "default deny" in decision.reason

    def test_deny_overrides_allow(self):
        policies = [
            PolicyRule("allow", "Allow all", PolicyAction.EXPORT, PolicyEffect.ALLOW),
            PolicyRule("deny", "Deny restricted", PolicyAction.EXPORT, PolicyEffect.DENY,
                conditions={"confidentiality": Confidentiality.RESTRICTED}),
        ]
        engine = PolicyEngine(policies=policies)
        decision = engine.evaluate(
            PolicyAction.EXPORT,
            asset_confidentiality=Confidentiality.RESTRICTED,
        )
        assert decision.effect == PolicyEffect.DENY

    def test_add_policy(self):
        engine = PolicyEngine(policies=[])
        engine.add_policy(PolicyRule("r1", "test", PolicyAction.SEARCH, PolicyEffect.ALLOW))
        assert len(engine.policies) == 1

    def test_remove_policy(self):
        engine = PolicyEngine()
        original_count = len(engine.policies)
        ok = engine.remove_policy("allow-search")
        assert ok is True
        assert len(engine.policies) == original_count - 1

    def test_remove_nonexistent_policy(self):
        engine = PolicyEngine()
        ok = engine.remove_policy("nonexistent")
        assert ok is False

    def test_to_json(self):
        engine = PolicyEngine()
        j = engine.to_json()
        assert j["policy_count"] >= 3
        assert isinstance(j["policies"], list)


class TestPolicyDecision:
    def test_to_json_allow(self):
        d = PolicyDecision(PolicyEffect.ALLOW, ["r1"], "allowed")
        j = d.to_json()
        assert j["effect"] == "allow"
        assert "requires_approval" not in j

    def test_to_json_approval(self):
        d = PolicyDecision(
            PolicyEffect.REQUIRE_APPROVAL, ["r1"], "needs approval",
            requires_approval=True, approver_role="admin",
        )
        j = d.to_json()
        assert j["requires_approval"] is True
        assert j["approver_role"] == "admin"
