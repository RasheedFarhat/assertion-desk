"""The case lifecycle state machine (plan section 19's Case table, section 21's approval
model). A Case moves through a fixed set of named states; state.py owns the legal
transition graph and nothing else -- it has no knowledge of Postgres/SQLite (store.py),
of what a disposition means (desk/policy), or of HTTP (desk/api.py). transition() is the
only way a Case's state field is ever allowed to change, and it raises IllegalTransition
on any edge not in CASE_TRANSITIONS -- unlike a grounding rejection or a broken trace
chain, an illegal transition is not a legitimate real-world outcome this system needs to
represent; it is a caller bug, and it should fail loudly at the call site rather than
silently persist a corrupted lifecycle.

How the plan's ten states (section 19) map onto the pipeline (section 15), and why --
this mapping is this module's own design decision, since the plan names the states but
never gives their edges:

  A Case is created already past intake+custody, since both run synchronously before
  persistence begins (architecture section 15). So case creation lands directly in
  exactly one of three states, never a fourth "new"/"received" state the plan doesn't
  name: INTAKE_FAILED (intake couldn't parse the bundle -- terminal, nothing to verify),
  CUSTODY_REVIEW (custody quarantined a currently-valid credential -- security_flags is
  non-empty, so section 21's rule ("must request approval for ... any case where
  security_flags is non-empty") fires before verification even starts), or VERIFYING
  (the normal case: custody found nothing live, verify/reason/ground/policy can run).

  desk/intake does not exist as code yet, and desk/custody's live-credential wiring is
  not called from any runtime path yet (eval/run.py evaluates the corpus directly, never
  a raw bundle -- see eval/metrics.py's computed_disposition() for the identical gap
  named on the policy side, and desk/custody/record.py's own docstring, which already
  names desk/case as its intended caller). INTAKE_FAILED and CUSTODY_REVIEW are real,
  tested states in this module's transition graph even though nothing in the codebase
  can construct a Case that starts there yet. That is an honest, named integration gap,
  not a design gap, and it is exactly the kind of thing this project's own module
  docstrings elsewhere already name rather than hide.

  From VERIFYING, the plan's remaining states are reached according to what
  desk/policy/rules.py decided, plus whether desk/ground accepted a usable draft:
    -> AWAITING_EVIDENCE   disposition == "awaiting_evidence"
    -> REASONED            disposition in {"review_required", "escalate"} and grounding
                            accepted a Job C draft -- there is something to show a human
    -> HUMAN_REVIEW        disposition == "review_required" and there is no usable draft
                            (grounding rejected it, or Job C was never invoked because no
                            check failed) -- a human works the raw check results directly
    -> ESCALATED           disposition == "escalate" and verify_state itself was
                            parse_error/error -- nothing to draft, this needs a person
                            immediately (desk/policy/rules.py's own escalate branches)

  AWAITING_EVIDENCE -> VERIFYING: WF3 (plan section 17, the evidence-chase workflow)
  re-ingests a customer reply and the case re-verifies against the new artifact.

  REASONED -> HUMAN_REVIEW: WF2's send-and-wait node actually posts the draft to an
  approver and starts waiting.

  HUMAN_REVIEW -> APPROVED | ESCALATED: the approver's decision (plan section 17's
  captured override reason lives on the Approval row, not on the Case).

  APPROVED -> PUBLISHED: the reply is actually sent / the ticket is actually updated.

  CUSTODY_REVIEW -> VERIFYING | BLOCKED: a human clears the security review and
  verification proceeds, or confirms the bundle is genuinely hostile and the case is
  blocked outright (plan section 21's "must never perform" list -- forwarding a bundle
  containing a live credential anywhere -- makes BLOCKED a dead end on purpose; nothing
  transitions out of it).

  Terminal states (no outgoing edges): INTAKE_FAILED, PUBLISHED, ESCALATED, BLOCKED.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class CaseState(str, Enum):
    INTAKE_FAILED = "intake_failed"
    CUSTODY_REVIEW = "custody_review"
    VERIFYING = "verifying"
    AWAITING_EVIDENCE = "awaiting_evidence"
    REASONED = "reasoned"
    HUMAN_REVIEW = "human_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ESCALATED = "escalated"
    BLOCKED = "blocked"


# The only three states a Case may be constructed directly into -- see this module's
# docstring for why there is no separate "new"/"received" state.
INITIAL_STATES = frozenset({CaseState.INTAKE_FAILED, CaseState.CUSTODY_REVIEW, CaseState.VERIFYING})

# States with no outgoing edge. A Case in one of these never transitions again.
TERMINAL_STATES = frozenset({CaseState.INTAKE_FAILED, CaseState.PUBLISHED, CaseState.ESCALATED, CaseState.BLOCKED})

CASE_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.INTAKE_FAILED: frozenset(),
    CaseState.CUSTODY_REVIEW: frozenset({CaseState.VERIFYING, CaseState.BLOCKED}),
    CaseState.VERIFYING: frozenset(
        {
            CaseState.AWAITING_EVIDENCE,
            CaseState.REASONED,
            CaseState.HUMAN_REVIEW,
            CaseState.ESCALATED,
        }
    ),
    CaseState.AWAITING_EVIDENCE: frozenset({CaseState.VERIFYING}),
    CaseState.REASONED: frozenset({CaseState.HUMAN_REVIEW}),
    CaseState.HUMAN_REVIEW: frozenset({CaseState.APPROVED, CaseState.ESCALATED}),
    CaseState.APPROVED: frozenset({CaseState.PUBLISHED}),
    CaseState.PUBLISHED: frozenset(),
    CaseState.ESCALATED: frozenset(),
    CaseState.BLOCKED: frozenset(),
}

# Every state named in the enum must have an explicit (possibly empty) entry above -- a
# state missing from this table entirely would silently allow no transitions in a way
# indistinguishable from a deliberately terminal state. Checked at import time, not just
# in a test, so a future edit that adds a CaseState value without wiring its edges fails
# immediately rather than shipping a case that can never transition anywhere.
assert set(CASE_TRANSITIONS) == set(CaseState), "CASE_TRANSITIONS is missing an entry for a CaseState value"
assert TERMINAL_STATES == {s for s, edges in CASE_TRANSITIONS.items() if not edges}, (
    "TERMINAL_STATES has drifted from the states CASE_TRANSITIONS actually gives no outgoing edges to"
)


class IllegalTransition(Exception):
    """Raised when code asks for a state change CASE_TRANSITIONS does not allow. This is
    always a caller bug (a missing branch in the orchestrator, a stale state read before
    the transition), never a legitimate outcome to route around -- see this module's
    docstring for why that is a deliberate difference from desk/ground's
    rejection-as-data pattern.

    `.detail` is always set from a literal f-string built here, in this module, from
    known-safe data (a CaseState value, a case id the caller already supplied) -- never
    from wrapping another exception. desk/api.py's HTTP handlers return `.detail` to the
    client rather than `str(exc)` so that guarantee holds by construction: nothing this
    class's constructor is ever called with can carry a stack trace, a file path, or
    another exception's message through to an API response."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class Case:
    id: str
    correlation_id: str
    tenant_ref: str | None
    state: CaseState
    disposition: str | None
    created_at: str
    updated_at: str
    security_flags: tuple[str, ...] = ()


