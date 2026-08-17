"""SQLite-backed persistence for Case, TraceEvent, and Approval (plan section 19). Same
honestly caveated position as Control Plane's lab/db.py: the schema below is written in
portable SQL (TEXT/INTEGER columns, `?` parameterized placeholders, no SQLite-only
pragmas beyond foreign_keys), so it is expected to also work against PostgreSQL (plan
section 18 names Postgres as the intended production backend, and compose.yaml will
eventually run it) -- but nothing in this repo's test suite runs it against Postgres.
Only SQLite is tested. "designed to be Postgres-compatible" and "verified Postgres
coverage" are different claims, and this module only makes the first one -- the exact
distinction this workspace's own notes on Control Plane's lab/db.py already draw,
deliberately repeated here rather than assumed silently.

Every statement is hand-written and parameterized (sqlite3's native `?` placeholders) --
no ORM, no string-built SQL. security_flags is the one Case field with no native SQL
array type available in either engine without an extension, so it is stored as a
JSON-encoded TEXT column and decoded back into a tuple on read; every other Case,
TraceEvent, and Approval field maps directly onto one column.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from desk.case.approval import Approval
from desk.case.state import Case, CaseState
from desk.case.trace import TraceEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id              TEXT PRIMARY KEY,
    correlation_id  TEXT NOT NULL,
    tenant_ref      TEXT,
    state           TEXT NOT NULL,
    disposition     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    security_flags  TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS ix_cases_state ON cases(state);
CREATE INDEX IF NOT EXISTS ix_cases_correlation_id ON cases(correlation_id);

CREATE TABLE IF NOT EXISTS trace_events (
    case_id         TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    stage           TEXT NOT NULL,
    payload_sha256  TEXT NOT NULL,
    prev_hash       TEXT NOT NULL,
    at              TEXT NOT NULL,
    hash            TEXT NOT NULL,
    PRIMARY KEY (case_id, seq),
    FOREIGN KEY (case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS approvals (
    id                TEXT PRIMARY KEY,
    case_id           TEXT NOT NULL,
    approver          TEXT NOT NULL,
    decision          TEXT NOT NULL,
    responded_at      TEXT NOT NULL,
    override_reason   TEXT,
    channel           TEXT NOT NULL,
    latency_seconds   REAL,
    FOREIGN KEY (case_id) REFERENCES cases(id)
);

CREATE INDEX IF NOT EXISTS ix_approvals_case_id ON approvals(case_id);
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    # check_same_thread=False: sqlite3's default same-thread check assumes a
    # single-threaded caller. desk/api.py's Flask dev server (Werkzeug) dispatches
    # request handling on a thread other than the one that opened this connection --
    # confirmed empirically running `make serve` and posting a case, which raised
    # sqlite3.ProgrammingError before this flag was added. Werkzeug's dev server
    # still runs threaded=False (one request at a time, no concurrency), so this is
    # safe: it relaxes Python's same-thread guard without introducing the concurrent
    # access CaseStore does not itself lock against. A future concurrent (threaded or
    # multi-worker) deployment would need real per-request connections or a
    # connection pool, not just this flag -- that is out of scope for the dev server
    # this module currently serves.
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _row_to_case(row: sqlite3.Row) -> Case:
    return Case(
        id=row["id"],
        correlation_id=row["correlation_id"],
        tenant_ref=row["tenant_ref"],
        state=CaseState(row["state"]),
        disposition=row["disposition"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        security_flags=tuple(json.loads(row["security_flags"])),
    )


def _row_to_trace_event(row: sqlite3.Row) -> TraceEvent:
    return TraceEvent(
        case_id=row["case_id"],
        seq=row["seq"],
        stage=row["stage"],
        payload_sha256=row["payload_sha256"],
        prev_hash=row["prev_hash"],
        at=row["at"],
        hash=row["hash"],
    )


def _row_to_approval(row: sqlite3.Row) -> Approval:
    return Approval(
        id=row["id"],
        case_id=row["case_id"],
        approver=row["approver"],
        decision=row["decision"],
        responded_at=row["responded_at"],
        override_reason=row["override_reason"],
        channel=row["channel"],
        latency_seconds=row["latency_seconds"],
    )


class CaseStore:
    """Thin wrapper around a sqlite3.Connection. Every write here is a single statement
    inside its own commit -- there is no multi-statement write path yet that needs an
    outbox pattern the way Control Plane's event worker does; a case's state row and its
    trace events are always written from separate, already-ordered call sites in the
    (not-yet-built) orchestrator. If a future n8n integration adds concurrent writers to
    the same case, that is the point to revisit this, not before.

    This class never calls desk.case.state.transition() itself and never validates a
    state edge -- it trusts the caller already has a legally-transitioned Case in hand.
    Enforcing the state machine is state.py's job; store.py only persists what it is
    given."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_case(self, case: Case) -> None:
        self.conn.execute(
            "INSERT INTO cases (id, correlation_id, tenant_ref, state, disposition, "
            "created_at, updated_at, security_flags) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case.id,
                case.correlation_id,
                case.tenant_ref,
                case.state.value,
                case.disposition,
                case.created_at,
                case.updated_at,
                json.dumps(list(case.security_flags)),
            ),
        )
        self.conn.commit()

    def update_case(self, case: Case) -> None:
        cur = self.conn.execute(
            "UPDATE cases SET state = ?, disposition = ?, updated_at = ?, "
            "security_flags = ? WHERE id = ?",
            (
                case.state.value,
                case.disposition,
                case.updated_at,
                json.dumps(list(case.security_flags)),
                case.id,
            ),
        )
        if cur.rowcount == 0:
            raise KeyError(f"no case with id {case.id!r} to update -- call insert_case first")
        self.conn.commit()

    def get_case(self, case_id: str) -> Case | None:
        row = self.conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        return _row_to_case(row) if row is not None else None

    def list_cases_by_state(self, state: CaseState) -> list[Case]:
        rows = self.conn.execute(
            "SELECT * FROM cases WHERE state = ? ORDER BY updated_at", (state.value,)
        ).fetchall()
        return [_row_to_case(r) for r in rows]

    def append_trace_event(self, event: TraceEvent) -> None:
        self.conn.execute(
            "INSERT INTO trace_events (case_id, seq, stage, payload_sha256, prev_hash, "
            "at, hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event.case_id,
                event.seq,
                event.stage,
                event.payload_sha256,
                event.prev_hash,
                event.at,
                event.hash,
            ),
        )
        self.conn.commit()

    def get_trace(self, case_id: str) -> list[TraceEvent]:
        rows = self.conn.execute(
            "SELECT * FROM trace_events WHERE case_id = ? ORDER BY seq", (case_id,)
        ).fetchall()
        return [_row_to_trace_event(r) for r in rows]

    def last_trace_event(self, case_id: str) -> TraceEvent | None:
        row = self.conn.execute(
            "SELECT * FROM trace_events WHERE case_id = ? ORDER BY seq DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        return _row_to_trace_event(row) if row is not None else None

    def insert_approval(self, approval: Approval) -> None:
        self.conn.execute(
            "INSERT INTO approvals (id, case_id, approver, decision, responded_at, "
            "override_reason, channel, latency_seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                approval.id,
                approval.case_id,
                approval.approver,
                approval.decision,
                approval.responded_at,
                approval.override_reason,
                approval.channel,
                approval.latency_seconds,
            ),
        )
        self.conn.commit()

    def get_approvals(self, case_id: str) -> list[Approval]:
        rows = self.conn.execute(
            "SELECT * FROM approvals WHERE case_id = ? ORDER BY responded_at", (case_id,)
        ).fetchall()
        return [_row_to_approval(r) for r in rows]
