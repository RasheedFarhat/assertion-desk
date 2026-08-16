"""SAML-AUD-01: the assertion must be scoped to this SP. Without an Audience check, an
assertion legitimately issued for a *different* SP under the same IdP could be replayed
here -- this is the check that prevents that cross-SP confusion."""

from __future__ import annotations

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import ParsedSamlResponse


def check_audience(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-AUD-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=ctx.sp_entity_id,
            reason="response contains no parsed Assertion",
        )
    audiences = parsed.assertions[0].audiences
    if not audiences:
        return CheckResult(
            check_id="SAML-AUD-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=ctx.sp_entity_id,
            reason="assertion has no AudienceRestriction/Audience",
        )
    if ctx.sp_entity_id in audiences:
        return CheckResult(
            check_id="SAML-AUD-01",
            assurance=Assurance.VERIFIED,
            observed=", ".join(audiences),
            expected=ctx.sp_entity_id,
            reason="this SP's entity ID is present in the assertion's Audience list",
        )
    return CheckResult(
        check_id="SAML-AUD-01",
        assurance=Assurance.FAILED,
        observed=", ".join(audiences),
        expected=ctx.sp_entity_id,
        reason="this SP's entity ID is not present in the assertion's Audience list",
    )
