"""Exhaustive transition-graph coverage for desk/case/state.py (Control Plane's "the
table is small enough to test exhaustively" pattern, already used by
tests/policy/test_rules.py for the disposition rule table). Every one of CaseState's 10
states, times every other state, is checked against desk.case.state.CASE_TRANSITIONS --
so this test fails the moment code and graph drift apart, not just the moment a specific
named edge breaks.
"""

from __future__ import annotations

import itertools

import pytest

from desk.case.state import (
    CASE_TRANSITIONS,
    INITIAL_STATES,
    TERMINAL_STATES,
    Case,
    CaseState,
    IllegalTransition,
    is_terminal,
    new_case,
    transition,
)

ALL_STATES = list(CaseState)


def _case_in(state: CaseState) -> Case:
    if state in INITIAL_STATES:
        return new_case(id="c1", correlation_id="corr-1", state=state)
    # Not every state is directly constructible via new_case (see state.py's docstring
    # for why only three states are legal initial states) -- build the rest directly so
    # every state can still be exercised as a *source* of a transition attempt.
    return Case(
        id="c1",
        correlation_id="corr-1",
        tenant_ref=None,
        state=state,
        disposition=None,
        created_at="2026-08-17T00:00:00+00:00",
        updated_at="2026-08-17T00:00:00+00:00",
    )


@pytest.mark.parametrize("frm,to", list(itertools.product(ALL_STATES, ALL_STATES)))
def test_transition_matches_the_graph_exactly(frm: CaseState, to: CaseState) -> None:
    case = _case_in(frm)
    legal = to in CASE_TRANSITIONS[frm]
    if legal:
        result = transition(case, to)
        assert result.state == to
    else:
        with pytest.raises(IllegalTransition):
            transition(case, to)


def test_every_state_has_an_explicit_table_entry() -> None:
    assert set(CASE_TRANSITIONS) == set(CaseState)


def test_terminal_states_have_no_outgoing_edges() -> None:
    for state in TERMINAL_STATES:
        assert CASE_TRANSITIONS[state] == frozenset()
        assert is_terminal(state)


def test_non_terminal_states_have_at_least_one_outgoing_edge() -> None:
    for state in set(CaseState) - TERMINAL_STATES:
        assert CASE_TRANSITIONS[state], f"{state} is not terminal but has no outgoing edges"
        assert not is_terminal(state)


def test_terminal_states_are_exactly_the_documented_four() -> None:
    assert TERMINAL_STATES == {
        CaseState.INTAKE_FAILED,
        CaseState.PUBLISHED,
        CaseState.ESCALATED,
        CaseState.BLOCKED,
    }


def test_initial_states_are_exactly_the_documented_three() -> None:
    assert INITIAL_STATES == {
        CaseState.INTAKE_FAILED,
        CaseState.CUSTODY_REVIEW,
        CaseState.VERIFYING,
    }


# --------------------------------------------------------------------------------- #
# new_case
# --------------------------------------------------------------------------------- #


@pytest.mark.parametrize("state", sorted(INITIAL_STATES, key=lambda s: s.value))
def test_new_case_accepts_every_initial_state(state: CaseState) -> None:
    case = new_case(id="c1", correlation_id="corr-1", state=state)
    assert case.state == state
    assert case.disposition is None
    assert case.created_at == case.updated_at


@pytest.mark.parametrize("state", sorted(set(CaseState) - INITIAL_STATES, key=lambda s: s.value))
def test_new_case_rejects_every_non_initial_state(state: CaseState) -> None:
    with pytest.raises(IllegalTransition):
        new_case(id="c1", correlation_id="corr-1", state=state)


def test_new_case_carries_tenant_ref_and_security_flags() -> None:
    case = new_case(
        id="c1",
        correlation_id="corr-1",
        state=CaseState.CUSTODY_REVIEW,
        tenant_ref="tenant-acme",
        security_flags=("live_credential_quarantined",),
    )
    assert case.tenant_ref == "tenant-acme"
    assert case.security_flags == ("live_credential_quarantined",)


