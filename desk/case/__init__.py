"""Case lifecycle: state machine (state.py), hash-linked audit trace (trace.py), and
SQLite persistence (store.py) -- plan section 19/21/22. See each module's own docstring
for the design decisions; this file only re-exports the public surface."""

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
from desk.case.store import CaseStore, connect
from desk.case.trace import GENESIS, ChainVerification, TraceEvent, append_event, verify_chain

__all__ = [
    "CASE_TRANSITIONS",
    "INITIAL_STATES",
    "TERMINAL_STATES",
    "Case",
    "CaseState",
    "IllegalTransition",
    "is_terminal",
    "new_case",
    "transition",
    "CaseStore",
    "connect",
    "GENESIS",
    "ChainVerification",
    "TraceEvent",
    "append_event",
    "verify_chain",
]
