"""acs_url_trailing_slash -- CONTEXT_MISMATCH. The single most common real-world SAML
typo: someone re-entered the ACS URL into the IdP's app config (or the SP's own record of
it) with a trailing slash the real endpoint doesn't have. desk/verify/checks/destination.py
compares both Destination and Recipient by exact string match against ctx.acs_url on
purpose -- SAML has no "close enough" URL comparison, and this fault exists specifically
to demonstrate why that matters. Both checks read the same ctx.acs_url field, so both
fail together; nothing else in the grid is touched.
"""

from __future__ import annotations

import dataclasses

from desk.verify.context import VerificationContext
from harness.faults import baseline
from harness.faults.base import FaultCategory, FaultSpec

WRONG_ACS_URL = baseline.SP_ACS_URL + "/"


def _apply(ctx: VerificationContext) -> VerificationContext:
    return dataclasses.replace(ctx, acs_url=WRONG_ACS_URL)


FAULT = FaultSpec(
    fault_id="acs_url_trailing_slash",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "SP's configured ACS URL carries a trailing slash the real endpoint doesn't have. "
        "Exact-match comparison correctly rejects it -- SAML has no notion of "
        "URL-equivalent-but-not-identical."
    ),
    target_check_ids=["SAML-DEST-01", "SAML-RECIP-01"],
    expected_states={"SAML-DEST-01": "failed", "SAML-RECIP-01": "failed"},
    expected_root_cause="SAML-DEST-01",
    expected_disposition="review_required",
    difficulty="normal",
    ctx_transform=_apply,
)
