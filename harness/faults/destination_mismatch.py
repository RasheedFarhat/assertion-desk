"""destination_mismatch -- CONTEXT_MISMATCH. A third variant of the same ctx.acs_url
exact-match fault family (see acs_url_trailing_slash and http_https_mismatch), this time
modeling a wholesale wrong path -- the SP's config points at an entirely different
endpoint, as if it were copy-pasted from another tenant or environment. Kept distinct for
narrative variety even though the check-level signature is identical to the other two;
the corpus's narrative registers (harness/narratives/) are what actually differentiate a
support engineer's read of these three cases, not the check grid.
"""

from __future__ import annotations

import dataclasses

from desk.verify.context import VerificationContext
from harness.faults.base import FaultCategory, FaultSpec

WRONG_ACS_URL = "http://127.0.0.1:9091/legacy/saml/consume"


def _apply(ctx: VerificationContext) -> VerificationContext:
    return dataclasses.replace(ctx, acs_url=WRONG_ACS_URL)


FAULT = FaultSpec(
    fault_id="destination_mismatch",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "SP's configured ACS URL points at an entirely different path, as if copy-pasted "
        "from another tenant's config. Same DEST-01/RECIP-01 signature as the other two "
        "ACS-mismatch faults, via a distinct real-world cause."
    ),
    target_check_ids=["SAML-DEST-01", "SAML-RECIP-01"],
    expected_states={"SAML-DEST-01": "failed", "SAML-RECIP-01": "failed"},
    expected_root_cause="SAML-DEST-01",
    expected_disposition="review_required",
    difficulty="normal",
    ctx_transform=_apply,
)
