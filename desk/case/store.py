"""SQLite-backed persistence for Case and TraceEvent (plan section 19). Same honestly
caveated position as Control Plane's lab/db.py: the schema below is written in portable
SQL (TEXT/INTEGER columns, `?` parameterized placeholders, no SQLite-only pragmas beyond
foreign_keys), so it is expected to also work against PostgreSQL (plan section 18 names
Postgres as the intended production backend, and compose.yaml will eventually run it) --
but nothing in this repo's test suite runs it against Postgres. Only SQLite is tested.
"designed to be Postgres-compatible" and "verified Postgres coverage" are different
claims, and this module only makes the first one -- the exact distinction this
workspace's own notes on Control Plane's lab/db.py already draw, deliberately repeated
here rather than assumed silently.

Every statement is hand-written and parameterized (sqlite3's native `?` placeholders) --
no ORM, no string-built SQL. security_flags is the one Case field with no native SQL
array type available in either engine without an extension, so it is stored as a
JSON-encoded TEXT column and decoded back into a tuple on read; every other Case and
TraceEvent field maps directly onto one column.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
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
