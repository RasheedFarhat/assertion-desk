"""Tests for desk/case/orchestrate.py -- the live case orchestrator that ties
desk/pipeline.run_pipeline()'s output through desk/policy/rules.py's decide() to
desk/case/state.py's transition(). Real corpus cases drive the scenarios
desk/case/state.py's own docstring documents (REASONED, AWAITING_EVIDENCE,
HUMAN_REVIEW, ESCALATED); a couple of directly-constructed PipelineResult/
PolicyDecision objects cover edge cases no corpus case currently exercises (the
"auto" disposition, which desk/policy/rules.py's own docstring says its rule table
never emits, and the escalate-with-a-draft branch, which the current pipeline wiring
never produces either -- see next_case_state()'s own comment)."""

from __future__ import annotations

import pytest

from desk.case.orchestrate import advance_verifying_case, next_case_state, policy_input_from_pipeline_result
from desk.case.state import CaseState, IllegalTransition, new_case
from desk.pipeline import PipelineResult, run_pipeline
from desk.policy.rules import PolicyDecision
from desk.reason.fixtures import FixtureCache
from eval.run import CASES_DIR, build_clients, load_context, load_narrative

CERT_EXPIRED_DIR = CASES_DIR / "cert_expired"
WITHHELD_CLOCK_DIR = CASES_DIR / "withheld_clock"
NEGATIVE_CONTROL_DIR = CASES_DIR / "negative_control"
TRUNCATED_RESPONSE_DIR = CASES_DIR / "truncated_response"


def _run(case_dir):
    ctx = load_context(case_dir)
    narrative = load_narrative(case_dir)
    saml_path = case_dir / "saml_response.xml"
    raw = saml_path.read_bytes() if saml_path.exists() else None
    return run_pipeline(
        raw_saml_response=raw,
        ctx=ctx,
        narrative=narrative,
        clients=build_clients(),
        fixtures=FixtureCache(),
        replay_only=True,
    )


def _verifying_case():
    return new_case(id="case-1", correlation_id="corr-1", state=CaseState.VERIFYING)


# --------------------------------------------------------------------------------- #
# Real corpus cases, end to end through advance_verifying_case()
# --------------------------------------------------------------------------------- #


def test_clean_fault_with_a_grounded_draft_lands_in_reasoned():
    """cert_expired: has_failed_check True, Job C's claim grounded, final_root_cause
    set -> disposition review_required with a usable draft -> REASONED."""
    result = _run(CERT_EXPIRED_DIR)
    assert result.final_root_cause is not None  # sanity: this scenario needs a draft

    advanced, decision = advance_verifying_case(_verifying_case(), result)

    assert decision.disposition == "review_required"
    assert advanced.state == CaseState.REASONED
    assert advanced.disposition == "review_required"


def test_ambiguous_case_with_a_real_gap_lands_in_awaiting_evidence():
    """withheld_clock: no failed check, but compute_gaps(run) is non-empty (Job B ran)
    -> disposition awaiting_evidence -> AWAITING_EVIDENCE."""
    result = _run(WITHHELD_CLOCK_DIR)
    assert result.job_b is not None  # sanity: this scenario needs a real gap

    advanced, decision = advance_verifying_case(_verifying_case(), result)

    assert decision.disposition == "awaiting_evidence"
    assert advanced.state == CaseState.AWAITING_EVIDENCE


def test_no_failure_no_gap_lands_in_human_review_with_no_draft():
    """negative_control: verify_state is no_saml_response, no failed check, no gap
    (Job B never ran because there was no VerificationRun to compute gaps from) ->
    _decide_base_disposition's "no_failure_no_gap" branch -> review_required, and
    with no Job C draft that is HUMAN_REVIEW, not REASONED."""
    result = _run(NEGATIVE_CONTROL_DIR)
    assert result.job_b is None
    assert result.final_root_cause is None

    advanced, decision = advance_verifying_case(_verifying_case(), result)

    assert decision.disposition == "review_required"
    assert advanced.state == CaseState.HUMAN_REVIEW


def test_parse_failure_lands_in_escalated():
    """truncated_response: label.json's own expects_parse_failure=True and
    expected_disposition="escalate" -- run_pipeline sets verify_state="parse_error",
    Job C never runs (no draft), so this is desk/case/state.py's documented
    "escalate and verify_state itself was parse_error/error" -> ESCALATED."""
    result = _run(TRUNCATED_RESPONSE_DIR)
    assert result.verify_state == "parse_error"
    assert result.final_root_cause is None

    advanced, decision = advance_verifying_case(_verifying_case(), result)

    assert decision.disposition == "escalate"
    assert advanced.state == CaseState.ESCALATED


