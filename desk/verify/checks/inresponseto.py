"""SAML-INRESP-01 / SAML-INRESP-02: InResponseTo binds this response to a specific
authentication request the SP actually made. Without it (IdP-initiated flows legitimately
omit it), the SP has no proof the response is answering a request it issued, rather than
being replayed. Both checks require the SP to have supplied the expected request ID as
independent evidence (ctx.in_response_to_expected) -- there is nothing in the response
itself that could verify this against, since that's exactly what would be forged."""

from __future__ import annotations

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import ParsedSamlResponse


def _check(check_id: str, observed: str | None, ctx: VerificationContext, missing_reason: str) -> CheckResult:
    if ctx.in_response_to_expected is None:
        return CheckResult(
            check_id=check_id,
            assurance=Assurance.NOT_VERIFIED,
            observed=observed,
            expected=None,
            reason="no expected InResponseTo value was supplied by the SP (IdP-initiated "
            "flows legitimately have none; SP-initiated flows should)",
        )
    if observed is None:
        return CheckResult(
            check_id=check_id,
            assurance=Assurance.FAILED,
            observed=None,
            expected=ctx.in_response_to_expected,
            reason=missing_reason,
        )
    if observed == ctx.in_response_to_expected:
        return CheckResult(
            check_id=check_id,
            assurance=Assurance.VERIFIED,
            observed=observed,
            expected=ctx.in_response_to_expected,
            reason="InResponseTo matches the SP's own request ID",
        )
    return CheckResult(
        check_id=check_id,
        assurance=Assurance.FAILED,
        observed=observed,
        expected=ctx.in_response_to_expected,
        reason="InResponseTo does not match the SP's own request ID",
    )


def check_response_in_response_to(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    return _check("SAML-INRESP-01", parsed.in_response_to, ctx, "SP expected a specific request ID but the Response has no InResponseTo")


def check_scd_in_response_to(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-INRESP-02",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=ctx.in_response_to_expected,
            reason="response contains no parsed Assertion",
        )
    observed = parsed.assertions[0].scd_in_response_to
    return _check(
        "SAML-INRESP-02", observed, ctx,
        "SP expected a specific request ID but SubjectConfirmationData has no InResponseTo",
    )
