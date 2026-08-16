"""Phase 4 exit criteria (plan section 27): grounding unit tests including deliberately
ungrounded outputs, plus a genuinely-grounded output that must be accepted.

Every test here builds its own synthetic VerificationRun from hand-constructed
CheckResult rows rather than running the real verifier against a corpus fixture --
desk/ground/validator.py's job is to cross-check parsed Job C content against
`run.results`, and a synthetic run makes every violation kind reachable on demand
instead of hunting the corpus for a case that happens to trigger it. Real corpus
coverage of this module lives at the integration level (eval/run.py + eval/metrics.py's
grounding_rejection_rate).
"""

from __future__ import annotations

from desk.ground.validator import GroundingResult, ViolationKind, validate_job_c_output
from desk.verify.assurance import Assurance, CheckResult
from desk.verify.verifier import VerificationRun


def _run(*results: CheckResult) -> VerificationRun:
    return VerificationRun(parse_error=None, results=list(results))


CERT_FAILED = CheckResult(
    check_id="SAML-CERT-02",
    assurance=Assurance.FAILED,
    observed="9f:2c:11:...",
    expected="4a:71:e8:...",
    reason="signing cert thumbprint does not match metadata",
)
SIG_VERIFIED = CheckResult(
    check_id="SAML-SIG-01",
    assurance=Assurance.VERIFIED,
    observed="valid",
    expected="valid",
    reason="signature verifies",
)
ATTR_REVIEW = CheckResult(
    check_id="SAML-ATTR-01",
    assurance=Assurance.REVIEW_REQUIRED,
    observed="duplicate Name attributes",
    expected="unique Name attributes",
    reason="role attribute Name appears twice with conflicting values",
)
SKEW_NOT_VERIFIED = CheckResult(
    check_id="SAML-SKEW-01",
    assurance=Assurance.NOT_VERIFIED,
    observed=None,
    expected=None,
    reason="no SP clock evidence supplied",
)


# --------------------------------------------------------------------------------- #
# The accepted path -- a genuinely grounded output must not be rejected for any reason.
# --------------------------------------------------------------------------------- #


def test_grounded_output_is_accepted():
    run = _run(CERT_FAILED, SIG_VERIFIED)
    parsed = {
        "summary": "The presented certificate does not match your metadata.",
        "root_cause": "SAML-CERT-02",
        "fix_steps": ["Re-upload the current signing certificate to your metadata."],
        "claims": [
            {
                "text": "SAML-CERT-02: signing cert thumbprint does not match metadata",
                "check_id": "SAML-CERT-02",
                "asserted_state": "failed",
            },
            {
                "text": "SAML-SIG-01: signature verifies",
                "check_id": "SAML-SIG-01",
                "asserted_state": "verified",
            },
        ],
    }
    result = validate_job_c_output(parsed, run)
    assert isinstance(result, GroundingResult)
    assert result.accepted is True
    assert result.violations == []
    assert result.claims_total == 2
    assert result.claims_verified == 2


def test_review_required_root_cause_is_a_legal_diagnosis():
    """The duplicate_role_attributes corpus finding, replicated directly: a root cause
    pointing at a REVIEW_REQUIRED check (conflicting signals, not an outright failure)
    must be accepted, not rejected as unfounded. A FAILED-only rule would reject the
    one corpus case where this is the correct answer (see validator.py's module
    docstring and _LEGAL_ROOT_CAUSE_STATES)."""
    run = _run(ATTR_REVIEW, SIG_VERIFIED)
    parsed = {
        "summary": "Two conflicting values were sent for the same role attribute.",
        "root_cause": "SAML-ATTR-01",
        "fix_steps": ["Confirm which role attribute value is authoritative."],
        "claims": [
            {
                "text": "SAML-ATTR-01: duplicate Name attributes",
                "check_id": "SAML-ATTR-01",
                "asserted_state": "review_required",
            }
        ],
    }
    result = validate_job_c_output(parsed, run)
    assert result.accepted is True
    assert result.violations == []


# --------------------------------------------------------------------------------- #
# Each rejection kind, triggered on its own so a failure here points at exactly one
# mechanism.
# --------------------------------------------------------------------------------- #


def test_empty_claims_is_rejected():
    run = _run(CERT_FAILED)
    parsed = {"summary": "Something is wrong.", "root_cause": None, "fix_steps": [], "claims": []}
    result = validate_job_c_output(parsed, run)
    assert result.accepted is False
    assert result.claims_total == 0
    kinds = [v.kind for v in result.violations]
    assert ViolationKind.EMPTY_CLAIMS in kinds


def test_unknown_check_in_claim_is_rejected():
    run = _run(CERT_FAILED)
    parsed = {
        "summary": "The evidence-skip check passed.",
        "root_cause": None,
        "fix_steps": [],
        "claims": [
            {"text": "made up", "check_id": "EVIDENCE-SKIP-01", "asserted_state": "verified"}
        ],
    }
    result = validate_job_c_output(parsed, run)
    assert result.accepted is False
    violation = next(v for v in result.violations if v.kind == ViolationKind.UNKNOWN_CHECK)
    assert violation.claim_index == 0
    assert "EVIDENCE-SKIP-01" in violation.detail
    assert result.claims_verified == 0


