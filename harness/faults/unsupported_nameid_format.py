"""unsupported_nameid_format -- ARTIFACT_MUTATION. Rewrites the real NameID's Format
attribute to a value outside desk/verify/checks/subject.py's KNOWN_NAMEID_FORMATS set,
simulating an IdP-specific extension format (or a genuine misconfiguration) the SP has
never seen. SAML-NAMEID-02 deliberately reports REVIEW_REQUIRED rather than FAILED for
this -- the check's own reasoning is that an unrecognized format may be a legitimate
IdP-specific extension, worth a human glance rather than an automatic pass or fail.

Same signature side effect as missing_nameid.py, for the same reason (an attribute value
inside the signed Assertion changed): both SAML-SIG-01 and SAML-SIG-02 also fail. Recorded
honestly rather than treated as a confound.
"""

from __future__ import annotations

from harness.faults import mutations
from harness.faults.base import FaultCategory, FaultSpec

UNKNOWN_FORMAT = "urn:mycompany:custom:nameid-format:employee-id"


def _apply(xml_bytes: bytes) -> bytes:
    return mutations.rewrite_attribute(xml_bytes, "NameID", "Format", UNKNOWN_FORMAT, occurrence=0)


FAULT = FaultSpec(
    fault_id="unsupported_nameid_format",
    category=FaultCategory.ARTIFACT_MUTATION,
    description=(
        "NameID Format is a value outside the recognized SAML 2.0 core §8.3 set -- "
        "possibly a legitimate IdP-specific extension, correctly routed to human review "
        "rather than an automatic pass or fail. Also invalidates both signatures, the "
        "same real consequence documented in missing_nameid.py."
    ),
    target_check_ids=["SAML-NAMEID-02", "SAML-SIG-01", "SAML-SIG-02"],
    expected_states={
        "SAML-NAMEID-02": "review_required",
        "SAML-SIG-01": "failed",
        "SAML-SIG-02": "failed",
    },
    expected_root_cause="SAML-NAMEID-02",
    expected_disposition="review_required",
    difficulty="normal",
    xml_transform=_apply,
)
