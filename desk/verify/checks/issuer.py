"""SAML-ISS-01 / SAML-ISS-02: the Response's and the Assertion's Issuer must both be the
IdP entity ID the SP actually configured for this tenant -- not merely "an issuer",
which is the difference between authenticating against the right IdP and any IdP that
can produce a validly-signed assertion for a *different* trust relationship."""

from __future__ import annotations

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import ParsedSamlResponse


def check_response_issuer(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if parsed.issuer is None:
        return CheckResult(
            check_id="SAML-ISS-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=ctx.idp_entity_id,
            reason="response has no Issuer element",
        )
    if parsed.issuer == ctx.idp_entity_id:
        return CheckResult(
            check_id="SAML-ISS-01",
            assurance=Assurance.VERIFIED,
            observed=parsed.issuer,
            expected=ctx.idp_entity_id,
            reason="Response Issuer matches the configured IdP entity ID",
        )
    return CheckResult(
        check_id="SAML-ISS-01",
        assurance=Assurance.FAILED,
        observed=parsed.issuer,
        expected=ctx.idp_entity_id,
        reason="Response Issuer does not match the configured IdP entity ID",
    )


def check_assertion_issuer(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-ISS-02",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=ctx.idp_entity_id,
            reason="response contains no parsed Assertion",
        )
    issuer = parsed.assertions[0].issuer
    if issuer is None:
        return CheckResult(
            check_id="SAML-ISS-02",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=ctx.idp_entity_id,
            reason="assertion has no Issuer element",
        )
    if issuer == ctx.idp_entity_id:
        return CheckResult(
            check_id="SAML-ISS-02",
            assurance=Assurance.VERIFIED,
            observed=issuer,
            expected=ctx.idp_entity_id,
            reason="Assertion Issuer matches the configured IdP entity ID",
        )
    return CheckResult(
        check_id="SAML-ISS-02",
        assurance=Assurance.FAILED,
        observed=issuer,
        expected=ctx.idp_entity_id,
        reason="Assertion Issuer does not match the configured IdP entity ID",
    )