# --------------------------------------------------------------------------------- #
# transition() field behavior
# --------------------------------------------------------------------------------- #


def test_transition_sets_disposition_when_given() -> None:
    case = new_case(id="c1", correlation_id="corr-1", state=CaseState.VERIFYING)
    result = transition(case, CaseState.AWAITING_EVIDENCE, disposition="awaiting_evidence")
    assert result.disposition == "awaiting_evidence"
    assert result.state == CaseState.AWAITING_EVIDENCE


def test_transition_preserves_disposition_when_not_given() -> None:
    case = new_case(id="c1", correlation_id="corr-1", state=CaseState.VERIFYING)
    reasoned_bound = transition(case, CaseState.REASONED, disposition="review_required")
    human_review = transition(reasoned_bound, CaseState.HUMAN_REVIEW)
    assert human_review.disposition == "review_required"


def test_transition_advances_updated_at_but_not_created_at() -> None:
    case = new_case(id="c1", correlation_id="corr-1", state=CaseState.VERIFYING, at="2026-08-17T00:00:00+00:00")
    result = transition(case, CaseState.HUMAN_REVIEW, at="2026-08-17T01:00:00+00:00")
    assert result.created_at == "2026-08-17T00:00:00+00:00"
    assert result.updated_at == "2026-08-17T01:00:00+00:00"


def test_transition_returns_a_new_object_and_does_not_mutate_the_original() -> None:
    case = new_case(id="c1", correlation_id="corr-1", state=CaseState.VERIFYING)
    result = transition(case, CaseState.HUMAN_REVIEW)
    assert case.state == CaseState.VERIFYING
    assert result.state == CaseState.HUMAN_REVIEW
    assert result is not case


def test_illegal_transition_message_names_both_states_and_the_legal_set() -> None:
    case = new_case(id="c1", correlation_id="corr-1", state=CaseState.VERIFYING)
    with pytest.raises(IllegalTransition, match="verifying.*published"):
        transition(case, CaseState.PUBLISHED)


def test_illegal_transition_from_a_terminal_state_names_it_as_terminal() -> None:
    case = _case_in(CaseState.PUBLISHED)
    with pytest.raises(IllegalTransition, match="terminal state"):
        transition(case, CaseState.VERIFYING)


# --------------------------------------------------------------------------------- #
# The plan-derived, human-readable path a normal case actually takes
# --------------------------------------------------------------------------------- #


def test_full_happy_path_review_required_case() -> None:
    case = new_case(id="c1", correlation_id="corr-1", state=CaseState.VERIFYING)
    case = transition(case, CaseState.REASONED, disposition="review_required")
    case = transition(case, CaseState.HUMAN_REVIEW)
    case = transition(case, CaseState.APPROVED)
    case = transition(case, CaseState.PUBLISHED)
    assert case.state == CaseState.PUBLISHED
    assert case.disposition == "review_required"
    assert is_terminal(case.state)


def test_full_path_awaiting_evidence_then_reverified() -> None:
    case = new_case(id="c1", correlation_id="corr-1", state=CaseState.VERIFYING)
    case = transition(case, CaseState.AWAITING_EVIDENCE, disposition="awaiting_evidence")
    case = transition(case, CaseState.VERIFYING)
    case = transition(case, CaseState.HUMAN_REVIEW, disposition="review_required")
    case = transition(case, CaseState.ESCALATED)
    assert case.state == CaseState.ESCALATED
    assert is_terminal(case.state)


def test_custody_review_cleared_then_blocked_paths() -> None:
    cleared = new_case(id="c1", correlation_id="corr-1", state=CaseState.CUSTODY_REVIEW)
    cleared = transition(cleared, CaseState.VERIFYING)
    assert cleared.state == CaseState.VERIFYING

    blocked = new_case(id="c2", correlation_id="corr-2", state=CaseState.CUSTODY_REVIEW)
    blocked = transition(blocked, CaseState.BLOCKED)
    assert blocked.state == CaseState.BLOCKED
    assert is_terminal(blocked.state)
