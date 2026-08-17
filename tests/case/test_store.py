"""Round-trip persistence tests for desk/case/store.py. All against SQLite in-memory --
see store.py's own docstring for why that is an intentional, named limit rather than an
oversight (Postgres compatibility is a design intent here, not a tested claim)."""

from __future__ import annotations

import pytest

from desk.case.state import Case, CaseState, new_case, transition
from desk.case.store import CaseStore, connect
from desk.case.trace import append_event, verify_chain


@pytest.fixture()
def store() -> CaseStore:
    return CaseStore(connect(":memory:"))


def test_insert_and_get_case_round_trips_every_field(store: CaseStore) -> None:
    case = new_case(
        id="case-1",
        correlation_id="corr-1",
        state=CaseState.VERIFYING,
        tenant_ref="tenant-acme",
        security_flags=("live_credential_quarantined",),
    )
    store.insert_case(case)
    fetched = store.get_case("case-1")
    assert fetched == case


def test_get_missing_case_returns_none(store: CaseStore) -> None:
    assert store.get_case("does-not-exist") is None


def test_update_case_persists_the_new_state_and_disposition(store: CaseStore) -> None:
    case = new_case(id="case-1", correlation_id="corr-1", state=CaseState.VERIFYING)
    store.insert_case(case)
    advanced = transition(case, CaseState.REASONED, disposition="review_required")
    store.update_case(advanced)
    fetched = store.get_case("case-1")
    assert fetched.state == CaseState.REASONED
    assert fetched.disposition == "review_required"


def test_update_missing_case_raises_key_error(store: CaseStore) -> None:
    case = new_case(id="ghost", correlation_id="corr-1", state=CaseState.VERIFYING)
    with pytest.raises(KeyError):
        store.update_case(case)


def test_list_cases_by_state_filters_correctly(store: CaseStore) -> None:
    store.insert_case(new_case(id="c1", correlation_id="corr-1", state=CaseState.VERIFYING))
    store.insert_case(new_case(id="c2", correlation_id="corr-2", state=CaseState.VERIFYING))
    store.insert_case(new_case(id="c3", correlation_id="corr-3", state=CaseState.CUSTODY_REVIEW))
    verifying = store.list_cases_by_state(CaseState.VERIFYING)
    assert {c.id for c in verifying} == {"c1", "c2"}
    custody = store.list_cases_by_state(CaseState.CUSTODY_REVIEW)
    assert {c.id for c in custody} == {"c3"}


def test_security_flags_round_trip_as_a_tuple_not_a_list(store: CaseStore) -> None:
    case = new_case(
        id="case-1",
        correlation_id="corr-1",
        state=CaseState.CUSTODY_REVIEW,
        security_flags=("live_credential_quarantined", "injection_suspected"),
    )
    store.insert_case(case)
    fetched = store.get_case("case-1")
    assert fetched.security_flags == ("live_credential_quarantined", "injection_suspected")
    assert isinstance(fetched.security_flags, tuple)


def test_tenant_ref_none_round_trips_as_none(store: CaseStore) -> None:
    case = new_case(id="case-1", correlation_id="corr-1", state=CaseState.VERIFYING)
    store.insert_case(case)
    assert store.get_case("case-1").tenant_ref is None


# --------------------------------------------------------------------------------- #
# Trace events
# --------------------------------------------------------------------------------- #


def test_append_and_get_trace_round_trips_in_seq_order(store: CaseStore) -> None:
    store.insert_case(new_case(id="case-1", correlation_id="corr-1", state=CaseState.VERIFYING))
    e0 = append_event("case-1", "custody", "sha-custody", prior=None)
    store.append_trace_event(e0)
    e1 = append_event("case-1", "verify", "sha-verify", prior=e0)
    store.append_trace_event(e1)
    e2 = append_event("case-1", "policy", "sha-policy", prior=e1)
    store.append_trace_event(e2)

    trace = store.get_trace("case-1")
    assert [e.stage for e in trace] == ["custody", "verify", "policy"]
    assert [e.seq for e in trace] == [0, 1, 2]


def test_get_trace_for_a_case_with_no_events_is_empty(store: CaseStore) -> None:
    assert store.get_trace("no-such-case") == []


def test_last_trace_event_returns_the_highest_seq(store: CaseStore) -> None:
    store.insert_case(new_case(id="case-1", correlation_id="corr-1", state=CaseState.VERIFYING))
    e0 = append_event("case-1", "custody", "sha-custody", prior=None)
    store.append_trace_event(e0)
    e1 = append_event("case-1", "verify", "sha-verify", prior=e0)
    store.append_trace_event(e1)
    assert store.last_trace_event("case-1") == e1


def test_last_trace_event_for_empty_case_is_none(store: CaseStore) -> None:
    assert store.last_trace_event("no-such-case") is None


def test_a_persisted_and_reloaded_trace_still_verifies(store: CaseStore) -> None:
    # The real integration point: build a chain, persist it, read it back from SQLite
    # (a different Python object identity, and an implicit ORDER BY on the way out),
    # and confirm verify_chain still accepts it.
    store.insert_case(new_case(id="case-1", correlation_id="corr-1", state=CaseState.VERIFYING))
    prior = None
    for stage in ["custody", "verify", "reason", "ground", "policy"]:
        prior = append_event("case-1", stage, f"sha-{stage}", prior=prior)
        store.append_trace_event(prior)

    reloaded = store.get_trace("case-1")
    result = verify_chain("case-1", reloaded)
    assert result.valid is True


def test_last_trace_event_can_seed_the_next_append(store: CaseStore) -> None:
    # This is the actual call shape a future orchestrator will use: fetch the last
    # persisted event, pass it as `prior` to the next append_event() call, without
    # needing to hold the whole chain in memory.
    store.insert_case(new_case(id="case-1", correlation_id="corr-1", state=CaseState.VERIFYING))
    store.append_trace_event(append_event("case-1", "custody", "sha-custody", prior=None))

    last = store.last_trace_event("case-1")
    next_event = append_event("case-1", "verify", "sha-verify", prior=last)
    store.append_trace_event(next_event)

    trace = store.get_trace("case-1")
    result = verify_chain("case-1", trace)
    assert result.valid is True
    assert len(trace) == 2
