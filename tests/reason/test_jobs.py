"""Unit tests for desk/reason/jobs.py's deterministic-only templates -- specifically
render_deterministic_job_c's root_cause tie-break, which docs/MEASUREMENTS.md's full
50-case run found picking the wrong check in a majority of multi-finding cases (a
SAML-SIG-* row winning ALL_CHECKS's registration-order tie-break over the check that
actually names the injected fault). The fix demotes SAML-SIG-* checks below any other
FAILED check, on the general protocol grounds documented in
desk.reason.jobs._is_signature_check, not by reading any case's expected label.
"""

from __future__ import annotations

import pytest

from desk.reason.jobs import pick_root_cause_check_id, render_deterministic_job_c
from desk.verify.assurance import Assurance, CheckResult
from desk.verify.verifier import VerificationRun


def _result(check_id: str, assurance: Assurance, reason: str = "because") -> CheckResult:
    observed = "x" if assurance == Assurance.VERIFIED else None
    return CheckResult(check_id=check_id, assurance=assurance, observed=observed, expected=None, reason=reason)


def test_root_cause_prefers_specific_check_over_signature_side_effect():
    """Mirrors corpus/MANIFEST.json's cert_rotation case: the signature checks are
    registered first in ALL_CHECKS and fail as a side effect, but SAML-CERT-02 is the
    check that names the actual injected fault and must win."""
    run = VerificationRun(
        parse_error=None,
        results=[
            _result("SAML-SIG-01", Assurance.FAILED, "digest mismatch"),
            _result("SAML-SIG-02", Assurance.FAILED, "digest mismatch"),
            _result("SAML-CERT-02", Assurance.FAILED, "thumbprint does not match metadata"),
            _result("SAML-AUD-01", Assurance.VERIFIED),
        ],
    )
    out = render_deterministic_job_c(run)
    assert out["root_cause"] == "SAML-CERT-02"
    # every FAILED/REVIEW_REQUIRED row still surfaces as a claim, signature checks included
    claim_ids = {c["check_id"] for c in out["claims"]}
    assert claim_ids == {"SAML-SIG-01", "SAML-SIG-02", "SAML-CERT-02"}


def test_root_cause_is_signature_check_when_it_is_the_only_failure():
    """Mirrors corpus/MANIFEST.json's broken_signature case (target_check_ids ==
    ["SAML-SIG-01"]): when a signature check is the *only* FAILED row, it must still be
    reported as root_cause -- the demotion only applies when a non-signature FAILED
    check is available to prefer instead."""
    run = VerificationRun(
        parse_error=None,
        results=[
            _result("SAML-SIG-01", Assurance.FAILED, "signature value invalid"),
            _result("SAML-CERT-01", Assurance.VERIFIED),
            _result("SAML-AUD-01", Assurance.VERIFIED),
        ],
    )
    out = render_deterministic_job_c(run)
    assert out["root_cause"] == "SAML-SIG-01"


def test_root_cause_prefers_failed_over_review_required():
    run = VerificationRun(
        parse_error=None,
        results=[
            _result("SAML-ATTR-01", Assurance.REVIEW_REQUIRED, "duplicate role attribute values"),
            _result("SAML-CERT-02", Assurance.FAILED, "thumbprint does not match metadata"),
        ],
    )
    out = render_deterministic_job_c(run)
    assert out["root_cause"] == "SAML-CERT-02"


def test_root_cause_falls_back_to_review_required_when_nothing_failed():
    """Mirrors corpus/MANIFEST.json's duplicate_role_attributes case: SAML-ATTR-01 is
    REVIEW_REQUIRED and nothing is FAILED, so it must still be selectable as root_cause
    rather than raising."""
    run = VerificationRun(
        parse_error=None,
        results=[
            _result("SAML-ATTR-01", Assurance.REVIEW_REQUIRED, "duplicate role attribute values"),
            _result("SAML-AUD-01", Assurance.VERIFIED),
        ],
    )
    out = render_deterministic_job_c(run)
    assert out["root_cause"] == "SAML-ATTR-01"


def test_raises_when_nothing_notable():
    run = VerificationRun(parse_error=None, results=[_result("SAML-AUD-01", Assurance.VERIFIED)])
    with pytest.raises(ValueError):
        render_deterministic_job_c(run)


# --------------------------------------------------------------------------------- #
# pick_root_cause_check_id directly -- this is the function eval/metrics.py's
# deterministic_root_cause() calls too (a prior version of this file's tests only
# exercised it indirectly through render_deterministic_job_c, which meant
# eval/metrics.py's separate hand-copied reimplementation of the same rule silently
# drifted out of sync with the fix and was never caught until a real corpus run
# showed deterministic_only_accuracy hadn't moved). These tests operate on the same
# (check_id, assurance_value) tuple shape eval/metrics.py passes in, not on
# CheckResult/VerificationRun objects, so they exercise the exact call shape used by
# both real callers.
# --------------------------------------------------------------------------------- #


def test_pick_root_cause_prefers_specific_check_over_signature_side_effect():
    rows = [
        ("SAML-SIG-01", "failed"),
        ("SAML-SIG-02", "failed"),
        ("SAML-CERT-02", "failed"),
        ("SAML-AUD-01", "verified"),
    ]
    assert pick_root_cause_check_id(rows) == "SAML-CERT-02"


def test_pick_root_cause_is_signature_check_when_it_is_the_only_failure():
    rows = [("SAML-SIG-01", "failed"), ("SAML-CERT-01", "verified")]
    assert pick_root_cause_check_id(rows) == "SAML-SIG-01"


def test_pick_root_cause_returns_none_when_nothing_notable():
    rows = [("SAML-AUD-01", "verified"), ("SAML-CERT-01", "verified")]
    assert pick_root_cause_check_id(rows) is None
