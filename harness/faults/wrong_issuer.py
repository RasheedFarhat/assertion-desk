"""wrong_issuer -- CONTEXT_MISMATCH. The SP's configured expectation of which IdP entity
ID it trusts doesn't match the real Issuer the response and assertion actually carry --
as if the SP were pointed at a stale realm identifier (e.g. after an IdP realm rename or
a copy-paste from a different Keycloak environment). Both SAML-ISS-01 (Response Issuer)
and SAML-ISS-02 (Assertion Issuer) read ctx.idp_entity_id, so both fail together; nothing
else in the grid is touched.
"""

from __future__ import annotations

import dataclasses

from desk.verify.context import VerificationContext
from harness.faults.base import FaultCategory, FaultSpec

WRONG_IDP_ENTITY_ID = "http://127.0.0.1:8080/realms/assertion-desk-old"


def _apply(ctx: VerificationContext) -> VerificationContext:
    return dataclasses.replace(ctx, idp_entity_id=WRONG_IDP_ENTITY_ID)


FAULT = FaultSpec(
    fault_id="wrong_issuer",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "SP's configured IdP entity ID doesn't match the real Issuer the response and "
        "assertion actually carry -- a stale realm identifier in the trust config."
    ),
    target_check_ids=["SAML-ISS-01", "SAML-ISS-02"],
    expected_states={"SAML-ISS-01": "failed", "SAML-ISS-02": "failed"},
    expected_root_cause="SAML-ISS-01",
    expected_disposition="review_required",
    difficulty="normal",
    ctx_transform=_apply,
)
