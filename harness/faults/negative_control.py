"""negative_control -- LIVE_CAPTURE. A real failed login (wrong password) against the
same Keycloak realm, captured via harness/capture/playwright_login_negative_control.py.
The HAR on disk (harness/capture/fault_negative_control/login.har, 23 real entries) shows
Keycloak's own "Invalid username or password" rejection page, and the capture script
itself asserts zero POSTs of a SAMLResponse to the SP's /saml/acs endpoint anywhere in it
-- confirmed live 2026-08-16, see capture_result.json alongside the HAR.

This is the "a system that always finds a fault is worthless" case the plan calls for.
There is no SAMLResponse artifact at all, so there is nothing for desk/verify/checks/ to
run against -- not one check, not zero_verified, not a forced NOT_VERIFIED across the
board. The correct system behavior is recognizing the case never reached the federation
exchange in the first place (the user's own credentials were rejected by the IdP, which
is expected, correct IdP behavior, not a fault in the trust chain this system verifies)
and routing it as out of scope for SAML verification entirely, not as 20 absent checks
dressed up as findings.

target_check_ids is deliberately empty, same reasoning as expects_parse_failure faults
but a different mechanism: there, parsing raises before checks run; here, there is no
SAMLResponse artifact to attempt to parse in the first place. no_check_coverage_reason
is the correct escape hatch -- it names a real, structural absence, not a coverage gap
in the check catalogue.
"""

from __future__ import annotations

import os

from harness.faults.base import FaultCategory, FaultSpec, LiveArtifacts

_LIVE_DIR = os.path.join(os.path.dirname(__file__), "..", "capture", "fault_negative_control")

_NO_SAML_RESPONSE_REASON = (
    "No SAMLResponse artifact exists in this case (the IdP rejected the credential "
    "before producing one), so no check in desk/verify/checks/ has anything to run "
    "against. Correct behavior is a case state of out_of_scope / no_saml_response, "
    "never a fabricated check result."
)


def _load() -> LiveArtifacts:
    return LiveArtifacts(
        raw_saml_response=None,
        trusted_cert_pem=None,
        har_path=os.path.join(_LIVE_DIR, "login.har"),
        no_saml_response_reason=_NO_SAML_RESPONSE_REASON,
    )


FAULT = FaultSpec(
    fault_id="negative_control",
    category=FaultCategory.LIVE_CAPTURE,
    description=(
        "User typed the wrong password. Keycloak correctly rejects the login and no "
        "SAMLResponse is ever produced -- there is no federation trust-chain artifact "
        "for this system to verify, and it must say so rather than manufacture a finding."
    ),
    no_check_coverage_reason=_NO_SAML_RESPONSE_REASON,
    expected_disposition="review_required",
    difficulty="normal",
    live_dir="fault_negative_control",
    live_loader=_load,
)
