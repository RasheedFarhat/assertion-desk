"""SAML-NAMEID-01 / SAML-NAMEID-02 / SAML-SCM-01: who the assertion claims to be about,
and how it claims that binding was confirmed. Grouped together because all three read
from the same Subject element and none of them needs anything beyond the parsed response
itself -- no SP-supplied context required, unlike most of the other families."""

from __future__ import annotations

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import ParsedSamlResponse

# SAML 2.0 core §8.3 NameIDFormat identifiers actually issued by real IdPs in practice.
KNOWN_NAMEID_FORMATS = {
    "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified",
    "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
    "urn:oasis:names:tc:SAML:2.0:nameid-format:emailAddress",
    "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent",
    "urn:oasis:names:tc:SAML:2.0:nameid-format:transient",
    "urn:oasis:names:tc:SAML:1.1:nameid-format:X509SubjectName",
    "urn:oasis:names:tc:SAML:2.0:nameid-format:kerberos",
    "urn:oasis:names:tc:SAML:2.0:nameid-format:entity",
}

BEARER_METHOD = "urn:oasis:names:tc:SAML:2.0:cm:bearer"


def check_nameid_present(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-NAMEID-01", assurance=Assurance.NOT_VERIFIED, observed=None,
            expected="a non-empty NameID", reason="response contains no parsed Assertion",
        )
    nameid = parsed.assertions[0].nameid
    if not nameid:
        return CheckResult(
            check_id="SAML-NAMEID-01", assurance=Assurance.FAILED, observed=None,
            expected="a non-empty NameID", reason="Subject/NameID is missing or empty",
        )
    return CheckResult(
        check_id="SAML-NAMEID-01", assurance=Assurance.VERIFIED, observed=nameid,
        expected="a non-empty NameID", reason="NameID is present and non-empty",
    )


def check_nameid_format(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-NAMEID-02", assurance=Assurance.NOT_VERIFIED, observed=None,
            expected="a recognized NameID Format", reason="response contains no parsed Assertion",
        )
    fmt = parsed.assertions[0].nameid_format
    if fmt is None:
        return CheckResult(
            check_id="SAML-NAMEID-02", assurance=Assurance.NOT_VERIFIED, observed=None,
            expected="a recognized NameID Format", reason="NameID has no Format attribute",
        )
    if fmt in KNOWN_NAMEID_FORMATS:
        return CheckResult(
            check_id="SAML-NAMEID-02", assurance=Assurance.VERIFIED, observed=fmt,
            expected="one of the SAML 2.0 core §8.3 NameIDFormat identifiers",
            reason="NameID Format is a recognized SAML identifier",
        )
    return CheckResult(
        check_id="SAML-NAMEID-02", assurance=Assurance.REVIEW_REQUIRED, observed=fmt,
        expected="one of the SAML 2.0 core §8.3 NameIDFormat identifiers",
        reason="NameID Format is not a recognized standard identifier; may be a legitimate "
        "IdP-specific extension, worth a human glance rather than an automatic pass or fail",
    )


def check_subject_confirmation_method(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-SCM-01", assurance=Assurance.NOT_VERIFIED, observed=None,
            expected=BEARER_METHOD, reason="response contains no parsed Assertion",
        )
    method = parsed.assertions[0].subject_confirmation_method
    if method is None:
        return CheckResult(
            check_id="SAML-SCM-01", assurance=Assurance.NOT_VERIFIED, observed=None,
            expected=BEARER_METHOD, reason="SubjectConfirmation has no Method attribute",
        )
    if method == BEARER_METHOD:
        return CheckResult(
            check_id="SAML-SCM-01", assurance=Assurance.VERIFIED, observed=method,
            expected=BEARER_METHOD, reason="SubjectConfirmation Method is the expected bearer method",
        )
    return CheckResult(
        check_id="SAML-SCM-01", assurance=Assurance.FAILED, observed=method,
        expected=BEARER_METHOD, reason="SubjectConfirmation Method is not the bearer method the SP expects for web SSO",
    )
