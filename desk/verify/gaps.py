"""Turns a VerificationRun's NOT_VERIFIED checks into a gap list: what's missing, and
which single artifact would resolve it. This is deterministic, closed-enum output --
Phase 4's Job B (the missing-evidence-request writer) is only allowed to request
artifacts from this same enum, so it cannot invent a request for something the system
doesn't actually need.

Only NOT_VERIFIED checks produce gaps. FAILED is not a gap -- it's an answer (something
is concretely wrong); REVIEW_REQUIRED and NOT_APPLICABLE aren't gaps either. A gap is
specifically "we cannot tell, because we don't have the evidence."
"""

from __future__ import annotations

from dataclasses import dataclass

from desk.verify.assurance import Assurance
from desk.verify.verifier import VerificationRun

# The closed set of artifacts a customer or their SP-side config can supply. Job B (the
# AI's evidence-request writer, Phase 4) may only request from this enum.
REQUESTED_ARTIFACT_HAR = "har"
REQUESTED_ARTIFACT_SAML_RESPONSE = "saml_response"
REQUESTED_ARTIFACT_IDP_METADATA = "idp_metadata"
REQUESTED_ARTIFACT_SP_CLOCK = "sp_clock"
REQUESTED_ARTIFACT_SP_REQUEST_LOG = "sp_request_log"

REQUESTED_ARTIFACTS = {
    REQUESTED_ARTIFACT_HAR,
    REQUESTED_ARTIFACT_SAML_RESPONSE,
    REQUESTED_ARTIFACT_IDP_METADATA,
    REQUESTED_ARTIFACT_SP_CLOCK,
    REQUESTED_ARTIFACT_SP_REQUEST_LOG,
}

# Which artifact resolves which check's NOT_VERIFIED gap. Checks not listed here default
# to requesting the raw SAML response, which is the common cause when the gap traces back
# to "there was no parsed Assertion at all."
_CHECK_TO_ARTIFACT = {
    "SAML-SIG-01": REQUESTED_ARTIFACT_IDP_METADATA,
    "SAML-SIG-02": REQUESTED_ARTIFACT_IDP_METADATA,
    "SAML-CERT-01": REQUESTED_ARTIFACT_IDP_METADATA,
    "SAML-CERT-02": REQUESTED_ARTIFACT_IDP_METADATA,
    "SAML-SKEW-01": REQUESTED_ARTIFACT_SP_CLOCK,
    "SAML-INRESP-01": REQUESTED_ARTIFACT_SP_REQUEST_LOG,
    "SAML-INRESP-02": REQUESTED_ARTIFACT_SP_REQUEST_LOG,
}


@dataclass
class Gap:
    check_id: str
    reason: str
    requested_artifact: str


def compute_gaps(run: VerificationRun) -> list[Gap]:
    gaps = []
    for r in run.results:
        if r.assurance != Assurance.NOT_VERIFIED:
            continue
        artifact = _CHECK_TO_ARTIFACT.get(r.check_id, REQUESTED_ARTIFACT_SAML_RESPONSE)
        assert artifact in REQUESTED_ARTIFACTS  # closed enum; a typo above must fail loudly, not silently drift
        gaps.append(Gap(check_id=r.check_id, reason=r.reason, requested_artifact=artifact))
    return gaps
