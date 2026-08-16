"""truncated_response -- ARTIFACT_MUTATION, malformed stratum. Chops the real
SAMLResponse XML off at 60% of its length (mutations.truncate), simulating a network
truncation, a proxy body-size limit, or a copy-paste that lost the tail. The cut lands
mid-document (keep_fraction > 0.5), not near the start, so this models "most of a real
response, cut off" rather than an obviously-empty payload.

desk/verify/parsed.py's defused-XML pre-parse and lxml parse both raise
MalformedSamlResponse on this input well before any check in desk/verify/checks/ ever
runs -- there is no partial CheckResult set to name, because verification never starts.
expects_parse_failure names that honestly instead of forcing a fake target_check_id onto
a case where no check fired.

Correct system behavior: a clean, named intake-stage rejection (case -> intake_failed,
with the parse error recorded), never a crash, never a partial/inconsistent case state.
"""

from __future__ import annotations

from harness.faults import mutations
from harness.faults.base import FaultCategory, FaultSpec


def _apply(xml_bytes: bytes) -> bytes:
    return mutations.truncate(xml_bytes, keep_fraction=0.6)


FAULT = FaultSpec(
    fault_id="truncated_response",
    category=FaultCategory.ARTIFACT_MUTATION,
    description=(
        "SAMLResponse XML is truncated mid-document at 60% of its real length, "
        "simulating a network or proxy truncation. Fails to parse before any check runs."
    ),
    expects_parse_failure=True,
    expected_disposition="escalate",
    difficulty="malformed",
    xml_transform=_apply,
)
