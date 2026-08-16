"""Cross-checks a Job C response against the real VerificationRun and rejects the whole
output if any part of it is not grounded in what the verifier actually found. desk/reason
deliberately stops at "schema-valid" (see jobs.py's module docstring); this module is the
only place that asks whether the content is *true*.

A rejection here is a recorded outcome, not an exception. Nothing raises for a bad model
output -- validate_job_c_output always returns a GroundingResult, and a rejected result
(.accepted is False) names exactly what was wrong via .violations. "How many outputs got
rejected, and why" is one of the eval's headline metrics (plan section 23, grounding
violation catch rate), so a violation has to be a data point, not a stack trace.

This was built immediately after a live smoke test (desk/reason/jobs.py against the real
clock_skew corpus case) produced exactly the failure mode this module exists to catch:
Ollama's Job C asserted root_cause "SAML-ISS-01" at asserted_state "verified" -- a real
check in the run, correctly described, but not a failure of any kind. A model is never
short of confidence; root_cause_not_failed exists because "cites something real" and
"cites the thing that's actually wrong" are different claims, and only the second one is
a diagnosis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from desk.verify.assurance import Assurance
from desk.verify.verifier import VerificationRun

# A root cause has to point at an actual finding. NOT_VERIFIED is deliberately excluded
# here even though it's "notable" enough to gate Job C's invocation elsewhere in the
# system (run.has_any_failed() only checks FAILED) -- a gap is "we don't know", never a
# cause. REVIEW_REQUIRED is included on purpose: the duplicate_role_attributes corpus
# case has expected_root_cause pointing at a REVIEW_REQUIRED check (conflicting signals,
# not an outright failure), and the same smoke test that motivated this module showed
# Ollama getting that case right. A FAILED-only rule would have rejected the one case in
# the corpus where the model's disambiguation was correct.
_LEGAL_ROOT_CAUSE_STATES = {Assurance.FAILED, Assurance.REVIEW_REQUIRED}

# Check IDs look like "SAML-CERT-01", "SAML-SKEW-01", etc. (desk/verify/checks/*).
_CHECK_ID_RE = re.compile(r"\bSAML-[A-Z]+-\d+\b")


class ViolationKind:
    EMPTY_CLAIMS = "empty_claims"
    UNKNOWN_CHECK = "unknown_check"
    STATE_CONTRADICTION = "state_contradiction"
    UNCITED_CHECK_REFERENCE = "uncited_check_reference"
    ROOT_CAUSE_NOT_FAILED = "root_cause_not_failed"


@dataclass
class GroundingViolation:
    kind: str
    detail: str
    claim_index: int | None = None  # None for violations that aren't about one specific claim


@dataclass
class GroundingResult:
    accepted: bool
    violations: list[GroundingViolation] = field(default_factory=list)
    claims_total: int = 0
    claims_verified: int = 0  # claims whose check_id exists and whose asserted_state matched


def validate_job_c_output(parsed: dict[str, Any], run: VerificationRun) -> GroundingResult:
    """parsed is a Job C response that has already passed schema validation (see
    desk/reason/jobs.py's JobResult.accepted) -- this function assumes claims/root_cause/
    summary/fix_steps are present with the right shapes and only checks their content
    against `run`, the same VerificationRun the prompt was built from."""
    real_by_id = {r.check_id: r for r in run.results}
    violations: list[GroundingViolation] = []

    claims = parsed.get("claims") or []
    if not claims:
        violations.append(GroundingViolation(ViolationKind.EMPTY_CLAIMS, "claims[] is empty"))

    claims_verified = 0
    cited_check_ids: set[str] = set()
    for i, claim in enumerate(claims):
        check_id = claim.get("check_id")
        asserted_state = claim.get("asserted_state")
        cited_check_ids.add(check_id)

        real = real_by_id.get(check_id)
        if real is None:
            violations.append(
                GroundingViolation(
                    ViolationKind.UNKNOWN_CHECK,
                    f"claim cites check_id {check_id!r}, which does not exist in this run",
                    claim_index=i,
                )
            )
            continue

        if real.assurance.value != asserted_state:
            violations.append(
                GroundingViolation(
                    ViolationKind.STATE_CONTRADICTION,
                    f"claim asserts {check_id} is {asserted_state!r}, but the verifier found "
                    f"{real.assurance.value!r}",
                    claim_index=i,
                )
            )
            continue

        claims_verified += 1

    # uncited_check_reference: a check-ID-shaped token in free prose (summary, fix_steps)
    # that no claims[] entry cites. A claim is the audit unit -- a check ID that only
    # appears in prose carries no asserted_state, so there's nothing to verify it against.
    prose = " ".join([parsed.get("summary") or "", *(parsed.get("fix_steps") or [])])
    uncited_tokens = {m.group(0) for m in _CHECK_ID_RE.finditer(prose)} - cited_check_ids
    for token in sorted(uncited_tokens):
        violations.append(
            GroundingViolation(
                ViolationKind.UNCITED_CHECK_REFERENCE,
                f"{token!r} appears in free prose with no matching claims[] entry",
            )
        )

    root_cause = parsed.get("root_cause")
    if root_cause is not None:
        real_root = real_by_id.get(root_cause)
        if real_root is None:
            violations.append(
                GroundingViolation(ViolationKind.UNKNOWN_CHECK, f"root_cause {root_cause!r} does not exist in this run")
            )
        elif real_root.assurance not in _LEGAL_ROOT_CAUSE_STATES:
            violations.append(
                GroundingViolation(
                    ViolationKind.ROOT_CAUSE_NOT_FAILED,
                    f"root_cause {root_cause!r} is {real_root.assurance.value!r}, not failed or "
                    "review_required -- a root cause must point at an actual finding, not a gap "
                    "or a passing check",
                )
            )

    return GroundingResult(
        accepted=not violations,
        violations=violations,
        claims_total=len(claims),
        claims_verified=claims_verified,
    )
