"""SAML-STATUS-01: the IdP's own verdict on the authentication attempt. A response can be
perfectly well-formed and signed while honestly reporting failure (wrong password, user
declined consent, IdP-side policy denial) -- that is not a verification bug, it's the IdP
telling the truth, and it should route differently than a malformed or tampered response."""

from __future__ import annotations

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import ParsedSamlResponse

STATUS_SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"


def check_status_success(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if parsed.status_code is None:
        return CheckResult(
            check_id="SAML-STATUS-01", assurance=Assurance.NOT_VERIFIED, observed=None,
            expected=STATUS_SUCCESS, reason="response has no Status/StatusCode",
        )
    if parsed.status_code == STATUS_SUCCESS:
        return CheckResult(
            check_id="SAML-STATUS-01", assurance=Assurance.VERIFIED, observed=parsed.status_code,
            expected=STATUS_SUCCESS, reason="IdP reported Success",
        )
    return CheckResult(
        check_id="SAML-STATUS-01", assurance=Assurance.FAILED, observed=parsed.status_code,
        expected=STATUS_SUCCESS,
        reason="IdP reported a non-Success status; this may be an honest IdP-side denial "
        "rather than a tampered or malformed response",
    )
