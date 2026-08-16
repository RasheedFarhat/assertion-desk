"""encrypted_assertion -- ARTIFACT_MUTATION. Inserts a structurally valid but
non-decryptable xenc:EncryptedData element as a child of the real <saml:Assertion>, via
mutations.insert_encrypted_data_into_assertion (see that function's docstring for why an
in-place insertion is the honest shape and an earlier whole-assertion-wrapping draft was
not, per the desk/verify/parsed.py descendant-search discovery).

SAML-ENC-01 correctly reports NOT_APPLICABLE, not FAILED -- this verifier does not
implement SAML assertion decryption, and an encrypted assertion is a stated capability
boundary, not a defect (see desk/verify/checks/encryption.py's own docstring). The point
of this case in the corpus is proving the system reports that boundary honestly rather
than silently skipping the check or, worse, reporting VERIFIED on content it never read.

Same cascading signature consequence as missing_nameid.py and
unsupported_nameid_format.py: the inserted element is new content inside <saml:Assertion>,
which both the Assertion's own signature and the enveloping Response-level signature
cover, so both SAML-SIG-01 and SAML-SIG-02 also fail. In a live deployment this exact
combination (encrypted content, invalid signature) is itself an honest signal something is
wrong with the artifact, not just with this verifier's capability -- worth noting in the
corpus label rather than treated as three unrelated findings.
"""

from __future__ import annotations

from harness.faults import mutations
from harness.faults.base import FaultCategory, FaultSpec


def _apply(xml_bytes: bytes) -> bytes:
    return mutations.insert_encrypted_data_into_assertion(xml_bytes)


FAULT = FaultSpec(
    fault_id="encrypted_assertion",
    category=FaultCategory.ARTIFACT_MUTATION,
    description=(
        "Assertion carries an EncryptedData element this verifier cannot decrypt -- a "
        "stated capability boundary, not a defect. Also invalidates both signatures, "
        "since the insertion is new content inside the signed Assertion."
    ),
    target_check_ids=["SAML-ENC-01", "SAML-SIG-01", "SAML-SIG-02"],
    expected_states={
        "SAML-ENC-01": "not_applicable",
        "SAML-SIG-01": "failed",
        "SAML-SIG-02": "failed",
    },
    expected_root_cause="SAML-ENC-01",
    expected_disposition="review_required",
    difficulty="normal",
    xml_transform=_apply,
)
