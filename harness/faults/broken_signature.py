"""broken_signature -- ARTIFACT_MUTATION. Corrupts the RESPONSE-level ds:SignatureValue
only (occurrence=0, the first SignatureValue in document order), not the Assertion's own.

Confirmed directly from the real captured XML's two ds:Reference elements: the
Response-level Signature's Reference URI points at the Response's own ID and its
enveloped-signature transform excludes only that same Signature block from the digest --
it does NOT exclude the nested Assertion-level Signature. Content strictly inside the
Response's own <ds:Signature>...</ds:Signature> (including its SignatureValue) is
therefore excluded from the Response's own digest calculation, so corrupting it changes
the raw signature bytes without touching any digest anywhere. The result is a clean,
single-check failure: SAML-SIG-01 fails on a genuine cryptographic signature mismatch,
while SAML-SIG-02 (the Assertion's own, independent signature) still verifies -- a
realistic shape for a mangled outer envelope (a lossy relay, a copy-paste error) that
left an already-signed inner Assertion untouched.

Contrast with missing_nameid.py / unsupported_nameid_format.py / encrypted_assertion.py,
which mutate content *inside* the Assertion and therefore break both signatures at once --
see those modules' docstrings for why that's the opposite, and also honest, outcome.
"""

from __future__ import annotations

from harness.faults import mutations
from harness.faults.base import FaultCategory, FaultSpec


def _apply(xml_bytes: bytes) -> bytes:
    return mutations.flip_signature_value(xml_bytes, occurrence=0)


FAULT = FaultSpec(
    fault_id="broken_signature",
    category=FaultCategory.ARTIFACT_MUTATION,
    description=(
        "Response-level signature is cryptographically corrupted (one flipped base64 "
        "character in its SignatureValue) while the Assertion's own independent "
        "signature is left intact -- an outer-envelope corruption, not an assertion "
        "forgery."
    ),
    target_check_ids=["SAML-SIG-01"],
    expected_states={"SAML-SIG-01": "failed"},
    expected_root_cause="SAML-SIG-01",
    expected_disposition="review_required",
    difficulty="normal",
    xml_transform=_apply,
)
