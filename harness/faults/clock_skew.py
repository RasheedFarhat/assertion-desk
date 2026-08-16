"""clock_skew -- CONTEXT_MISMATCH. Offsets ONLY ctx.sp_clock, the independent SP-side
clock evidence SAML-SKEW-01 compares against the response's own claimed IssueInstant.
evaluation_time is deliberately left at baseline.good_context()'s value, so ctx.now()
(what SAML-CERT-01 and SAML-COND-01/02 read) is untouched -- desk/verify/context.py keeps
these two clock concepts genuinely independent, and this fault is the demonstration case
for why SAML-SKEW-01 needs its own evidence rather than trusting the message to describe
its own timing.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from desk.verify.context import VerificationContext
from harness.faults import baseline
from harness.faults.base import FaultCategory, FaultSpec

# 10 minutes off IssueInstant, comfortably past the 180s default tolerance.
SKEWED_SP_CLOCK = baseline.GOOD_EVALUATION_TIME + timedelta(minutes=10)


def _apply(ctx: VerificationContext) -> VerificationContext:
    return dataclasses.replace(ctx, sp_clock=SKEWED_SP_CLOCK)


FAULT = FaultSpec(
    fault_id="clock_skew",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "SP's own clock (independent evidence, not read from the response) is 10 minutes "
        "off the response's IssueInstant -- a drifted or misconfigured SP host clock, the "
        "textbook cause of intermittent SSO failures that 'work sometimes.'"
    ),
    target_check_ids=["SAML-SKEW-01"],
    expected_states={"SAML-SKEW-01": "failed"},
    expected_root_cause="SAML-SKEW-01",
    expected_disposition="review_required",
    difficulty="normal",
    ctx_transform=_apply,
)
