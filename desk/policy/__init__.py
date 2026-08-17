"""Deterministic disposition policy (plan section 15/19/21). See desk/policy/rules.py
for the actual rule table; this file only re-exports the public surface."""

from desk.policy.rules import POLICY_VERSION, PolicyDecision, PolicyInput, decide

__all__ = ["POLICY_VERSION", "PolicyDecision", "PolicyInput", "decide"]
