"""cert_rotation -- LIVE_CAPTURE. Formalizes Phase 0's original de-risking fault: a
Keycloak realm signing key rotated (a second, higher-priority RSA key added via the
Admin API) without the SP's pinned metadata being refreshed to match. The pre-rotation
and post-rotation artifacts are both real captures, already on disk in
harness/capture/fault_cert_rotation/ from Phase 0 (docs/PHASE0_NOTES.md has the exact
recipe: rotate via Admin API, re-run harness/capture/playwright_login.py under the new
key). This module doesn't re-run that capture -- it wraps the artifacts Phase 0 already
produced into the same FaultSpec shape every other fault in this catalogue uses, so the
corpus generator has one interface regardless of how each case's evidence was produced.

Self-test note (Phase 3, run against the live verifier before freezing): with the stale
cert pinned, SAML-SIG-01 and SAML-SIG-02 also fail, not only SAML-CERT-02 -- the response
is genuinely signed with the new key, so signature verification against the old pinned
cert fails for real, not just the separate thumbprint-comparison check. Named here rather
than left as an undocumented side effect, matching cert_expired.py's own honesty
convention for cascading failures. SAML-CERT-02 stays the expected root cause: it is the
specific, actionable diagnosis ("your pinned cert is stale"), and the two signature
failures are the same underlying mechanism restated, not independent findings.
"""

from __future__ import annotations

import os

from harness.faults.base import FaultCategory, FaultSpec, LiveArtifacts

_LIVE_DIR = os.path.join(os.path.dirname(__file__), "..", "capture", "fault_cert_rotation")


def _load() -> LiveArtifacts:
    # The case is deliberately post_rotation_saml_response + stale_trusted_cert -- the
    # new key signed the response, but the SP's pinned copy is still the old one.
    # pre_rotation_saml_response.xml and rotated_trusted_cert.txt live in the same
    # directory only as the "before" comparison Phase 0 used to prove the fault was
    # real; neither belongs in this case's artifacts.
    with open(os.path.join(_LIVE_DIR, "post_rotation_saml_response.xml"), "rb") as f:
        raw = f.read()
    with open(os.path.join(_LIVE_DIR, "stale_trusted_cert.txt")) as f:
        stale_cert = f.read()
    return LiveArtifacts(raw_saml_response=raw, trusted_cert_pem=stale_cert, har_path=None)


FAULT = FaultSpec(
    fault_id="cert_rotation",
    category=FaultCategory.LIVE_CAPTURE,
    description=(
        "IdP signing key rotated (a second RSA key added at higher priority in Keycloak) "
        "without the SP's pinned trusted certificate being refreshed to match -- the "
        "single most common real-world SAML-CERT-02 cause. Also fails signature "
        "verification outright (see module docstring), not only the thumbprint check."
    ),
    target_check_ids=["SAML-CERT-02", "SAML-SIG-01", "SAML-SIG-02"],
    expected_states={"SAML-CERT-02": "failed", "SAML-SIG-01": "failed", "SAML-SIG-02": "failed"},
    expected_root_cause="SAML-CERT-02",
    expected_disposition="review_required",
    difficulty="normal",
    live_dir="fault_cert_rotation",
    live_loader=_load,
)
