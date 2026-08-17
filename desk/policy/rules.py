"""The disposition policy (plan section 15/19/21): the last deterministic gate before
a case is allowed to leave analysis and enter the human-approval/publish path. No AI
call happens in this module and none of its inputs are model output text -- every
field on PolicyInput is either a verifier fact, a grounding-validator verdict, a
custody-scan fact, or a pre-call structural signal computed over customer-controlled
text before it reached a model. That is deliberate: desk/ground already vetoes an
individual Job C claim; this module decides what happens to the *case*, and it must
stay trustworthy even if desk/ground had a bug, so it never reads a model's parsed
content directly.

Disposition vocabulary matches harness/faults/base.py's FaultSpec.expected_disposition
comment exactly: auto | review_required | escalate | awaiting_evidence. `auto` is
defined in that vocabulary but this rule table never emits it -- see the docstring on
_decide_base_disposition for why that is a real property of the rule table, not an
oversight, and matches the fact that zero corpus cases have expected_disposition ==
"auto" either (confirmed by inspection of all 51 label.json files, 2026-08-17).

Default-deny (plan section 15's table: "Unknown state -> review. Default deny"): any
verify_state this table does not explicitly recognize resolves to review_required, the
same as the recognized-but-inconclusive branch. There is no silent pass-through.

Ground-truth-leakage boundary, the design rule this module is built to obey: nothing
here may read a corpus label field (label.json's difficulty, target_check_ids,
expected_disposition, or the injection taxonomy_class). Those exist only to grade this
module from the outside, in eval/metrics.py; grading logic and decision logic must stay
on opposite sides of that line or the "measured" claim in docs/MEASUREMENTS.md becomes
circular. See the KNOWN_MISMATCH note below for the one case where obeying this rule
has a real, named cost.

KNOWN, NAMED MISMATCH -- duplicate_role_attributes. eval/metrics.py's own module
docstring already flags this (read it before changing this file): duplicate_role_attributes
(the corpus's one `conflicting` case) and withheld_cert/withheld_clock (the two
`ambiguous` cases) produce IDENTICAL real pipeline signals -- verify_state "ok", no
FAILED check, a real gap (compute_gaps(run) non-empty), Job C never invoked because
eval/run.py's Job C gate is run.has_any_failed() and duplicate_role_attributes's one
real finding (SAML-ATTR-01) is REVIEW_REQUIRED, not FAILED. desk/ground/validator.py's
_LEGAL_ROOT_CAUSE_STATES would accept a REVIEW_REQUIRED-based root cause if Job C were
ever asked, but it structurally never is for this case. The only place the distinction
is recorded is label.json's target_check_ids -- corpus-label-only ground truth. Reading
it here to force a match would be exactly the leakage this module refuses to do. So:
this rule table computes awaiting_evidence for duplicate_role_attributes, disagreeing
with its label's review_required. That is accepted, on purpose, as a real, honestly-
reported limitation -- see tests/policy/test_rules.py's corpus parity test, which
asserts the mismatch stays a mismatch rather than hiding it, and eval/metrics.py's
disposition_accuracy(), which reports it by name rather than excluding it silently.

INJECTION SIGNAL SCOPE -- narrower than it sounds. instruction_signal_detected is real
(desk/reason/prompts.py's detect_instruction_shaped_spans(), run pre-call against
de-fanged customer prose), but desk/reason/jobs.py only calls it from run_job_a, over
the narrative subject/body. run_job_b and run_job_c hard-code instruction_signals=[]
with a comment explaining why (Job B reads deterministic gap data + already-extracted
facts, Job C reads check results -- neither reads raw customer prose). Of the corpus's
4 adversarial cases, only clock_skew__adv_s3_context_manipulation carries its payload
in the narrative; the other three (cert_rotation__adv_s1_direct_override,
wrong_issuer__adv_s2_persona_hijack, assertion_expired__adv_s4_obfuscated) carry theirs
in a HAR header or an XML comment, which nothing in this pipeline scans for
instruction-shaped spans yet. This module's injection branch is real defense-in-depth,
not a complete injection detector, and it happens to be moot for grading this corpus:
all 4 adversarial cases already have a genuine FAILED check independent of their
injection payload, so has_failed_check routes them to review_required regardless of
whether instruction_signal_detected fires. Widening span detection to HAR headers and
XML comments is future work, not claimed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

POLICY_VERSION = "1"

# Matches harness/faults/base.py's FaultSpec.expected_disposition comment exactly.
DISPOSITIONS = frozenset({"auto", "review_required", "escalate", "awaiting_evidence"})


@dataclass(frozen=True)
class PolicyInput:
    """Every field here must be traceable to a real, already-implemented, production-
    realistic pipeline signal -- never a corpus label field. See the module docstring's
    ground-truth-leakage boundary."""

    verify_state: str  # "ok" | "parse_error" | "no_saml_response" | "error"
    has_failed_check: bool  # True iff the real VerificationRun had >=1 FAILED check
    has_gap: bool  # True iff compute_gaps(run) was non-empty (verify_state == "ok" only)
    job_c_invoked: bool  # whether Job C actually ran (currently == has_failed_check;
    # kept as its own field because the two are only accidentally equal under
    # eval/run.py's current has_any_failed() gate, and a future gate change should not
    # have to touch every call site that means "a failed check exists")
    grounding_accepted: bool | None  # None when Job C wasn't invoked or was grounded
    # by construction (the deterministic tier; see eval/run.py's own comment on why
    # that path is never sent through the grounding validator)
    final_root_cause: str | None
    instruction_signal_detected: bool = False  # see module docstring's INJECTION
    # SIGNAL SCOPE note -- narrative surface only
    any_live_credential: bool = False  # desk/custody/scan.py's CustodyResult.any_live_credential;
    # NOT currently wired into eval/run.py's CaseRecord (custody isn't in the eval
    # pipeline at all yet -- see eval/metrics.py's adapter), so this is always False
    # for every corpus-driven PolicyInput today. Real for a live case built from an
    # actual CustodyResult once desk/case/ composes the full pipeline.


@dataclass(frozen=True)
class PolicyDecision:
    disposition: str
    policy_version: str
    matched_rules: list[str] = field(default_factory=list)
    security_flags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.disposition not in DISPOSITIONS:
            raise ValueError(f"disposition {self.disposition!r} is not in {sorted(DISPOSITIONS)}")


def _decide_base_disposition(inp: PolicyInput, matched_rules: list[str]) -> str:
    """The verify_state / failed-check / gap ladder. Never returns "auto": every
    branch below is either a real finding that needs a human to read it
    (review_required/escalate) or a state that plan section 21 already classifies as
    something the system "may perform automatically" without it being a disposition
    that clears the case for the customer-facing path on its own (awaiting_evidence).
    Plan section 21's "must request approval for anything sent to the customer" makes
    `auto` unreachable for any disposition that itself authorizes a customer-facing
    artifact -- there is no branch here where that requirement is satisfiable without
    review, so none is written. This matches the corpus exactly: 0 of 51 labels use
    expected_disposition "auto" (confirmed by inspection, 2026-08-17)."""

    if inp.verify_state == "parse_error":
        matched_rules.append("artifact_did_not_parse")
        return "escalate"

    if inp.verify_state == "error":
        matched_rules.append("internal_verification_error")
        return "escalate"

    if inp.verify_state in ("ok", "no_saml_response"):
        if inp.has_failed_check:
            matched_rules.append("failed_check_present")
            return "review_required"
        if inp.has_gap:
            matched_rules.append("evidence_gap_present_no_failure")
            return "awaiting_evidence"
        matched_rules.append("no_failure_no_gap")
        return "review_required"

    # Unknown verify_state: default-deny per plan section 15's policy table.
    matched_rules.append("unknown_verify_state_default_deny")
    return "review_required"


def decide(inp: PolicyInput) -> PolicyDecision:
    matched_rules: list[str] = []
    security_flags: list[str] = []

    disposition = _decide_base_disposition(inp, matched_rules)

    # A grounding rejection means a Job C output existed and made an unverifiable
    # claim -- that is itself a signal worth a human, even though has_failed_check
    # already routed the case to review_required in every case where Job C could have
    # run (Job C's own gate is has_failed_check under eval/run.py's current wiring).
    # Recorded as a matched rule regardless, so the decision's audit trail names the
    # rejection rather than leaving it implicit in a null final_root_cause.
    if inp.job_c_invoked and inp.grounding_accepted is False:
        matched_rules.append("grounding_rejected_job_c_output")
        if disposition == "awaiting_evidence":
            disposition = "review_required"

    # Never let a case with a suspected prompt-injection payload proceed on the
    # lower-touch awaiting_evidence path -- see the module docstring's INJECTION
    # SIGNAL SCOPE note for what this can and cannot see today.
    if inp.instruction_signal_detected:
        matched_rules.append("instruction_shaped_span_detected")
        if disposition == "awaiting_evidence":
            disposition = "review_required"

    # T1 (plan section 20): a currently-valid credential in the customer's bundle
    # always gets a named flag, and it is never allowed to ride the lower-touch
    # awaiting_evidence path without a human aware of it.
    if inp.any_live_credential:
        security_flags.append("live_credential_quarantined")
        if disposition == "awaiting_evidence":
            matched_rules.append("live_credential_forces_review")
            disposition = "review_required"

    return PolicyDecision(
        disposition=disposition,
        policy_version=POLICY_VERSION,
        matched_rules=matched_rules,
        security_flags=security_flags,
    )
