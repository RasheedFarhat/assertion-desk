"""desk/ground -- cross-checks Job C's output against the real VerificationRun. This is
the package the plan's own repo-structure section (26) calls "the file that ends the
'wrapper' argument": nothing here does anything clever, it just refuses to let a model
claim be true unless the deterministic verifier already produced that exact claim.
"""

from desk.ground.validator import GroundingResult, GroundingViolation, ViolationKind, validate_job_c_output

__all__ = ["GroundingResult", "GroundingViolation", "ViolationKind", "validate_job_c_output"]
