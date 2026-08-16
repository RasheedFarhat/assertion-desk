"""Tests for the CustodyRecord aggregate (desk/custody/record.py): hash stability
regardless of finding order, hash sensitivity to real content changes, count accuracy,
and confirmation the summary dict a case card would render never carries a raw value.
"""

from __future__ import annotations

import os

from desk.custody.findings import Action, CustodyFinding, FindingClass, Liveness
from desk.custody.record import build_custody_record
from desk.custody.scan import CustodyResult, run_custody

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "verify", "phase0_fixtures")


def _read(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def _finding(finding_class, location, placeholder, action=Action.REPLACED) -> CustodyFinding:
    return CustodyFinding(finding_class, location, placeholder, Liveness.UNKNOWN, action, "test.detector", "1")


def test_hash_is_stable_regardless_of_finding_order():
    f1 = _finding(FindingClass.IDP_SESSION_COOKIE, "loc.a", "{{COOKIE:1111}}")
    f2 = _finding(FindingClass.API_KEY, "loc.b", "{{APIKEY:2222}}")

    result_ab = CustodyResult(defanged_bytes=b"x", findings=[f1, f2])
    result_ba = CustodyResult(defanged_bytes=b"x", findings=[f2, f1])

    record_ab = build_custody_record("artifact-1", result_ab)
    record_ba = build_custody_record("artifact-1", result_ba)

    assert record_ab.sha256 == record_ba.sha256


def test_hash_changes_when_findings_differ():
    f1 = _finding(FindingClass.IDP_SESSION_COOKIE, "loc.a", "{{COOKIE:1111}}")
    f2 = _finding(FindingClass.API_KEY, "loc.b", "{{APIKEY:2222}}")
    f3 = _finding(FindingClass.EMAIL_PII, "loc.c", "{{EMAIL:3333}}")

    record_two = build_custody_record("artifact-1", CustodyResult(defanged_bytes=b"x", findings=[f1, f2]))
    record_three = build_custody_record("artifact-1", CustodyResult(defanged_bytes=b"x", findings=[f1, f2, f3]))

    assert record_two.sha256 != record_three.sha256


def test_hash_is_a_real_sha256_hex_digest():
    record = build_custody_record("artifact-1", CustodyResult(defanged_bytes=b"x", findings=[]))
    assert len(record.sha256) == 64
    int(record.sha256, 16)  # raises ValueError if not valid hex


def test_empty_findings_hashes_deterministically():
    a = build_custody_record("artifact-1", CustodyResult(defanged_bytes=b"x", findings=[]))
    b = build_custody_record("artifact-2", CustodyResult(defanged_bytes=b"y", findings=[]))
    # Same (empty) finding content -> same hash, even though artifact_id and bytes differ.
    # The hash covers findings only, deliberately -- it's a content-of-secrets digest,
    # not a whole-record digest.
    assert a.sha256 == b.sha256


def test_counts_by_class_matches_findings():
    findings = [
        _finding(FindingClass.IDP_SESSION_COOKIE, "loc.a", "{{COOKIE:1111}}"),
        _finding(FindingClass.IDP_SESSION_COOKIE, "loc.b", "{{COOKIE:2222}}"),
        _finding(FindingClass.API_KEY, "loc.c", "{{APIKEY:3333}}"),
    ]
    record = build_custody_record("artifact-1", CustodyResult(defanged_bytes=b"x", findings=findings))
    assert record.counts_by_class == {"idp_session_cookie": 2, "api_key": 1}
    assert sum(record.counts_by_class.values()) == len(findings)


def test_any_live_credential_passthrough():
    live_finding = CustodyFinding(
        FindingClass.IDP_SESSION_COOKIE, "loc.a", "{{COOKIE:1111}}", Liveness.LIVE, Action.REPLACED, "test", "1"
    )
    record = build_custody_record("artifact-1", CustodyResult(defanged_bytes=b"x", findings=[live_finding]))
    assert record.any_live_credential is True

    expired_finding = CustodyFinding(
        FindingClass.IDP_SESSION_COOKIE, "loc.a", "{{COOKIE:1111}}", Liveness.EXPIRED, Action.REPLACED, "test", "1"
    )
    record2 = build_custody_record("artifact-1", CustodyResult(defanged_bytes=b"x", findings=[expired_finding]))
    assert record2.any_live_credential is False


def test_summary_dict_has_no_raw_value_field():
    record = build_custody_record("artifact-1", CustodyResult(defanged_bytes=b"x", findings=[]))
    summary = record.to_summary_dict()
    expected_keys = {"artifact_id", "sha256", "counts_by_class", "any_live_credential", "total_findings"}
    assert set(summary.keys()) == expected_keys


def test_build_custody_record_end_to_end_on_real_fixture():
    """The real path: run_custody() -> build_custody_record() against the real HAR
    fixture, confirming the aggregate builds cleanly and its counts are internally
    consistent with the underlying findings list."""
    result = run_custody("har", _read("real_login.har"))
    record = build_custody_record("real_login.har", result)

    assert record.any_live_credential == result.any_live_credential
    assert sum(record.counts_by_class.values()) == len(result.findings)
    assert len(record.sha256) == 64

    # Determinism: scanning the same bytes again produces the same hash.
    result_again = run_custody("har", _read("real_login.har"))
    record_again = build_custody_record("real_login.har", result_again)
    assert record.sha256 == record_again.sha256
