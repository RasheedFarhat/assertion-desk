"""double_encoded_response -- ARTIFACT_MUTATION, malformed stratum. Base64-encodes the
real, already-decoded SAMLResponse XML a second time (mutations.double_base64_encode),
simulating an SP-side bug where the form field was decoded once by a proxy or framework
and once by the application, so the bytes that ultimately reach the XML parser are base64
*text*, not XML.

Same downstream consequence as truncated_response.py and for the same structural reason:
desk/verify/parsed.py's defused-XML pre-parse rejects base64 text as not-well-formed XML
immediately, before any check runs. expects_parse_failure=True, no target_check_ids --
there is no partial CheckResult set here either.

Distinguishing this from truncated_response.py in the corpus matters even though both
land on the same expects_parse_failure outcome: the failure signatures differ (a
truncation error vs a not-well-formed-XML-from-the-first-byte error), and a system that
collapses both into an identical generic "malformed" bucket without a distinguishable
reason string would be less useful to a human than one that names which malformation
occurred.
"""

from __future__ import annotations

from harness.faults import mutations
from harness.faults.base import FaultCategory, FaultSpec


def _apply(xml_bytes: bytes) -> bytes:
    return mutations.double_base64_encode(xml_bytes)


FAULT = FaultSpec(
    fault_id="double_encoded_response",
    category=FaultCategory.ARTIFACT_MUTATION,
    description=(
        "SAMLResponse XML has been base64-encoded a second time, simulating a "
        "double-decode bug on the SP side. The parser sees base64 text where it expects "
        "XML and fails before any check runs."
    ),
    expects_parse_failure=True,
    expected_disposition="escalate",
    difficulty="malformed",
    xml_transform=_apply,
)
