"""SAML-DEST-01 / SAML-RECIP-01: both are exact-match checks of a URL carried in the
response against the SP's configured ACS URL, so they share one module rather than being
split into two near-identical files. They are still distinct check IDs because they
guard different things: Destination (on the Response) is where the IdP intended the
message to be delivered; Recipient (on SubjectConfirmationData) is where the assertion
authorizes itself to be presented. A mismatch on either is a real, separately named
class of misconfiguration (e.g. an ACS URL with a trailing slash added on one side and
not the other) and support engineers debug them as different symptoms."""

from __future__ import annotations

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import ParsedSamlResponse


def check_destination(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if parsed.destination is None:
        return CheckResult(
            check_id="SAML-DEST-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=ctx.acs_url,
            reason="response has no Destination attribute",
        )
    if parsed.destination == ctx.acs_url:
        return CheckResult(
            check_id="SAML-DEST-01",
            assurance=Assurance.VERIFIED,
            observed=parsed.destination,
            expected=ctx.acs_url,
            reason="Response Destination matches the configured ACS URL exactly",
        )
    return CheckResult(
        check_id="SAML-DEST-01",
        assurance=Assurance.FAILED,
        observed=parsed.destination,
        expected=ctx.acs_url,
        reason="Response Destination does not exactly match the configured ACS URL",
    )


def check_recipient(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-RECIP-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=ctx.acs_url,
            reason="response contains no parsed Assertion",
        )
    recipient = parsed.assertions[0].scd_recipient
    if recipient is None:
        return CheckResult(
            check_id="SAML-RECIP-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=ctx.acs_url,
            reason="SubjectConfirmationData has no Recipient attribute",
        )
    if recipient == ctx.acs_url:
        return CheckResult(
            check_id="SAML-RECIP-01",
            assurance=Assurance.VERIFIED,
            observed=recipient,
            expected=ctx.acs_url,
            reason="SubjectConfirmationData Recipient matches the configured ACS URL exactly",
        )
    return CheckResult(
        check_id="SAML-RECIP-01",
        assurance=Assurance.FAILED,
        observed=recipient,
        expected=ctx.acs_url,
        reason="SubjectConfirmationData Recipient does not exactly match the configured ACS URL",
    )
