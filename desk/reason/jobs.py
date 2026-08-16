"""Ties custody, prompts, schemas, and the fallback chain together into the three jobs
the rest of the system calls: run_job_a (intake comprehension), run_job_b (missing-
evidence request), run_job_c (explanation synthesis). Also owns the deterministic-only
template renderers used when every model tier is exhausted (plan T7) -- kept here,
next to the prompts they stand in for, rather than in desk/reason/fallback.py, which
stays a pure dispatcher that doesn't know what a job's output is supposed to mean.

Grounding is deliberately NOT done here. run_job_c returns a schema-valid parse; a
separate module (desk/ground/validator.py) decides whether its *content* is grounded in
the real check results. Keeping that boundary means this file never has to reason about
what "grounded" means, and desk/ground never has to know how a job was produced.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from desk.custody.scan import run_custody
from desk.reason.client import ReasonClient
from desk.reason.fallback import ReplayMiss, TieredResult, run_with_fallback
from desk.reason.fixtures import FixtureCache
from desk.reason.prompts import (
    build_job_a_prompt,
    build_job_b_prompt,
    build_job_c_prompt,
    detect_instruction_shaped_spans,
)
from desk.reason.schemas import JOB_A_SCHEMA, JOB_B_SCHEMA, JOB_C_SCHEMA, validate_against_schema
from desk.verify.assurance import Assurance
from desk.verify.gaps import Gap
from desk.verify.verifier import VerificationRun

__all__ = [
    "JobResult",
    "run_job_a",
    "run_job_b",
    "run_job_c",
    "render_deterministic_job_a",
    "render_deterministic_job_b",
    "render_deterministic_job_c",
    "ReplayMiss",
]


@dataclass
class JobResult:
    job: str  # "A" | "B" | "C"
    tier_used: str  # "fixture" | a client's model_id (as reported by ModelResponse.provider) | "deterministic"
    parsed: dict[str, Any] | None
    schema_violations: list[str]
    accepted: bool  # schema-valid, nothing more -- grounding (Job C) is a separate check
    prompt_sha256: str
    latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    instruction_signals: list[dict] = field(default_factory=list)


# --------------------------------------------------------------------------------- #
# Deterministic-only templates. Each produces schema-valid output with zero model
# calls, so a case is never left without a verdict just because every tier failed.
# --------------------------------------------------------------------------------- #


def render_deterministic_job_a() -> dict[str, Any]:
    """All-unknown facts. Matches plan section 16's "unavailable" behavior for Job A:
    the case proceeds with every field unknown/null rather than blocking, and Job B's
    template falls back to the standard artifact set instead of anything Job A would
    have supplied."""
    return {
        "scope": "unknown",
        "scope_confidence": 0.0,
        "onset": None,
        "onset_confidence": 0.0,
        "recent_change": None,
        "recent_change_confidence": 0.0,
        "already_tried": [],
        "reporter_role": None,
        "reporter_role_confidence": 0.0,
        "wrong_belief": None,
        "wrong_belief_confidence": 0.0,
    }


def render_deterministic_job_b(gaps: list[Gap]) -> dict[str, Any]:
    if not gaps:
        raise ValueError("render_deterministic_job_b requires a non-empty gap list")
    artifacts = sorted({g.requested_artifact for g in gaps})
    reason_lines = "\n".join(f"- {g.reason} (needed to check {g.check_id})" for g in gaps)
    body = (
        "We were not able to fully verify your SSO configuration because some evidence "
        "is still missing:\n\n"
        f"{reason_lines}\n\n"
        "Could you provide the following so we can finish checking your setup? "
        f"{', '.join(artifacts)}."
    )
    return {
        "subject": "Additional evidence needed to diagnose your SSO issue",
        "body": body,
        "requested_artifacts": artifacts,
    }


def render_deterministic_job_c(run: VerificationRun) -> dict[str, Any]:
    """Renders every FAILED/REVIEW_REQUIRED row as a claim -- deliberately not just the
    single "root cause" -- so a multi-finding case (see duplicate_role_attributes,
    which carries an independently REVIEW_REQUIRED SAML-ATTR-01 alongside FAILED
    SIG/CERT checks) still surfaces every real finding in deterministic-only mode, not
    just the one this template happens to pick as root_cause. root_cause prefers a
    FAILED row over a REVIEW_REQUIRED one, and within a tier uses ALL_CHECKS's list
    order (the order run.results was built in) for a stable, reproducible pick."""
    notable = [r for r in run.results if r.assurance in (Assurance.FAILED, Assurance.REVIEW_REQUIRED)]
    if not notable:
        raise ValueError(
            "render_deterministic_job_c requires at least one FAILED or REVIEW_REQUIRED "
            "check; callers must gate on run.has_any_failed() before invoking Job C"
        )
    root = next((r for r in notable if r.assurance == Assurance.FAILED), notable[0])
    claims = [
        {"text": f"{r.check_id}: {r.reason}", "check_id": r.check_id, "asserted_state": r.assurance.value}
        for r in notable
    ]
    fix_steps = [f"Review {r.check_id}: {r.reason}" for r in notable]
    return {
        "summary": f"Verification found a problem with {root.check_id}: {root.reason}",
        "root_cause": root.check_id,
        "fix_steps": fix_steps,
        "claims": claims,
    }


# --------------------------------------------------------------------------------- #
# Shared finalize step: a model/fixture response that fails to parse as JSON or fails
# schema validation is treated exactly like an exhausted fallback chain -- degrade to
# the deterministic template rather than propagate a broken parse downstream. Token
# and latency accounting still reflects the real (wasted) call, because that cost was
# genuinely incurred even though the content wasn't usable.
# --------------------------------------------------------------------------------- #


def _finalize(
    job: str,
    prompt_sha256: str,
    tiered: TieredResult,
    schema: dict[str, Any],
    deterministic_fn,
    instruction_signals: list[dict],
) -> JobResult:
    if tiered.response is None:
        parsed = deterministic_fn()
        violations = validate_against_schema(parsed, schema)
        return JobResult(
            job=job,
            tier_used="deterministic",
            parsed=parsed,
            schema_violations=violations,
            accepted=not violations,
            prompt_sha256=prompt_sha256,
            latency_ms=None,
            input_tokens=None,
            output_tokens=None,
            instruction_signals=instruction_signals,
        )

    parsed: dict[str, Any] | None
    try:
        parsed = json.loads(tiered.response.text)
        violations = (
            validate_against_schema(parsed, schema)
            if isinstance(parsed, dict)
            else ["response did not parse to a JSON object"]
        )
    except json.JSONDecodeError as exc:
        parsed = None
        violations = [f"response was not valid JSON: {exc}"]

    tier_used = tiered.tier_used
    if parsed is None or violations:
        parsed = deterministic_fn()
        violations = validate_against_schema(parsed, schema)
        tier_used = "deterministic"

    return JobResult(
        job=job,
        tier_used=tier_used,
        parsed=parsed,
        schema_violations=violations,
        accepted=not violations,
        prompt_sha256=prompt_sha256,
        latency_ms=tiered.response.latency_ms,
        input_tokens=tiered.response.input_tokens,
        output_tokens=tiered.response.output_tokens,
        instruction_signals=instruction_signals,
    )


# --------------------------------------------------------------------------------- #
# The three jobs.
# --------------------------------------------------------------------------------- #


def run_job_a(
    subject: str,
    body: str,
    *,
    clients: list[ReasonClient],
    fixtures: FixtureCache,
    replay_only: bool = False,
) -> JobResult:
    # Custody first, always -- Job A must never see raw customer prose. run_custody
    # fails closed (raises CustodyFailure) rather than ever returning unredacted bytes.
    subject_defanged = run_custody("narrative", subject.encode("utf-8")).defanged_bytes.decode("utf-8")
    body_defanged = run_custody("narrative", body.encode("utf-8")).defanged_bytes.decode("utf-8")

    instruction_signals = detect_instruction_shaped_spans(subject_defanged) + detect_instruction_shaped_spans(
        body_defanged
    )

    prompt = build_job_a_prompt(subject_defanged, body_defanged)
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    tiered = run_with_fallback(prompt, JOB_A_SCHEMA, clients=clients, fixtures=fixtures, replay_only=replay_only)
    return _finalize("A", prompt_sha256, tiered, JOB_A_SCHEMA, render_deterministic_job_a, instruction_signals)


def run_job_b(
    gaps: list[Gap],
    job_a_facts: dict[str, Any] | None,
    *,
    clients: list[ReasonClient],
    fixtures: FixtureCache,
    replay_only: bool = False,
) -> JobResult:
    if not gaps:
        raise ValueError("run_job_b requires a non-empty gap list; the Job B gate is gaps non-empty")

    prompt = build_job_b_prompt(gaps, job_a_facts)
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    tiered = run_with_fallback(prompt, JOB_B_SCHEMA, clients=clients, fixtures=fixtures, replay_only=replay_only)
    return _finalize(
        "B",
        prompt_sha256,
        tiered,
        JOB_B_SCHEMA,
        lambda: render_deterministic_job_b(gaps),
        instruction_signals=[],  # Job B reads deterministic gap data + already-extracted
        # facts, not raw customer prose -- nothing new to scan here
    )


def run_job_c(
    run: VerificationRun,
    job_a_facts: dict[str, Any] | None,
    *,
    clients: list[ReasonClient],
    fixtures: FixtureCache,
    replay_only: bool = False,
) -> JobResult:
    if not run.has_any_failed():
        raise ValueError(
            "run_job_c requires run.has_any_failed(); the model is never asked to guess "
            "a root cause when the verifier found nothing FAILED"
        )

    check_rows = [
        {
            "check_id": r.check_id,
            "assurance": r.assurance.value,
            "observed": r.observed,
            "expected": r.expected,
            "reason": r.reason,
        }
        for r in run.results
    ]
    prompt = build_job_c_prompt(check_rows, job_a_facts)
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    tiered = run_with_fallback(prompt, JOB_C_SCHEMA, clients=clients, fixtures=fixtures, replay_only=replay_only)
    return _finalize(
        "C", prompt_sha256, tiered, JOB_C_SCHEMA, lambda: render_deterministic_job_c(run), instruction_signals=[]
    )
