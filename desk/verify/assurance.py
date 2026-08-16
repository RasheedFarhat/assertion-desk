"""The six-state assurance taxonomy, reused from mcp-detect/docs/CONTROL-ASSURANCE.md.

The one rule that matters more than any individual check: absence of evidence must
never produce VERIFIED. A check with no input to evaluate returns NOT_VERIFIED, not a
guess and not a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Assurance(str, Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"
    NOT_VERIFIED = "not_verified"
    NOT_TESTED = "not_tested"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class CheckResult:
    check_id: str
    assurance: Assurance
    observed: str | None
    expected: str | None
    reason: str
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        # The taxonomy's one hard invariant, enforced at construction time rather than
        # only in a test: nothing can claim VERIFIED without something to point at.
        if self.assurance == Assurance.VERIFIED and self.observed is None:
            raise ValueError(
                f"{self.check_id}: refusing to construct a VERIFIED CheckResult with no "
                "observed value -- absence of evidence must never yield verified"
            )