def test_advance_verifying_case_raises_on_a_case_not_in_verifying():
    """transition()'s own authority, not a redundant check in the orchestrator --
    confirms advance_verifying_case() does not silently swallow an illegal edge."""
    result = _run(CERT_EXPIRED_DIR)
    # CUSTODY_REVIEW is a legal *initial* state but VERIFYING -> REASONED is not legal
    # from it -- construct a case that starts in CUSTODY_REVIEW instead to prove the
    # illegal edge is caught.
    custody_case = new_case(id="case-2", correlation_id="corr-2", state=CaseState.CUSTODY_REVIEW)

    with pytest.raises(IllegalTransition):
        advance_verifying_case(custody_case, result)

    # sanity: the same result, from the correct starting state, succeeds
    advance_verifying_case(_verifying_case(), result)


# --------------------------------------------------------------------------------- #
# Edge cases no corpus case currently exercises -- directly-constructed inputs
# --------------------------------------------------------------------------------- #


def test_next_case_state_raises_on_auto_disposition():
    """desk/policy/rules.py's own docstring: "auto" is a defined DISPOSITIONS member
    its rule table never emits, and desk/case/state.py's VERIFYING mapping has no edge
    for it either. next_case_state() must fail loudly rather than guess."""
    decision = PolicyDecision(disposition="auto", policy_version="1")
    result = PipelineResult(
        verify_state="ok",
        run=None,
        job_a=None,
        job_b=None,
        job_c=None,
        grounding=None,
        final_root_cause=None,
    )

    with pytest.raises(ValueError, match="auto"):
        next_case_state(decision, result)


def test_next_case_state_routes_escalate_with_a_draft_to_reasoned():
    """The current pipeline never produces escalate-with-a-draft (see
    next_case_state()'s own comment), but desk/case/state.py's documented mapping is
    general: disposition in {review_required, escalate} with an accepted Job C draft
    is REASONED regardless of which of the two dispositions it is. Constructed
    directly since no corpus case reaches this branch."""
    decision = PolicyDecision(disposition="escalate", policy_version="1")
    result = PipelineResult(
        verify_state="ok",
        run=None,
        job_a=None,
        job_b=None,
        job_c=None,
        grounding=None,
        final_root_cause="SAML-CERT-01",
    )

    assert next_case_state(decision, result) == CaseState.REASONED


def test_next_case_state_asserts_on_escalate_with_no_draft_and_an_ok_verify_state():
    """The invariant next_case_state() asserts rather than assumes: escalate with no
    draft is only ever meaningful when verify_state itself was parse_error/error.
    A hypothetical policy bug that returned escalate-with-no-draft alongside
    verify_state="ok" must fail loudly here, not silently mis-route to ESCALATED."""
    decision = PolicyDecision(disposition="escalate", policy_version="1")
    result = PipelineResult(
        verify_state="ok",
        run=None,
        job_a=None,
        job_b=None,
        job_c=None,
        grounding=None,
        final_root_cause=None,
    )

    with pytest.raises(AssertionError):
        next_case_state(decision, result)


def test_policy_input_from_pipeline_result_reads_instruction_signals_off_job_a():
    """instruction_signal_detected must come from job_a.instruction_signals (the only
    job that ever populates it -- see desk/policy/rules.py's INJECTION SIGNAL SCOPE
    note), and must be False, not an error, when job_a is None entirely."""
    from desk.reason.jobs import JobResult

    job_a_with_signal = JobResult(
        job="A",
        tier_used="fixture",
        parsed={},
        schema_violations=[],
        accepted=True,
        prompt_sha256="deadbeef",
        latency_ms=None,
        input_tokens=None,
        output_tokens=None,
        instruction_signals=[{"taxonomy_class": "S1_direct_override"}],
    )
    result_with_signal = PipelineResult(
        verify_state="ok", run=None, job_a=job_a_with_signal, job_b=None, job_c=None,
        grounding=None, final_root_cause=None,
    )
    result_without_job_a = PipelineResult(
        verify_state="ok", run=None, job_a=None, job_b=None, job_c=None,
        grounding=None, final_root_cause=None,
    )

    assert policy_input_from_pipeline_result(result_with_signal).instruction_signal_detected is True
    assert policy_input_from_pipeline_result(result_without_job_a).instruction_signal_detected is False


def test_advance_verifying_case_threads_any_live_credential_into_security_flags():
    """any_live_credential=True must reach desk/policy/rules.py's decide() and produce
    the live_credential_quarantined security flag on the returned PolicyDecision --
    the one field this orchestrator accepts as a parameter rather than deriving, per
    this module's own docstring (desk/custody isn't wired into any runtime path yet)."""
    result = _run(WITHHELD_CLOCK_DIR)  # base disposition would be awaiting_evidence

    advanced, decision = advance_verifying_case(_verifying_case(), result, any_live_credential=True)

    assert "live_credential_quarantined" in decision.security_flags
    # a live credential must never ride the lower-touch awaiting_evidence path
    assert decision.disposition == "review_required"
    assert advanced.state == CaseState.HUMAN_REVIEW
