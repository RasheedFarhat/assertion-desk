"""wrong_audience -- CONTEXT_MISMATCH. Real response, real cert, real timestamps. The
fault is that the SP's own configured entity ID (the value ctx.sp_entity_id supplies)
does not match what the real assertion's Audience list actually contains -- as if the SP
were configured under a stale or copy-pasted entity ID. Isolated: SAML-AUD-01 is the only
check that reads ctx.sp_entity_id, so nothing else in the grid moves.
"""

from __future__ import annotations

import dataclasses

from desk.verify.context import VerificationContext
from harness.faults.base import FaultCategory, FaultSpec

WRONG_SP_ENTITY_ID = "http://127.0.0.1:9091/saml/metadata-old"


def _apply(ctx: VerificationContext) -> VerificationContext:
    return dataclasses.replace(ctx, sp_entity_id=WRONG_SP_ENTITY_ID)


FAULT = FaultSpec(
    fault_id="wrong_audience",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "SP's configured entity ID does not match what the real assertion's Audience "
        "list actually contains -- a stale or copy-pasted SP entity ID in the trust "
        "configuration, not anything wrong with the assertion itself."
    ),
    target_check_ids=["SAML-AUD-01"],
    expected_states={"SAML-AUD-01": "failed"},
    expected_root_cause="SAML-AUD-01",
    expected_disposition="review_required",
    difficulty="normal",
    ctx_transform=_apply,
)
