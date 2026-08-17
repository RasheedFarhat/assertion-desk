"""Hash-linked audit trace for a Case (plan section 19's TraceEvent table, section 22's
"the hash-linked trace, verifiable end to end" case-card panel). Mirrors Control Plane's
evidence ledger exactly: prev_hash chained from a fixed GENESIS sentinel, each event's
own hash computed over a canonical encoding of {case_id, seq, stage, payload_sha256,
prev_hash, at}, so a later event can never be forged to point at a different history
without every subsequent hash changing too.

This module stores only a payload_sha256 per event, never the payload itself -- the
CustodyRecord / CheckResult list / ModelInvocation / PolicyDecision that produced each
hash lives wherever desk/custody, desk/verify, desk/reason, or desk/policy already
persists it. desk/custody/record.py's own docstring already names this relationship:
"a later TraceEvent can use this record's sha256 directly as the payload hash for its
custody stage, without recomputing anything." trace.py's job is only the chain, not the
evidence -- append_event() takes a payload_sha256 the caller already computed.

A broken chain is a real, expected-to-be-detectable outcome (tampering, a bug in the
persistence layer, a partial write), not a programming error -- verify_chain() returns a
ChainVerification, it never raises. That matches this codebase's established pattern
(desk/ground's GroundingResult, desk/policy's PolicyDecision): a bad outcome is a data
point to report, not a stack trace. Contrast this deliberately with state.py's
IllegalTransition, which does raise -- an illegal state transition is always a caller
bug, but a broken hash chain can be caused by something outside the calling code's
control (a corrupted row, a compromised store), so the caller needs the full detail back
as a value to act on, not just an exception to catch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

GENESIS = "GENESIS"


@dataclass(frozen=True)
class TraceEvent:
    case_id: str
    seq: int
    stage: str
    payload_sha256: str
    prev_hash: str
    at: str
    hash: str


def _event_hash(case_id: str, seq: int, stage: str, payload_sha256: str, prev_hash: str, at: str) -> str:
    # sorted_keys + no separators, same canonical-encoding convention as
    # desk/custody/record.py's _canonical_json -- order-independent, whitespace-free,
    # so two callers who build the same fields in a different order still hash identically.
    canonical = json.dumps(
        {
            "case_id": case_id,
            "seq": seq,
            "stage": stage,
            "payload_sha256": payload_sha256,
            "prev_hash": prev_hash,
            "at": at,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def append_event(
    case_id: str,
    stage: str,
    payload_sha256: str,
    prior: TraceEvent | None,
    at: str | None = None,
) -> TraceEvent:
    """Builds the next TraceEvent in a case's chain. `prior` is the last event already
    appended for this case (None only for the very first event in a case's history, in
    which case prev_hash is GENESIS and seq is 0). Callers are responsible for
    persisting the returned event via desk.case.store -- this function computes, it does
    not store, matching desk/custody/record.py's build_custody_record() convention of a
    single pure entry point taking already-computed inputs."""
    seq = 0 if prior is None else prior.seq + 1
    prev_hash = GENESIS if prior is None else prior.hash
    at = at or datetime.now(timezone.utc).isoformat()
    h = _event_hash(case_id, seq, stage, payload_sha256, prev_hash, at)
    return TraceEvent(
        case_id=case_id,
        seq=seq,
        stage=stage,
        payload_sha256=payload_sha256,
        prev_hash=prev_hash,
        at=at,
        hash=h,
    )


@dataclass(frozen=True)
class ChainVerification:
    valid: bool
    case_id: str | None = None
    break_at_seq: int | None = None
    reason: str | None = None


def verify_chain(case_id: str, events: list[TraceEvent]) -> ChainVerification:
    """Recomputes every event's hash from its own fields and checks prev_hash linkage,
    in seq order. events must already be sorted by seq -- this function verifies that
    invariant rather than assuming it, since a caller reading from a database without an
    explicit ORDER BY is exactly the kind of bug this exists to catch. An empty case
    (no events yet) is vacuously valid."""
    if not events:
        return ChainVerification(valid=True, case_id=case_id)
    expected_prev = GENESIS
    for i, e in enumerate(events):
        if e.case_id != case_id:
            return ChainVerification(False, case_id, e.seq, f"event at index {i} belongs to case {e.case_id!r}, not {case_id!r}")
        if e.seq != i:
            return ChainVerification(False, case_id, e.seq, f"events out of sequence: expected seq {i} at index {i}, found {e.seq}")
        if e.prev_hash != expected_prev:
            return ChainVerification(False, case_id, e.seq, f"prev_hash mismatch at seq {e.seq}: expected {expected_prev}, found {e.prev_hash}")
        recomputed = _event_hash(e.case_id, e.seq, e.stage, e.payload_sha256, e.prev_hash, e.at)
        if recomputed != e.hash:
            return ChainVerification(
                False, case_id, e.seq,
                f"hash mismatch at seq {e.seq}: stored hash does not match the recomputed hash -- "
                "payload_sha256, stage, or at was altered after the event was written",
            )
        expected_prev = e.hash
    return ChainVerification(valid=True, case_id=case_id)
