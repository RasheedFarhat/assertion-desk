"""record_decision() construction rules for desk/case/approval.py -- the DECISIONS enum
tying back to desk/case/state.py's actual HUMAN_REVIEW edges, the escalated-requires-a-
reason rule that feeds plan section 17's human-override-rate metric, and the optional
latency_seconds derivation from requested_at/responded_at."""

from __future__ import annotations

import pytest

from desk.case.approval import Approval, record_decision


def test_approved_decision_builds_an_approval() -> None:
    approval = record_decision(
        id="appr-1",
        case_id="case-1",
        approver="analyst@example.com",
        decision="approved",
        channel="gmail",
        responded_at="2026-08-17T00:05:00+00:00",
    )
    assert isinstance(approval, Approval)
    assert approval.decision == "approved"
    assert approval.override_reason is None
    assert approval.responded_at == "2026-08-17T00:05:00+00:00"


def test_unknown_decision_is_rejected() -> None:
    with pytest.raises(ValueError, match="approved.*escalated|escalated.*approved"):
        record_decision(id="appr-1", case_id="case-1", approver="a", decision="rejected", channel="gmail")


def test_escalated_decision_requires_an_override_reason() -> None:
    with pytest.raises(ValueError, match="override_reason"):
        record_decision(id="appr-1", case_id="case-1", approver="a", decision="escalated", channel="gmail")


def test_escalated_decision_with_a_reason_succeeds() -> None:
    approval = record_decision(
        id="appr-1",
        case_id="case-1",
        approver="a",
        decision="escalated",
        channel="gmail",
        override_reason="root cause cites SAML-SIG-01, not the more specific CERT-02 finding",
    )
    assert approval.decision == "escalated"
    assert approval.override_reason is not None


def test_approved_decision_may_also_carry_a_reason() -> None:
    # The requirement is one-directional: escalated needs a reason, approved doesn't
    # need to be reasonless.
    approval = record_decision(
        id="appr-1",
        case_id="case-1",
        approver="a",
        decision="approved",
        channel="gmail",
        override_reason="approved, but fix_steps wording was tightened before sending",
    )
    assert approval.override_reason is not None


def test_latency_seconds_is_none_without_requested_at() -> None:
    approval = record_decision(id="appr-1", case_id="case-1", approver="a", decision="approved", channel="gmail")
    assert approval.latency_seconds is None


def test_latency_seconds_is_computed_from_requested_at_and_responded_at() -> None:
    approval = record_decision(
        id="appr-1",
        case_id="case-1",
        approver="a",
        decision="approved",
        channel="gmail",
        requested_at="2026-08-17T00:00:00+00:00",
        responded_at="2026-08-17T00:05:30+00:00",
    )
    assert approval.latency_seconds == 330.0


def test_responded_at_defaults_to_now_when_omitted() -> None:
    approval = record_decision(id="appr-1", case_id="case-1", approver="a", decision="approved", channel="gmail")
    assert approval.responded_at  # non-empty; exact value is wall-clock, not asserted
