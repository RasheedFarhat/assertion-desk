"""SAML-SIG-01 / SAML-SIG-02: XML-DSig signature verification, adapted from
desk/verify/xmldsig.py (Phase 0) into the six-state assurance taxonomy.

Deliberately does not skip verification when ctx.trusted_cert_pem is absent by falling
back to trusting whatever certificate is embedded in the response. That would mean an
attacker who can produce a self-signed cert and a matching signature gets a VERIFIED
result -- exactly the "absence of evidence yields verified" failure the taxonomy exists
to forbid. No pinned cert means NOT_VERIFIED, full stop, regardless of what xmldsig.py's
raw signature math says.
"""

from __future__ import annotations

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import ParsedSamlResponse
from desk.verify.xmldsig import verify_saml_response


def _check_element_signature(check_id: str, kind: str, parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if ctx.trusted_cert_pem is None:
        return CheckResult(
            check_id=check_id,
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected="a pinned IdP signing certificate to verify against",
            reason="no trusted_cert_pem supplied; refusing to trust an embedded certificate blindly",
        )

    report = verify_saml_response(parsed.raw_bytes, trusted_cert_pem=ctx.trusted_cert_pem)
    match = next((c for c in report.checks if c.element == kind), None)

    if match is None:
        return CheckResult(
            check_id=check_id,
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=f"a ds:Signature element on the {kind}",
            reason=f"no ds:Signature found on the {kind} element",
        )

    if match.verified:
        return CheckResult(
            check_id=check_id,
            assurance=Assurance.VERIFIED,
            observed=match.reason,
            expected="signature valid against the pinned IdP certificate",
            reason=match.reason,
            evidence_ref=match.element_id,
        )

    return CheckResult(
        check_id=check_id,
        assurance=Assurance.FAILED,
        observed=match.reason,
        expected="signature valid against the pinned IdP certificate",
        reason=match.reason,
        evidence_ref=match.element_id,
    )


def check_response_signature(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    return _check_element_signature("SAML-SIG-01", "Response", parsed, ctx)


def check_assertion_signature(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-SIG-02",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected="at least one saml:Assertion",
            reason="response contains no parsed Assertion",
        )
    return _check_element_signature("SAML-SIG-02", "Assertion", parsed, ctx)
