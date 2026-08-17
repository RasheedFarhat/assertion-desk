"""The real Assertion Desk pipeline: verify -> gap computation -> reason (Job A/B/C)
-> ground. This is the one place that sequence is implemented. eval/run.py (the
corpus batch runner) and any future live case orchestrator (desk/case's state
machine driving desk/api.py, plan section 22 -- not built yet) both call into this
module rather than each reimplementing the verify-then-reason-then-ground sequence.
The layering direction is eval/ and desk/api.py depend on desk/pipeline.py, never the
reverse -- matching the direction eval/metrics.py already established by reading
desk/policy/rules.py.

Extracted from eval/run.py's run_case() (Phase 4), where this exact logic first got
written and tested against the full corpus. The extraction is deliberately behavior-
preserving, not a rewrite: eval/run.py's run_case() now calls run_pipeline() and
layers its own corpus-only concerns (on-disk case loading, stored-check-result
parity against corpus/MANIFEST.json, CaseRecord/JobRecord serialization) on top.
tests/reason/test_replay_determinism.py's byte-identical-records assertion is the
regression check that this extraction changed nothing observable.

Deliberately corpus-agnostic. This module has never heard of a case_dir, a
label.json, or corpus/cases/ -- it takes an already-decided VerificationContext, an
already-loaded narrative dict (or None), and either the raw SAMLResponse bytes to
verify or None when there is nothing to verify (the corpus's no_saml_response cases;
a live case with no SAMLResponse anywhere in the customer's bundle is the identical
situation, decided by desk/intake instead of a label field). That is what makes it
reusable from a live orchestrator later without corpus_cases/*.json existing at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from desk.ground.validator import GroundingResult, validate_job_c_output
from desk.reason.client import ReasonClient
from desk.reason.fixtures import FixtureCache
from desk.reason.jobs import JobResult, run_job_a, run_job_b, run_job_c
from desk.verify.context import VerificationContext
from desk.verify.gaps import compute_gaps
from desk.verify.verifier import VerificationRun, run_all_checks


@dataclass
class PipelineResult:
    verify_state: str  # "ok" | "parse_error" | "no_saml_response"
    run: VerificationRun | None
    job_a: JobResult | None
    job_b: JobResult | None
    job_c: JobResult | None
    grounding: GroundingResult | None
    final_root_cause: str | None


def run_pipeline(
    *,
    raw_saml_response: bytes | None,
    ctx: VerificationContext,
    narrative: dict[str, Any] | None,
    clients: list[ReasonClient],
    fixtures: FixtureCache,
    replay_only: bool,
) -> PipelineResult:
    """raw_saml_response=None means there is nothing to verify -- mirrors
    harness/generate.py's own no_saml_response_reason handling exactly (resolved.raw
    is None there too), so a corpus case and a live case that both never produced a
    SAMLResponse land in the identical verify_state="no_saml_response" branch below,
    for the identical reason: there is no trust chain to check, only a narrative to
    read. narrative={"subject":..., "body":...} or None; Job A runs whenever a
    narrative exists regardless of verify_state (see the inline comment below --
    negative_control's whole point is a real narrative with no SAMLResponse behind
    it), and only Job B/Job C are gated on a completed, error-free VerificationRun."""
    if raw_saml_response is None:
        run: VerificationRun | None = None
        verify_state = "no_saml_response"
    else:
        run = run_all_checks(raw_saml_response, ctx)
        verify_state = "parse_error" if run.parse_error is not None else "ok"

    job_a_result: JobResult | None = None
    job_b_result: JobResult | None = None
    job_c_result: JobResult | None = None
    grounding_result: GroundingResult | None = None
    final_root_cause: str | None = None
    job_a_facts: dict[str, Any] | None = None

    if narrative is not None:
        job_a_result = run_job_a(
            narrative["subject"], narrative["body"], clients=clients, fixtures=fixtures, replay_only=replay_only
        )
        job_a_facts = job_a_result.parsed

    if verify_state == "ok":
        assert run is not None  # verify_state == "ok" guarantees this

        gaps = compute_gaps(run)
        if gaps:
            job_b_result = run_job_b(gaps, job_a_facts, clients=clients, fixtures=fixtures, replay_only=replay_only)

        if run.has_any_failed():
            job_c_result = run_job_c(run, job_a_facts, clients=clients, fixtures=fixtures, replay_only=replay_only)

            if job_c_result.accepted:
                if job_c_result.tier_used == "deterministic":
                    # Grounded by construction: render_deterministic_job_c derives
                    # every claim straight from `run`, so there is nothing for
                    # desk/ground to check that isn't true by definition. Skipping the
                    # call here (rather than calling it and asserting it always
                    # passes) keeps any grounding-rejection-rate metric honestly
                    # scoped to outputs that were actually capable of being wrong.
                    final_root_cause = job_c_result.parsed.get("root_cause")
                else:
                    grounding_result = validate_job_c_output(job_c_result.parsed, run)
                    if grounding_result.accepted:
                        final_root_cause = job_c_result.parsed.get("root_cause")
                    # else: final_root_cause stays None. A rejected Job C output
                    # publishes nothing -- that is the entire reason desk/ground
                    # exists.
    # verify_state in ("parse_error", "no_saml_response"): no checks (or no usable
    # checks) exist for Job B/C to work from, so neither is invoked and
    # final_root_cause stays None.

    return PipelineResult(
        verify_state=verify_state,
        run=run,
        job_a=job_a_result,
        job_b=job_b_result,
        job_c=job_c_result,
        grounding=grounding_result,
        final_root_cause=final_root_cause,
    )
