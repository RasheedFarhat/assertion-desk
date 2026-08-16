"""assertion_expired -- CONTEXT_MISMATCH. Offsets ONLY ctx.evaluation_time, past the real
assertion's own Conditions NotOnOrAfter (06:59:51.491Z) and SubjectConfirmationData
NotOnOrAfter (06:55:51.491Z) but nowhere near the trusted cert's real 2036 expiry -- so
SAML-CERT-01 stays verified. sp_clock is left at baseline, so SAML-SKEW-01 (which reads
sp_clock, not evaluation_time) is unaffected. This isolates "the assertion was replayed
or reviewed too late" from cert_expired's necessarily-coupled scenario (see that module's
docstring for why cert expiry can't be isolated the same way).
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from desk.verify.context import VerificationContext
from harness.faults import baseline
from harness.faults.base import FaultCategory, FaultSpec

# Comfortably past both real NotOnOrAfter values (06:55:51Z and 06:59:51Z), well short of
# the cert's 2036 expiry.
EXPIRED_EVAL_TIME = baseline.GOOD_EVALUATION_TIME + timedelta(minutes=10)


def _apply(ctx: VerificationContext) -> VerificationContext:
    return dataclasses.replace(ctx, evaluation_time=EXPIRED_EVAL_TIME)


FAULT = FaultSpec(
    fault_id="assertion_expired",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "SP evaluates the assertion after both its Conditions and SubjectConfirmationData "
        "windows have closed -- a stale or replayed assertion, e.g. a customer resubmitting "
        "an old SAMLResponse from a support ticket rather than a fresh login."
    ),
    target_check_ids=["SAML-COND-01", "SAML-COND-02"],
    expected_states={"SAML-COND-01": "failed", "SAML-COND-02": "failed"},
    expected_root_cause="SAML-COND-01",
    expected_disposition="review_required",
    difficulty="normal",
    ctx_transform=_apply,
)
