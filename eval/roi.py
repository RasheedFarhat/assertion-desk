"""ROI calculator (plan section 24). Every input is visible and overridable via CLI
flags; nothing here is a hidden constant. Two inputs -- the human baseline time and
the human review time under the system -- have no default and are required, on
purpose: they can only come from the 20-case stopwatch study plan section 24 item 1
describes, and that study has not been run yet (see docs/HUMAN_BASELINE.md). A
calculator that could silently run with an invented number for the one figure this
whole project exists to measure honestly would be worse than no calculator, so it
refuses to run instead. This mirrors the project's own thesis at a smaller scale: no
step here is allowed to assert a number nothing has confirmed.

Run it:
    python3 -m eval.roi --baseline-minutes 45 --review-minutes 5

Every other flag has a defensible, cited default (see each flag's --help text) and
can be overridden. The output prints every input back before the result, so nothing
is hidden in a constant a reader has to go find in the source.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

# $86,050/yr US average base for a technical support engineer (Indeed, 2026,
# https://www.indeed.com/career/technical-support-engineer/salaries), times a 1.3
# fully-loaded multiplier (benefits, overhead), divided by 2080 (40hr/week x 52
# weeks), per plan section 2's cited cost basis. Shown as a derivation, not a bare
# constant, so the arithmetic is checkable without leaving this file.
_BASE_SALARY_USD = 86_050.0
_LOADING_MULTIPLIER = 1.3
_HOURS_PER_YEAR = 2080
DEFAULT_HOURLY_COST_USD = round(_BASE_SALARY_USD * _LOADING_MULTIPLIER / _HOURS_PER_YEAR, 2)

# Illustrative scale, not a claim about any real vendor. Change these to model an
# actual company if this calculator is ever pointed at one.
DEFAULT_TENANTS = 50
DEFAULT_TICKETS_PER_TENANT_PER_YEAR = 12.0

# Okta's Businesses at Work figure, cited in plan section 2 via Scalekit's SAML SSO
# guide: ">50% of enterprise SSO support tickets trace to IdP misconfiguration, not
# app code." Treated here explicitly as an assumption about the reader's own ticket
# mix, not a fact this project measured.
DEFAULT_MISCONFIG_SHARE = 0.5

# The one number this run actually measured: eval/runs/20260817T044253Z (the
# baseline docs/MEASUREMENTS.md publishes) spent $0/case because every call landed
# in fixtures/ or the local Ollama fallback tier, never a paid Gemini call. Plan
# section 16 separately estimates ~$0.004/case at Gemini's paid per-token rates if
# the fixture cache were cold and every call were live -- pass
# --system-cost-per-case 0.004 to model that scenario instead of this one.
DEFAULT_SYSTEM_COST_PER_CASE_USD = 0.0


@dataclass
class RoiInputs:
    baseline_minutes_per_case: float
    review_minutes_per_case: float
    tenants: int
    tickets_per_tenant_per_year: float
    misconfig_share: float
    hourly_cost_usd: float
    system_cost_per_case_usd: float


@dataclass
class RoiResult:
    annual_relevant_tickets: float
    minutes_saved_per_case: float
    hours_saved_per_year: float
    labor_savings_usd_per_year: float
    inference_cost_usd_per_year: float
    net_usd_per_year: float


def compute(i: RoiInputs) -> RoiResult:
    annual_relevant_tickets = i.tenants * i.tickets_per_tenant_per_year * i.misconfig_share
    minutes_saved_per_case = i.baseline_minutes_per_case - i.review_minutes_per_case
    hours_saved_per_year = annual_relevant_tickets * minutes_saved_per_case / 60.0
    labor_savings = hours_saved_per_year * i.hourly_cost_usd
    inference_cost = annual_relevant_tickets * i.system_cost_per_case_usd
    return RoiResult(
        annual_relevant_tickets=annual_relevant_tickets,
        minutes_saved_per_case=minutes_saved_per_case,
        hours_saved_per_year=hours_saved_per_year,
        labor_savings_usd_per_year=labor_savings,
        inference_cost_usd_per_year=inference_cost,
        net_usd_per_year=labor_savings - inference_cost,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Assertion Desk ROI calculator. Every input is a flag; nothing is hidden.",
    )
    p.add_argument(
        "--baseline-minutes",
        type=float,
        required=True,
        dest="baseline_minutes_per_case",
        help=(
            "Hands-on minutes for the manual workflow (plan section 14), timed against "
            "a real case, not estimated. Required, no default: see docs/HUMAN_BASELINE.md. "
            "This is the number the 20-case stopwatch study exists to produce."
        ),
    )
    p.add_argument(
        "--review-minutes",
        type=float,
        required=True,
        dest="review_minutes_per_case",
        help=(
            "Minutes for a human to read the case card and approve or override the "
            "system's output (plan section 24 item 2: 'the number that actually "
            "matters and the one most projects omit'). Required, no default, timed "
            "against the same cases as --baseline-minutes."
        ),
    )
    p.add_argument("--tenants", type=int, default=DEFAULT_TENANTS,
                    help=f"Enterprise SSO tenants. Illustrative default: {DEFAULT_TENANTS}.")
    p.add_argument("--tickets-per-tenant-year", type=float, default=DEFAULT_TICKETS_PER_TENANT_PER_YEAR,
                    dest="tickets_per_tenant_per_year",
                    help=f"SSO support tickets per tenant per year. Illustrative default: "
                         f"{DEFAULT_TICKETS_PER_TENANT_PER_YEAR}.")
    p.add_argument("--misconfig-share", type=float, default=DEFAULT_MISCONFIG_SHARE,
                    help=f"Share of tickets that are IdP misconfiguration, not app code. "
                         f"Default {DEFAULT_MISCONFIG_SHARE} cites Okta's Businesses at Work "
                         f"figure as an assumption, not a fact about your ticket mix.")
    p.add_argument("--hourly-cost", type=float, default=DEFAULT_HOURLY_COST_USD, dest="hourly_cost_usd",
                    help=f"Fully-loaded support engineer $/hr. Default ${DEFAULT_HOURLY_COST_USD} "
                         f"derived from ${_BASE_SALARY_USD:,.0f}/yr x {_LOADING_MULTIPLIER} / "
                         f"{_HOURS_PER_YEAR}hr (Indeed 2026; see module docstring).")
    p.add_argument("--system-cost-per-case", type=float, default=DEFAULT_SYSTEM_COST_PER_CASE_USD,
                    dest="system_cost_per_case_usd",
                    help=f"Model inference $/case. Default ${DEFAULT_SYSTEM_COST_PER_CASE_USD} is "
                         f"what eval/runs/20260817T044253Z actually spent (fixture + Ollama "
                         f"fallback, no Gemini call). Pass 0.004 to model the paid-Gemini estimate "
                         f"from plan section 16 instead.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    inputs = RoiInputs(**vars(args))
    result = compute(inputs)

    print("Inputs (every one is a flag; see --help for defaults and citations):")
    print(f"  baseline minutes/case (manual, stopwatch-timed) : {inputs.baseline_minutes_per_case}")
    print(f"  review minutes/case (human approves the system)  : {inputs.review_minutes_per_case}")
    print(f"  tenants                                           : {inputs.tenants}")
    print(f"  tickets/tenant/year                               : {inputs.tickets_per_tenant_per_year}")
    print(f"  IdP-misconfiguration share of tickets             : {inputs.misconfig_share}")
    print(f"  fully-loaded $/hr                                 : {inputs.hourly_cost_usd}")
    print(f"  system inference $/case                           : {inputs.system_cost_per_case_usd}")
    print()
    print("Result:")
    print(f"  relevant tickets/year   = tenants x tickets/tenant/year x misconfig_share")
    print(f"                          = {result.annual_relevant_tickets:,.1f}")
    print(f"  minutes saved/case      = baseline_minutes - review_minutes")
    print(f"                          = {result.minutes_saved_per_case:,.1f}")
    print(f"  hours saved/year        = relevant_tickets x minutes_saved / 60")
    print(f"                          = {result.hours_saved_per_year:,.1f}")
    print(f"  labor savings/year      = hours_saved x hourly_cost")
    print(f"                          = ${result.labor_savings_usd_per_year:,.2f}")
    print(f"  inference cost/year     = relevant_tickets x system_cost_per_case")
    print(f"                          = ${result.inference_cost_usd_per_year:,.2f}")
    print(f"  net/year                = labor_savings - inference_cost")
    print(f"                          = ${result.net_usd_per_year:,.2f}")
    if inputs.baseline_minutes_per_case <= 0 or inputs.review_minutes_per_case < 0:
        print()
        print(
            "WARNING: baseline/review minutes look like placeholders, not a real timed "
            "measurement. Do not publish this output until docs/HUMAN_BASELINE.md's study "
            "has actually been run."
        )


if __name__ == "__main__":
    main()
