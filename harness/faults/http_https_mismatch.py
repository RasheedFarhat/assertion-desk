"""http_https_mismatch -- CONTEXT_MISMATCH. Same mechanism as acs_url_trailing_slash
(ctx.acs_url exact-match against Destination and Recipient), different real-world typo:
the SP's config has the ACS URL on the wrong scheme, e.g. an admin pasted an https:// URL
into a dev/self-hosted tenant that actually terminates on plain http. Kept as its own
fault module (rather than folded into the trailing-slash one) because it is a distinct,
independently common misconfiguration with a distinct narrative -- the check-level
signature happens to be identical, and that's reported honestly rather than hidden.
"""

from __future__ import annotations

import dataclasses

from desk.verify.context import VerificationContext
from harness.faults.base import FaultCategory, FaultSpec

WRONG_ACS_URL = "https://127.0.0.1:9091/saml/acs"


def _apply(ctx: VerificationContext) -> VerificationContext:
    return dataclasses.replace(ctx, acs_url=WRONG_ACS_URL)


FAULT = FaultSpec(
    fault_id="http_https_mismatch",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "SP's configured ACS URL uses https where the real endpoint is plain http. "
        "Same two checks as acs_url_trailing_slash fail, for the same exact-match reason, "
        "via a different real-world typo."
    ),
    target_check_ids=["SAML-DEST-01", "SAML-RECIP-01"],
    expected_states={"SAML-DEST-01": "failed", "SAML-RECIP-01": "failed"},
    expected_root_cause="SAML-DEST-01",
    expected_disposition="review_required",
    difficulty="normal",
    ctx_transform=_apply,
)
