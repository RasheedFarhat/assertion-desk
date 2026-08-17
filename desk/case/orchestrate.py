"""Drives a Case through the VERIFYING -> * transition using a real desk/pipeline.py
PipelineResult and desk/policy/rules.py's disposition decision. This is the "live case
orchestrator" desk/pipeline.py's own docstring names as not built yet, and the
prerequisite named in commit 8c8e2a7's "not in this commit" list.

Layering direction: this module depends on desk.pipeline, desk.policy.rules, and
desk.case.state -- never the reverse, matching every other cross-package dependency in
this codebase (eval/metrics.py -> desk.policy.rules; eval/run.py -> desk.pipeline).
desk/case/state.py's own docstring already designs the full disposition-to-CaseState
mapping this module implements (see its "From VERIFYING, the plan's remaining states
are reached according to..." section) -- nothing here re-derives that design, it only
executes it.

PolicyInput construction mirrors eval/metrics.py's computed_disposition() field for
field, on purpose. That function is the existing, tested translation from a pipeline
outcome to a PolicyInput, and a live orchestrator diverging from it would be exactly
the kind of silent drift this workspace's methodology exists to prevent. The one
deliberate difference: eval/metrics.py reads a persisted CaseRecord dict (eval/run.py's
JSON shape); this module reads a live desk.pipeline.PipelineResult object directly,
since a live case is never serialized to that JSON shape at all.

any_live_credential is accepted as a parameter here, not derived here, because
desk/custody's live-credential wiring is not called from any runtime path yet -- see
desk/case/state.py's own docstring for the identical, honestly-named integration gap
on the case-construction side. A future caller that has composed a real CustodyResult
passes its any_live_credential field through; until then the default (False) is
accurate, not invented.
"""

from __future__ import annotations

from desk.case.state import Case, CaseState, transition
from desk.pipeline import PipelineResult
from desk.policy.rules import PolicyDecision, PolicyInput, decide


def policy_input_from_pipeline_result(
    result: PipelineResult, *, any_live_credential: bool = False
) -> PolicyInput:
    """The live-case mirror of eval/metrics.py's computed_disposition() field
    construction -- see this module's docstring for why the two must stay in step.
    has_failed_check/has_gap are read off job_c/job_b's mere presence rather than
    recomputed from result.run, for the identical reason eval/metrics.py's own comment
    gives: eval/run.py's (and desk/pipeline.py's) invocation gate for each job already
    IS the real signal, with no need to re-derive it."""
    return PolicyInput(
        verify_state=result.verify_state,
        has_failed_check=result.job_c is not None,
        has_gap=result.job_b is not None,
        job_c_invoked=result.job_c is not None,
        grounding_accepted=result.grounding.accepted if result.grounding is not None else None,
        final_root_cause=result.final_root_cause,
        instruction_signal_detected=bool(result.job_a.instruction_signals) if result.job_a is not None else False,
        any_live_credential=any_live_credential,
    )


def next_case_state(decision: PolicyDecision, result: PipelineResult) -> CaseState:
    """Implements desk/case/state.py's own documented VERIFYING -> * mapping (see that
    module's docstring in full before touching this function). has_draft mirrors
    "grounding accepted a Job C draft" exactly: result.final_root_cause is set precisely
    when Job C ran and its claim was accepted, either by construction (the deterministic
    tier) or by desk/ground/validator.py -- see desk/pipeline.py's run_pipeline() for
    where that invariant is enforced."""
    has_draft = result.final_root_cause is not None

    if decision.disposition == "awaiting_evidence":
        return CaseState.AWAITING_EVIDENCE

    if decision.disposition in ("review_required", "escalate"):
        if has_draft:
            return CaseState.REASONED
        if decision.disposition == "review_required":
            return CaseState.HUMAN_REVIEW
        # decision.disposition == "escalate" with no draft. desk/case/state.py's
        # docstring names this ESCALATED and ties it to verify_state itself being
        # parse_error/error -- true by construction under the current pipeline, since
        # _decide_base_disposition only ever returns "escalate" for those two
        # verify_states, and job_c is never invoked for either (has_draft is always
        # False there). Asserted rather than assumed, so a future change to the policy
        # ladder that violates this invariant fails loudly here instead of silently
        # mis-routing a case.
        assert result.verify_state in ("parse_error", "error"), (
            f"policy returned escalate with no draft for verify_state={result.verify_state!r}, "
            "which desk/case/state.py's ESCALATED mapping does not account for"
        )
        return CaseState.ESCALATED

    # "auto" is the one DISPOSITIONS member desk/policy/rules.py's own docstring says
    # this rule table never emits, and desk/case/state.py's VERIFYING mapping has no
    # edge for it either -- there is no legitimate case to route here, so this is a
    # loud failure rather than a silent default, matching IllegalTransition's own
    # "caller bug, not a real-world outcome" philosophy.
    raise ValueError(
        f"desk/case/state.py's VERIFYING mapping has no defined transition for disposition {decision.disposition!r}"
    )


def advance_verifying_case(
    case: Case, result: PipelineResult, *, any_live_credential: bool = False
) -> tuple[Case, PolicyDecision]:
    """The orchestrator's one real entry point: given a Case currently in VERIFYING and
    the PipelineResult produced by running desk.pipeline.run_pipeline() against it,
    decides the disposition and drives the one legal desk/case/state.py transition it
    implies. Returns the advanced Case and the PolicyDecision that produced it, so a
    caller (desk/api.py, once it exists) can persist both and record matched_rules /
    security_flags on the case's trace.

    Deliberately does not check case.state != VERIFYING itself -- transition() is
    already the single source of truth for legal edges and raises IllegalTransition on
    anything this function's caller got wrong (a stale case read, a case still in
    CUSTODY_REVIEW). Adding a second, possibly-drifting check here would duplicate that
    authority rather than defer to it."""
    policy_input = policy_input_from_pipeline_result(result, any_live_credential=any_live_credential)
    decision = decide(policy_input)
    target_state = next_case_state(decision, result)
    advanced = transition(case, target_state, disposition=decision.disposition)
    return advanced, decision