def new_case(
    id: str,
    correlation_id: str,
    state: CaseState,
    tenant_ref: str | None = None,
    security_flags: tuple[str, ...] = (),
    at: str | None = None,
) -> Case:
    if state not in INITIAL_STATES:
        raise IllegalTransition(
            f"a Case cannot be created directly into state {state.value!r}; "
            f"must be one of {sorted(s.value for s in INITIAL_STATES)}"
        )
    now = at or datetime.now(timezone.utc).isoformat()
    return Case(
        id=id,
        correlation_id=correlation_id,
        tenant_ref=tenant_ref,
        state=state,
        disposition=None,
        created_at=now,
        updated_at=now,
        security_flags=tuple(security_flags),
    )


def transition(case: Case, to: CaseState, disposition: str | None = None, at: str | None = None) -> Case:
    """Returns a new Case with .state advanced to `to`. Raises IllegalTransition if
    `case.state -> to` is not an edge in CASE_TRANSITIONS. disposition is only ever set
    here, never mutated afterward once set -- pass it on the transition that computed it
    (normally the VERIFYING -> * edge, once desk/policy/rules.py has decided); omitting
    it on a later transition (e.g. HUMAN_REVIEW -> APPROVED) leaves the case's existing
    disposition untouched rather than clearing it."""
    legal = CASE_TRANSITIONS.get(case.state, frozenset())
    if to not in legal:
        raise IllegalTransition(
            f"case {case.id}: {case.state.value!r} -> {to.value!r} is not a legal transition "
            f"(legal from {case.state.value!r}: {sorted(s.value for s in legal) or 'none, this is a terminal state'})"
        )
    now = at or datetime.now(timezone.utc).isoformat()
    return Case(
        id=case.id,
        correlation_id=case.correlation_id,
        tenant_ref=case.tenant_ref,
        state=to,
        disposition=disposition if disposition is not None else case.disposition,
        created_at=case.created_at,
        updated_at=now,
        security_flags=case.security_flags,
    )


def is_terminal(state: CaseState) -> bool:
    return state in TERMINAL_STATES
