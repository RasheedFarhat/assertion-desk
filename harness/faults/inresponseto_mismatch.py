"""inresponseto_mismatch -- CONTEXT_MISMATCH. The real captured response genuinely
carries InResponseTo (ONELOGIN_89b49ed92bc12dd359397307721f4ae3a0bed637 -- confirmed by
reading the real XML directly; this flow is SP-initiated, not IdP-initiated as an earlier
draft of this catalogue assumed). ctx.in_response_to_expected is set to a different value,
modeling an SP that lost track of its own outbound request ID (e.g. a load-balanced SP
whose request-state store didn't replicate, or a request that legitimately timed out and
was retried under a new ID). SAML-INRESP-01 (Response) and SAML-INRESP-02
(SubjectConfirmationData) both compare against the same ctx field, so both fail.
"""

from __future__ import annotations

import dataclasses

from desk.verify.context import VerificationContext
from harness.faults.base import FaultCategory, FaultSpec

WRONG_EXPECTED_REQUEST_ID = "ONELOGIN_00000000000000000000000000000000000000"


def _apply(ctx: VerificationContext) -> VerificationContext:
    return dataclasses.replace(ctx, in_response_to_expected=WRONG_EXPECTED_REQUEST_ID)


FAULT = FaultSpec(
    fault_id="inresponseto_mismatch",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "SP's expected outbound request ID doesn't match the real InResponseTo the "
        "response carries -- the SP lost track of its own request state, e.g. a "
        "load-balanced instance whose request store didn't replicate."
    ),
    target_check_ids=["SAML-INRESP-01", "SAML-INRESP-02"],
    expected_states={"SAML-INRESP-01": "failed", "SAML-INRESP-02": "failed"},
    expected_root_cause="SAML-INRESP-01",
    expected_disposition="review_required",
    difficulty="normal",
    ctx_transform=_apply,
)
