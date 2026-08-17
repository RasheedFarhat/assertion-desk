"""Exhaustive branch coverage for desk/policy/rules.py's rule table (Control Plane's
"the policy table is small enough to test exhaustively" pattern, cited by plan section
27 for this exact module). Every test builds a synthetic PolicyInput by hand so every
branch is reachable on demand, including ones the current corpus never exercises
(verify_state == "error", any_live_credential == True) -- real corpus coverage lives in
tests/policy/test_corpus_parity.py.
"""

from __future__ import annotations

import pytest

from desk.policy.rules import POLICY_VERSION, DISPOSITIONS, PolicyDecision, PolicyInput, decide


def _input(**overrides) -> PolicyInput:
    base = dict(
        verify_state="ok",
        has_failed_check=False,
        has_gap=False,
        job_c_invoked=False,
        grounding_accepted=None,
        final_root_cause=None,
    )
    base.update(overrides)
    return PolicyInput(**base)


# --------------------------------------------------------------------------------- #
# The verify_state / failed-check / gap ladder
# --------------------------------------------------------------------------------- #


def test_parse_error_escalates():
    d = decide(_input(verify_state="parse_error"))
    assert d.disposition == "escalate"
    assert "artifact_did_not_parse" in d.matched_rules


def test_internal_error_escalates():
    d = decide(_input(verify_state="error"))
    assert d.disposition == "escalate"
    assert "internal_verification_error" in d.matched_rules


def test_ok_with_failed_check_reviews():
    d = decide(_input(verify_state="ok", has_failed_check=True, job_c_invoked=True))
    assert d.disposition == "review_required"
    assert "failed_check_present" in d.matched_rules


def test_ok_no_failure_with_gap_awaits_evidence():
    d = decide(_input(verify_state="ok", has_gap=True))
    assert d.disposition == "awaiting_evidence"
    assert "evidence_gap_present_no_failure" in d.matched_rules


def test_ok_no_failure_no_gap_reviews_not_auto():
    # No branch in the rule table emits "auto" -- see rules.py's
    # _decide_base_disposition docstring for why that is deliberate.
    d = decide(_input(verify_state="ok", has_failed_check=False, has_gap=False))
    assert d.disposition == "review_required"
    assert "no_failure_no_gap" in d.matched_rules


def test_no_saml_response_with_no_failure_no_gap_reviews():
    # negative_control's real shape: verify_state "no_saml_response", no checks ran at
    # all, so has_failed_check and has_gap are both False.
    d = decide(_input(verify_state="no_saml_response", has_failed_check=False, has_gap=False))
    assert d.disposition == "review_required"


def test_unknown_verify_state_defaults_to_review():
    d = decide(_input(verify_state="some_future_state_this_table_has_never_seen"))
    assert d.disposition == "review_required"
    assert "unknown_verify_state_default_deny" in d.matched_rules


# --------------------------------------------------------------------------------- #
# Grounding rejection
# --------------------------------------------------------------------------------- #


def test_grounding_rejection_is_recorded_even_when_already_review():
    # has_failed_check already forces review_required; a grounding rejection on top of
    # that should still be named in matched_rules so the audit trail shows it, even
    # though the disposition itself doesn't change.
    d = decide(
        _input(verify_state="ok", has_failed_check=True, job_c_invoked=True, grounding_accepted=False)
    )
    assert d.disposition == "review_required"
    assert "grounding_rejected_job_c_output" in d.matched_rules


def test_grounding_accepted_does_not_add_a_rule():
    d = decide(
        _input(verify_state="ok", has_failed_check=True, job_c_invoked=True, grounding_accepted=True)
    )
    assert "grounding_rejected_job_c_output" not in d.matched_rules


# --------------------------------------------------------------------------------- #
# Instruction-shaped span detection (narrative surface only -- see rules.py's
# INJECTION SIGNAL SCOPE note)
# --------------------------------------------------------------------------------- #


def test_injection_signal_upgrades_awaiting_evidence_to_review():
    d = decide(_input(verify_state="ok", has_gap=True, instruction_signal_detected=True))
    assert d.disposition == "review_required"
    assert "instruction_shaped_span_detected" in d.matched_rules


def test_injection_signal_is_a_noop_when_already_review():
    d = decide(
        _input(verify_state="ok", has_failed_check=True, job_c_invoked=True, instruction_signal_detected=True)
    )
    assert d.disposition == "review_required"
    assert "instruction_shaped_span_detected" in d.matched_rules  # still named, for the audit trail


# --------------------------------------------------------------------------------- #
# Live credential (T1) -- never exercised by the current corpus (custody isn't wired
# into eval/run.py yet), so this is synthetic-only coverage by design.
# --------------------------------------------------------------------------------- #


def test_live_credential_flags_and_upgrades_awaiting_evidence():
    d = decide(_input(verify_state="ok", has_gap=True, any_live_credential=True))
    assert d.disposition == "review_required"
    assert "live_credential_quarantined" in d.security_flags
    assert "live_credential_forces_review" in d.matched_rules


def test_live_credential_flags_without_changing_an_already_review_disposition():
    d = decide(
        _input(verify_state="ok", has_failed_check=True, job_c_invoked=True, any_live_credential=True)
    )
    assert d.disposition == "review_required"
    assert "live_credential_quarantined" in d.security_flags
    # the disposition was already review_required, so the upgrade rule never had to fire
    assert "live_credential_forces_review" not in d.matched_rules


def test_no_live_credential_no_flag():
    d = decide(_input(verify_state="ok", has_gap=True, any_live_credential=False))
    assert d.security_flags == []


# --------------------------------------------------------------------------------- #
# The decision object itself
# --------------------------------------------------------------------------------- #


def test_decision_carries_policy_version():
    d = decide(_input())
    assert d.policy_version == POLICY_VERSION


def test_decision_rejects_an_invalid_disposition():
    with pytest.raises(ValueError):
        PolicyDecision(disposition="not_a_real_disposition", policy_version=POLICY_VERSION)


def test_auto_is_a_legal_disposition_value_even_though_this_table_never_emits_it():
    # DISPOSITIONS must still contain "auto" -- it's part of the vocabulary
    # (harness/faults/base.py's FaultSpec.expected_disposition comment), even though no
    # branch in decide() currently returns it. Constructing a PolicyDecision with it
    # directly must not raise.
    d = PolicyDecision(disposition="auto", policy_version=POLICY_VERSION)
    assert d.disposition == "auto"
    assert "auto" in DISPOSITIONS
