"""SAML-SKEW-01 / SAML-COND-01 / SAML-COND-02: every timestamp-window check the response
carries. All three depend on the SP knowing "now" -- SKEW-01 needs the SP's own clock as
independent evidence (a clock a message claims about itself proves nothing); COND-01 and
COND-02 use ctx.now(), which defaults to wall-clock time but can be pinned for tests and
replay via ctx.evaluation_time."""

from __future__ import annotations

from datetime import datetime, timezone

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import ParsedSamlResponse


def _parse_saml_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def check_response_clock_skew(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if ctx.sp_clock is None:
        return CheckResult(
            check_id="SAML-SKEW-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=f"within {ctx.clock_skew_tolerance_seconds}s of the SP's clock",
            reason="no SP clock evidence supplied (a message's own claimed time proves nothing about skew)",
        )
    if parsed.issue_instant is None:
        return CheckResult(
            check_id="SAML-SKEW-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected=f"within {ctx.clock_skew_tolerance_seconds}s of the SP's clock",
            reason="response has no IssueInstant",
        )

    try:
        issued = _parse_saml_time(parsed.issue_instant)
    except ValueError as exc:
        return CheckResult(
            check_id="SAML-SKEW-01",
            assurance=Assurance.FAILED,
            observed=parsed.issue_instant,
            expected="a parseable ISO-8601 timestamp",
            reason=f"IssueInstant is not a parseable timestamp: {exc}",
        )

    sp_clock = ctx.sp_clock if ctx.sp_clock.tzinfo else ctx.sp_clock.replace(tzinfo=timezone.utc)
    delta = abs((issued - sp_clock).total_seconds())
    observed = f"{delta:.0f}s skew (IssueInstant={parsed.issue_instant}, sp_clock={sp_clock.isoformat()})"

    if delta <= ctx.clock_skew_tolerance_seconds:
        return CheckResult(
            check_id="SAML-SKEW-01",
            assurance=Assurance.VERIFIED,
            observed=observed,
            expected=f"<= {ctx.clock_skew_tolerance_seconds}s",
            reason="IssueInstant is within the configured clock skew tolerance of the SP's clock",
        )
    return CheckResult(
        check_id="SAML-SKEW-01",
        assurance=Assurance.FAILED,
        observed=observed,
        expected=f"<= {ctx.clock_skew_tolerance_seconds}s",
        reason="IssueInstant exceeds the configured clock skew tolerance of the SP's clock",
    )


def check_conditions_window(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-COND-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected="a valid Conditions window",
            reason="response contains no parsed Assertion",
        )
    a = parsed.assertions[0]
    if a.conditions_not_before is None or a.conditions_not_on_or_after is None:
        return CheckResult(
            check_id="SAML-COND-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected="Conditions with both NotBefore and NotOnOrAfter",
            reason="assertion Conditions is missing NotBefore and/or NotOnOrAfter",
        )
    try:
        not_before = _parse_saml_time(a.conditions_not_before)
        not_on_or_after = _parse_saml_time(a.conditions_not_on_or_after)
    except ValueError as exc:
        return CheckResult(
            check_id="SAML-COND-01",
            assurance=Assurance.FAILED,
            observed=f"{a.conditions_not_before} / {a.conditions_not_on_or_after}",
            expected="parseable ISO-8601 timestamps",
            reason=f"Conditions timestamps are not parseable: {exc}",
        )

    now = ctx.now()
    observed = f"now={now.isoformat()}, window=[{not_before.isoformat()}, {not_on_or_after.isoformat()})"

    if not_before <= now < not_on_or_after:
        return CheckResult(
            check_id="SAML-COND-01",
            assurance=Assurance.VERIFIED,
            observed=observed,
            expected="evaluation time inside the Conditions window",
            reason="evaluation time falls inside the assertion's Conditions validity window",
        )
    reason = "assertion has expired (past NotOnOrAfter)" if now >= not_on_or_after else "assertion is not yet valid (before NotBefore)"
    return CheckResult(
        check_id="SAML-COND-01",
        assurance=Assurance.FAILED,
        observed=observed,
        expected="evaluation time inside the Conditions window",
        reason=reason,
    )


def check_scd_not_expired(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-COND-02",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected="a valid SubjectConfirmationData NotOnOrAfter",
            reason="response contains no parsed Assertion",
        )
    not_on_or_after_raw = parsed.assertions[0].scd_not_on_or_after
    if not_on_or_after_raw is None:
        return CheckResult(
            check_id="SAML-COND-02",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected="SubjectConfirmationData with NotOnOrAfter",
            reason="SubjectConfirmationData has no NotOnOrAfter",
        )
    try:
        not_on_or_after = _parse_saml_time(not_on_or_after_raw)
    except ValueError as exc:
        return CheckResult(
            check_id="SAML-COND-02",
            assurance=Assurance.FAILED,
            observed=not_on_or_after_raw,
            expected="a parseable ISO-8601 timestamp",
            reason=f"SubjectConfirmationData NotOnOrAfter is not parseable: {exc}",
        )

    now = ctx.now()
    observed = f"now={now.isoformat()}, NotOnOrAfter={not_on_or_after.isoformat()}"
    if now < not_on_or_after:
        return CheckResult(
            check_id="SAML-COND-02",
            assurance=Assurance.VERIFIED,
            observed=observed,
            expected="evaluation time before NotOnOrAfter",
            reason="SubjectConfirmationData has not expired",
        )
    return CheckResult(
        check_id="SAML-COND-02",
        assurance=Assurance.FAILED,
        observed=observed,
        expected="evaluation time before NotOnOrAfter",
        reason="SubjectConfirmationData has expired",
    )
