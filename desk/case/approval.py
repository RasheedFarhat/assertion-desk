"""A human approver's decision on a case in HUMAN_REVIEW (plan section 19's Approval
table, section 17's WF2 "captures approver, timestamp, decision, and free-text override
reason on reject"). Mirrors desk/case/trace.py's convention deliberately: a frozen
dataclass plus one pure builder function that computes and returns a value without
persisting it -- record_decision() takes an already-decided id, exactly like
desk/case/state.py's new_case() takes an already-decided id, because nothing in this
codebase's domain layer generates its own identifiers (that stays the caller's job, so
desk/api.py or a future orchestrator controls id generation the same way it already
controls Case ids).

Only two decisions exist here, not three, because desk/case/state.py's own transition
graph only gives HUMAN_REVIEW two outgoing edges: APPROVED and ESCALATED. The plan's
demo language ("Approve / Reject / Edit") describes the WF2 UI choice a human sees, not
a fourth CaseState the state machine would need to represent -- "reject" and "edit
then reject" both mean "this case needs a person to look further," which is exactly
what ESCALATED already models. Squaring the two would need a new CaseState with no
plan-defined edges, so this module deliberately picks the reading that costs nothing
new."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

DECISIONS = frozenset({"approved", "escalated"})


@dataclass(frozen=True)
class Approval:
    id: str
    case_id: str
    approver: str
    decision: str
    responded_at: str
    override_reason: str | None
    channel: str
    latency_seconds: float | None


def record_decision(
    id: str,
    case_id: str,
    approver: str,
    decision: str,
    *,
    channel: str,
    override_reason: str | None = None,
    requested_at: str | None = None,
    responded_at: str | None = None,
) -> Approval:
    """requested_at, when supplied, is the timestamp the case actually entered
    HUMAN_REVIEW (its Case.updated_at at that transition, or the matching TraceEvent's
    `at`) -- passing it lets this function compute latency_seconds itself rather than
    making every caller re-derive the same subtraction. Omit it (the common case for a
    hand-built Approval in a test) and latency_seconds is honestly None rather than a
    fabricated zero.

    escalated decisions require override_reason -- plan section 17 names the override
    reason as the input to the human-override-rate metric, and an escalation with no
    stated reason would make that metric silently swallow a data point. approved
    decisions may still carry one (an approver can approve with a caveat noted), so this
    is a one-way requirement, not a leave-it-blank-if-you-agree rule."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}, got {decision!r}")
    if decision == "escalated" and not override_reason:
        raise ValueError("an escalated decision requires a non-empty override_reason")

    responded = responded_at or datetime.now(timezone.utc).isoformat()
    latency_seconds: float | None = None
    if requested_at is not None:
        latency_seconds = (
            datetime.fromisoformat(responded) - datetime.fromisoformat(requested_at)
        ).total_seconds()

    return Approval(
        id=id,
        case_id=case_id,
        approver=approver,
        decision=decision,
        responded_at=responded,
        override_reason=override_reason,
        channel=channel,
        latency_seconds=latency_seconds,
    )
