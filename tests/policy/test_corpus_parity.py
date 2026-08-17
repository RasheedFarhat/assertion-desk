"""Corpus-driven parity test for desk/policy/rules.py, in the spirit of Control
Plane's cross-implementation parity suite (plan section 27 cites that pattern for this
exact module). Reads the canonical, already-committed eval run
(eval/runs/20260817T044253Z/, see docs/MEASUREMENTS.md) rather than re-running the
pipeline -- $0, no network, and it exercises the exact same persisted CaseRecord shape
eval/metrics.py's disposition_accuracy() reads in production use.

This does not re-derive disposition_accuracy()'s logic; it calls it directly and
asserts its own honesty contract: the known, named mismatches stay exactly the known,
named mismatches (no more, no fewer), and every other one of the 50 runnable cases
matches exactly. If a code change makes one of them start matching, that is good news
and this test's second assertion below will fail loudly, which is the signal to remove
that KNOWN_DISPOSITION_MISMATCHES entry rather than leave a stale exception sitting in
the codebase.
"""

from __future__ import annotations

from pathlib import Path

from eval.metrics import KNOWN_DISPOSITION_MISMATCHES, disposition_accuracy, load_records

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CANONICAL_RUN = REPO_ROOT / "eval" / "runs" / "20260817T044253Z" / "records.json"


def _load():
    assert CANONICAL_RUN.exists(), f"canonical eval run missing: {CANONICAL_RUN}"
    return load_records(CANONICAL_RUN)


def test_all_50_runnable_cases_are_scored():
    records = _load()
    result = disposition_accuracy(records)
    assert result["n"] == 50


def test_only_the_known_mismatch_diverges():
    records = _load()
    result = disposition_accuracy(records)
    mismatched_ids = {row["case_id"] for row in result["unexpected_mismatches"]}
    assert mismatched_ids == set(), (
        f"unexpected disposition mismatch(es) not on the known list: {mismatched_ids}. "
        "Either this is a real regression in desk/policy/rules.py, or a genuinely new, "
        "understood divergence that belongs in eval/metrics.py's "
        "KNOWN_DISPOSITION_MISMATCHES with the same treatment as duplicate_role_attributes."
    )
    known_ids = {row["case_id"] for row in result["known_mismatches"]}
    assert known_ids == set(KNOWN_DISPOSITION_MISMATCHES), (
        "the known-mismatch set drifted from KNOWN_DISPOSITION_MISMATCHES's keys -- "
        "if duplicate_role_attributes now matches, remove its entry rather than leave "
        "a stale exception; if a new case diverges, name and explain it before adding it here"
    )


def test_accuracy_is_47_of_50():
    # Written as an explicit number, not just "n - 3", so a future silent change in
    # which cases mismatch (still only the same three) is caught by this test even if
    # the count stays the same.
    records = _load()
    result = disposition_accuracy(records)
    assert result["correct"] == 47
    assert result["n"] == 50


def test_known_mismatches_are_exactly_the_documented_shape():
    # All three known mismatches share one root cause (the universal SAML-INRESP-01/02
    # baseline noise -- see eval/metrics.py's KNOWN_DISPOSITION_MISMATCHES) and the same
    # observable shape: the corpus expected review_required, the policy engine
    # (correctly, on the real signals it has) computed awaiting_evidence.
    records = _load()
    result = disposition_accuracy(records)
    rows = {row["case_id"]: row for row in result["known_mismatches"]}
    assert set(rows) == {"duplicate_role_attributes", "wrong_binding", "stripped_relaystate"}
    for case_id, row in rows.items():
        assert row["expected"] == "review_required", case_id
        assert row["actual"] == "awaiting_evidence", case_id