def test_state_contradiction_is_rejected():
    """The exact failure mode this module was built to catch (see the module
    docstring's own account): a claim cites a real check_id correctly but asserts a
    state the verifier did not actually find for it."""
    run = _run(CERT_FAILED)
    parsed = {
        "summary": "Your certificate is fine.",
        "root_cause": None,
        "fix_steps": [],
        "claims": [
            {"text": "SAML-CERT-02 is fine", "check_id": "SAML-CERT-02", "asserted_state": "verified"}
        ],
    }
    result = validate_job_c_output(parsed, run)
    assert result.accepted is False
    violation = next(v for v in result.violations if v.kind == ViolationKind.STATE_CONTRADICTION)
    assert violation.claim_index == 0
    assert "SAML-CERT-02" in violation.detail
    assert result.claims_verified == 0


def test_uncited_check_reference_in_prose_is_rejected():
    """A check ID that shows up in free prose (summary or fix_steps) but has no
    matching claims[] entry has nothing an auditor can verify it against -- the claim
    is the audit unit, per the module docstring."""
    run = _run(CERT_FAILED, SIG_VERIFIED)
    parsed = {
        "summary": "SAML-SIG-01 also looked suspicious.",
        "root_cause": "SAML-CERT-02",
        "fix_steps": ["Re-upload your certificate."],
        "claims": [
            {
                "text": "SAML-CERT-02: signing cert thumbprint does not match metadata",
                "check_id": "SAML-CERT-02",
                "asserted_state": "failed",
            }
        ],
    }
    result = validate_job_c_output(parsed, run)
    assert result.accepted is False
    violation = next(v for v in result.violations if v.kind == ViolationKind.UNCITED_CHECK_REFERENCE)
    assert "SAML-SIG-01" in violation.detail
    assert violation.claim_index is None


def test_root_cause_pointing_at_a_passing_check_is_rejected():
    """A model is never short of confidence (module docstring) -- citing a real,
    correctly-described check that is VERIFIED is not a diagnosis."""
    run = _run(CERT_FAILED, SIG_VERIFIED)
    parsed = {
        "summary": "The signature is the problem.",
        "root_cause": "SAML-SIG-01",
        "fix_steps": [],
        "claims": [
            {"text": "SAML-SIG-01: signature verifies", "check_id": "SAML-SIG-01", "asserted_state": "verified"}
        ],
    }
    result = validate_job_c_output(parsed, run)
    assert result.accepted is False
    violation = next(v for v in result.violations if v.kind == ViolationKind.ROOT_CAUSE_NOT_FAILED)
    assert "SAML-SIG-01" in violation.detail


def test_root_cause_pointing_at_a_gap_is_rejected():
    """NOT_VERIFIED is deliberately excluded from the legal root-cause states (module
    docstring): a gap means "we don't know," never a cause."""
    run = _run(SKEW_NOT_VERIFIED, CERT_FAILED)
    parsed = {
        "summary": "The clock is the problem.",
        "root_cause": "SAML-SKEW-01",
        "fix_steps": [],
        "claims": [
            {
                "text": "SAML-CERT-02: signing cert thumbprint does not match metadata",
                "check_id": "SAML-CERT-02",
                "asserted_state": "failed",
            }
        ],
    }
    result = validate_job_c_output(parsed, run)
    assert result.accepted is False
    violation = next(v for v in result.violations if v.kind == ViolationKind.ROOT_CAUSE_NOT_FAILED)
    assert "SAML-SKEW-01" in violation.detail


def test_unknown_root_cause_is_rejected():
    run = _run(CERT_FAILED)
    parsed = {
        "summary": "made up",
        "root_cause": "EVIDENCE-SKIP-01",
        "fix_steps": [],
        "claims": [
            {
                "text": "SAML-CERT-02: signing cert thumbprint does not match metadata",
                "check_id": "SAML-CERT-02",
                "asserted_state": "failed",
            }
        ],
    }
    result = validate_job_c_output(parsed, run)
    assert result.accepted is False
    kinds = [v.kind for v in result.violations]
    assert ViolationKind.UNKNOWN_CHECK in kinds


def test_multiple_violations_are_all_reported_not_just_the_first():
    """Matches this repo's existing pattern (validate_against_schema, and
    tests/harness/test_corpus.py) of collecting every mismatch at once rather than
    stopping at the first -- a caller inspecting a rejected output should see its
    whole shape, not one violation at a time across repeated calls."""
    run = _run(CERT_FAILED)
    parsed = {
        "summary": "SAML-SIG-01 is also broken.",
        "root_cause": None,
        "fix_steps": [],
        "claims": [
            {"text": "made up", "check_id": "EVIDENCE-SKIP-01", "asserted_state": "verified"}
        ],
    }
    result = validate_job_c_output(parsed, run)
    assert result.accepted is False
    kinds = {v.kind for v in result.violations}
    assert ViolationKind.UNKNOWN_CHECK in kinds
    assert ViolationKind.UNCITED_CHECK_REFERENCE in kinds
