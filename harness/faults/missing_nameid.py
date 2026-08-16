"""missing_nameid -- ARTIFACT_MUTATION. Blanks the real Assertion's Subject/NameID text,
leaving the element itself in place, so parsing still succeeds and SAML-NAMEID-01 reports
a genuine FAILED (empty NameID) rather than a structural parse error it was never meant
to catch.

Honest, verified side effect, not a bug: NameID lives inside <saml:Assertion>, which the
Response-level Signature's digest covers as well as the Assertion's own (see
broken_signature.py's docstring for the ds:Reference evidence). Mutating it invalidates
BOTH signatures at once. This is a genuinely good property to demonstrate rather than
paper over -- in a real deployment, tampering with a signed assertion's Subject is
self-revealing exactly because it also breaks the signature covering it. The structural
check (SAML-NAMEID-01) is what tells a human *what* is wrong; the signature checks are
what prove it was tampered with rather than merely malformed.
"""

from __future__ import annotations

from harness.faults import mutations
from harness.faults.base import FaultCategory, FaultSpec


def _apply(xml_bytes: bytes) -> bytes:
    return mutations.strip_element_text(xml_bytes, "NameID", occurrence=0)


FAULT = FaultSpec(
    fault_id="missing_nameid",
    category=FaultCategory.ARTIFACT_MUTATION,
    description=(
        "Subject/NameID is present but empty. As a real consequence of tampering with "
        "signed content, both the Assertion's own signature and the Response-level "
        "signature covering it also fail to verify."
    ),
    target_check_ids=["SAML-NAMEID-01", "SAML-SIG-01", "SAML-SIG-02"],
    expected_states={
        "SAML-NAMEID-01": "failed",
        "SAML-SIG-01": "failed",
        "SAML-SIG-02": "failed",
    },
    expected_root_cause="SAML-NAMEID-01",
    expected_disposition="review_required",
    difficulty="normal",
    xml_transform=_apply,
)
