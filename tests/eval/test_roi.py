"""eval/roi.py: the ROI calculator's arithmetic, and the structural refusal that keeps
it from ever running with a fabricated human-baseline number (plan section 24).

The two things worth testing here are not the arithmetic in isolation (that is
one-line multiplication, low risk) but the two properties that make this calculator
different from a spreadsheet: the CLI hard-fails without a real timed input, and the
formulas compose the way the module's own printed derivation says they do.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from eval.roi import DEFAULT_HOURLY_COST_USD, RoiInputs, compute


def _inputs(**overrides) -> RoiInputs:
    base = dict(
        baseline_minutes_per_case=48.0,
        review_minutes_per_case=4.0,
        tenants=50,
        tickets_per_tenant_per_year=12.0,
        misconfig_share=0.5,
        hourly_cost_usd=DEFAULT_HOURLY_COST_USD,
        system_cost_per_case_usd=0.0,
    )
    base.update(overrides)
    return RoiInputs(**base)


def test_relevant_tickets_multiplies_the_three_volume_inputs():
    result = compute(_inputs(tenants=50, tickets_per_tenant_per_year=12.0, misconfig_share=0.5))
    assert result.annual_relevant_tickets == pytest.approx(300.0)


def test_minutes_saved_is_baseline_minus_review_not_baseline_alone():
    # The whole point of plan section 24 item 2: review time under the system is not
    # zero, and pretending it is would overstate the saving.
    result = compute(_inputs(baseline_minutes_per_case=48.0, review_minutes_per_case=4.0))
    assert result.minutes_saved_per_case == pytest.approx(44.0)


def test_zero_review_time_is_not_silently_assumed():
    with_review = compute(_inputs(review_minutes_per_case=4.0))
    without_review = compute(_inputs(review_minutes_per_case=0.0))
    assert without_review.hours_saved_per_year > with_review.hours_saved_per_year


def test_hours_and_labor_savings_derive_from_minutes_saved():
    result = compute(_inputs(baseline_minutes_per_case=48.0, review_minutes_per_case=4.0))
    expected_hours = 300.0 * 44.0 / 60.0
    assert result.hours_saved_per_year == pytest.approx(expected_hours)
    assert result.labor_savings_usd_per_year == pytest.approx(expected_hours * DEFAULT_HOURLY_COST_USD)


def test_inference_cost_is_netted_out_not_ignored():
    # An ROI model that ignores its own operating cost is not an ROI model (plan
    # section 24 item 6). Nonzero system cost must reduce net, never leave it untouched.
    free = compute(_inputs(system_cost_per_case_usd=0.0))
    paid = compute(_inputs(system_cost_per_case_usd=0.004))
    assert paid.inference_cost_usd_per_year > 0
    assert paid.net_usd_per_year < free.net_usd_per_year
    assert free.net_usd_per_year == pytest.approx(free.labor_savings_usd_per_year)


def test_negative_minutes_saved_is_reflected_honestly_not_floored_at_zero():
    # If review time under the system ever exceeded manual baseline time (a real
    # possible outcome for a case class this system handles badly), the calculator
    # must report the loss, not hide it behind a floor.
    result = compute(_inputs(baseline_minutes_per_case=5.0, review_minutes_per_case=10.0))
    assert result.minutes_saved_per_case == pytest.approx(-5.0)
    assert result.hours_saved_per_year < 0
    assert result.labor_savings_usd_per_year < 0


def test_default_hourly_cost_matches_its_own_documented_derivation():
    # $86,050/yr x 1.3 / 2080hr, per the module docstring and README's cited basis.
    assert DEFAULT_HOURLY_COST_USD == pytest.approx(86_050.0 * 1.3 / 2080, abs=0.01)


def test_cli_refuses_to_run_without_the_two_measured_inputs():
    # This is the structural guarantee, not just a UX nicety: there is no default for
    # --baseline-minutes or --review-minutes, so a bare invocation must fail loudly
    # rather than silently compute against an invented number.
    result = subprocess.run(
        [sys.executable, "-m", "eval.roi"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "--baseline-minutes" in result.stderr
    assert "--review-minutes" in result.stderr


def test_cli_runs_and_warns_on_placeholder_zero_values():
    result = subprocess.run(
        [sys.executable, "-m", "eval.roi", "--baseline-minutes", "0", "--review-minutes", "0"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "WARNING" in result.stdout
    assert "docs/HUMAN_BASELINE.md" in result.stdout


def test_cli_prints_every_input_back_before_the_result():
    # Plan section 24 item 5: "visible, editable inputs... every input on screen."
    result = subprocess.run(
        [sys.executable, "-m", "eval.roi", "--baseline-minutes", "48", "--review-minutes", "4",
         "--tenants", "75"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "48.0" in result.stdout
    assert "4.0" in result.stdout
    assert "75" in result.stdout
