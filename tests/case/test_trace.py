"""Hash-chain construction and tamper detection for desk/case/trace.py -- the same
"evidence tamper test rejected on content-hash mismatch" pattern already established as
a strong point in Control Plane's own evidence ledger, applied here to TraceEvent.
"""

from __future__ import annotations

import dataclasses

from desk.case.trace import GENESIS, append_event, verify_chain


def _chain(case_id: str, stages: list[str]) -> list:
    events = []
    prior = None
    for stage in stages:
        prior = append_event(case_id, stage, payload_sha256=f"sha-{stage}", prior=prior, at=f"2026-08-17T00:00:0{len(events)}+00:00")
        events.append(prior)
    return events


# --------------------------------------------------------------------------------- #
# append_event
# --------------------------------------------------------------------------------- #


def test_first_event_chains_from_genesis() -> None:
    e = append_event("case-1", "custody", "sha-custody", prior=None)
    assert e.seq == 0
    assert e.prev_hash == GENESIS
    assert e.case_id == "case-1"


def test_second_event_chains_from_the_first_events_hash() -> None:
    first = append_event("case-1", "custody", "sha-custody", prior=None)
    second = append_event("case-1", "verify", "sha-verify", prior=first)
    assert second.seq == 1
    assert second.prev_hash == first.hash


def test_hash_is_deterministic_given_identical_inputs() -> None:
    e1 = append_event("case-1", "custody", "sha-x", prior=None, at="2026-08-17T00:00:00+00:00")
    e2 = append_event("case-1", "custody", "sha-x", prior=None, at="2026-08-17T00:00:00+00:00")
    assert e1.hash == e2.hash


def test_hash_changes_if_any_field_changes() -> None:
    base = append_event("case-1", "custody", "sha-x", prior=None, at="2026-08-17T00:00:00+00:00")
    different_payload = append_event("case-1", "custody", "sha-y", prior=None, at="2026-08-17T00:00:00+00:00")
    different_stage = append_event("case-1", "verify", "sha-x", prior=None, at="2026-08-17T00:00:00+00:00")
    assert base.hash != different_payload.hash
    assert base.hash != different_stage.hash


def test_custody_record_sha256_can_be_reused_directly_as_a_payload_hash() -> None:
    # desk/custody/record.py's own docstring promises this: a later TraceEvent can use
    # CustodyRecord.sha256 directly as the payload hash for its custody stage, without
    # recomputing anything. append_event() places no format constraint on
    # payload_sha256 beyond "a string the caller already computed" -- so any sha256 hex
    # digest works as-is.
    custody_record_sha256 = "4f2b" + "0" * 60  # stand-in for a real CustodyRecord.sha256
    e = append_event("case-1", "custody", custody_record_sha256, prior=None)
    assert e.payload_sha256 == custody_record_sha256


# --------------------------------------------------------------------------------- #
# verify_chain
# --------------------------------------------------------------------------------- #


def test_empty_chain_is_vacuously_valid() -> None:
    result = verify_chain("case-1", [])
    assert result.valid is True


def test_intact_chain_is_valid() -> None:
    events = _chain("case-1", ["custody", "verify", "reason", "ground", "policy"])
    result = verify_chain("case-1", events)
    assert result.valid is True
    assert result.break_at_seq is None


def test_tampered_payload_hash_is_rejected() -> None:
    events = _chain("case-1", ["custody", "verify", "reason"])
    tampered = list(events)
    tampered[1] = dataclasses.replace(tampered[1], payload_sha256="sha-forged")
    result = verify_chain("case-1", tampered)
    assert result.valid is False
    assert result.break_at_seq == 1
    assert "hash mismatch" in result.reason


def test_broken_prev_hash_link_is_rejected() -> None:
    events = _chain("case-1", ["custody", "verify", "reason"])
    tampered = list(events)
    # Splice in a foreign event whose prev_hash doesn't chain from seq 0's real hash --
    # simulates a row from a different case's history being inserted by mistake.
    foreign = append_event("case-1", "verify", "sha-verify", prior=None)
    tampered[1] = dataclasses.replace(foreign, seq=1)
    result = verify_chain("case-1", tampered)
    assert result.valid is False
    assert result.break_at_seq == 1
    assert "prev_hash mismatch" in result.reason


def test_out_of_order_events_are_rejected() -> None:
    events = _chain("case-1", ["custody", "verify", "reason"])
    reordered = [events[0], events[2], events[1]]
    result = verify_chain("case-1", reordered)
    assert result.valid is False
    assert "out of sequence" in result.reason


def test_event_from_a_different_case_is_rejected() -> None:
    own = _chain("case-1", ["custody"])
    foreign = append_event("case-2", "verify", "sha-verify", prior=own[0])
    result = verify_chain("case-1", own + [foreign])
    assert result.valid is False
    assert result.break_at_seq == 1
    assert "belongs to case" in result.reason


def test_stage_relabeled_after_the_fact_is_rejected() -> None:
    # A relabel changes the event's own hash preimage without touching payload_sha256,
    # so this exercises a distinct path from test_tampered_payload_hash_is_rejected.
    events = _chain("case-1", ["custody", "verify"])
    tampered = list(events)
    tampered[0] = dataclasses.replace(tampered[0], stage="relabeled")
    result = verify_chain("case-1", tampered)
    assert result.valid is False
    assert result.break_at_seq == 0
