"""stripped_relaystate -- ARTIFACT_MUTATION on the HAR (mutations.strip_relaystate_param),
not on the SAMLResponse XML. Removes the real RelayState form field from the ACS POST
entry, simulating an IdP or an intermediate proxy that drops it in transit -- the
customer ends up authenticated but not returned to the page they started from.

RelayState is transport-layer (SAML core 3.4.3): it lives in the HAR's POST body
alongside SAMLResponse, never inside the SAMLResponse XML itself, and no check in
desk/verify/checks/ reads the HAR at all -- the whole check catalogue operates on the
parsed SAMLResponse. Verification therefore runs to completion and reports every trust-
chain check VERIFIED, correctly, because the trust chain genuinely is intact. The actual
customer complaint (landed on the wrong page after login) is real and unexplained by any
check result -- an honest, named coverage gap rather than a silently absent one.

no_check_coverage_reason is the correct escape hatch here, not expects_parse_failure: the
SAMLResponse parses and verifies fine on its own, the gap is specifically that nothing
inspects RelayState's presence or destination.
"""

from __future__ import annotations

from harness.faults import mutations
from harness.faults.base import FaultCategory, FaultSpec


def _apply(har: dict) -> dict:
    return mutations.strip_relaystate_param(har)


FAULT = FaultSpec(
    fault_id="stripped_relaystate",
    category=FaultCategory.ARTIFACT_MUTATION,
    description=(
        "RelayState is missing from the ACS POST. The trust chain itself is fully "
        "intact and every check verifies clean -- the customer's actual complaint (landed "
        "on the wrong page post-login) is real but outside what this verifier inspects."
    ),
    no_check_coverage_reason=(
        "RelayState lives in the HAR/transport layer (the ACS POST body), not inside the "
        "parsed SAMLResponse XML desk/verify/checks/ operates on. No check in the current "
        "catalogue reads RelayState's presence, value, or destination."
    ),
    expected_disposition="review_required",
    difficulty="normal",
    har_transform=_apply,
)
