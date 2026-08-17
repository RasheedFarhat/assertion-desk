"""Direct tests for desk/pipeline.py, independent of eval/run.py's corpus-adapter
layer (the module eval/run.py's run_case() now delegates to -- see desk/pipeline.py's
own docstring for the extraction rationale). eval/run.py's existing suite, especially
tests/reason/test_replay_determinism.py's byte-identical-records assertion, already
covers run_pipeline() indirectly through run_case()/run_corpus(). This file exists to
prove the thing the extraction was actually for: that run_pipeline() is callable on
its own, with nothing but a VerificationContext, a narrative dict or None, and raw
SAMLResponse bytes or None -- no case_dir, no label.json, no corpus/cases/ involved --
which is exactly the shape a future live case orchestrator will call.

Test data is loaded from real corpus cases (via eval.run's own loaders, reused rather
than duplicated) purely as convenient real fixtures, the same way tests/reason/
test_jobs.py mirrors corpus cases without importing the corpus machinery itself. Every
assertion here is against run_pipeline()'s return value directly.
"""

from __future__ import annotations

from desk.pipeline import PipelineResult, run_pipeline
from desk.reason.fixtures import FixtureCache
from eval.run import CASES_DIR, build_clients, load_context, load_narrative

CERT_EXPIRED_DIR = CASES_DIR / "cert_expired"
NEGATIVE_CONTROL_DIR = CASES_DIR / "negative_control"
WITHHELD_CLOCK_DIR = CASES_DIR / "withheld_clock"


def _clients():
    # Fresh build_clients() per call, matching tests/reason/test_replay_determinism.py's
    # pattern -- ReasonClient instances are cheap and this avoids any cross-test state.
    return build_clients()


def _fixtures() -> FixtureCache:
    # The real, committed fixtures/ directory, not a tmp_path copy -- these tests exist
    # to prove run_pipeline() itself replays deterministically, which only means
    # something against the fixture cache `make eval-replay` actually reads.
    return FixtureCache()


def test_ok_case_with_a_failed_check_produces_a_grounded_root_cause():
    """cert_expired: a single clean fault. All three jobs run, Job C's claim is
    grounded against the real VerificationRun, and final_root_cause is set."""
    ctx = load_context(CERT_EXPIRED_DIR)
    narrative = load_narrative(CERT_EXPIRED_DIR)
    raw = (CERT_EXPIRED_DIR / "saml_response.xml").read_bytes()

    result = run_pipeline(
        raw_saml_response=raw,
        ctx=ctx,
        narrative=narrative,
        clients=_clients(),
        fixtures=_fixtures(),
        replay_only=True,
    )

    assert isinstance(result, PipelineResult)
    assert result.verify_state == "ok"
    assert result.run is not None
    assert result.job_a is not None
    assert result.job_a.tier_used == "fixture"
    assert result.job_b is not None
    assert result.job_c is not None
    assert result.job_c.accepted is True
    assert result.grounding is not None
    assert result.grounding.accepted is True
    assert result.final_root_cause == "SAML-CERT-01"


def test_no_saml_response_runs_job_a_only_and_never_touches_verify():
    """negative_control: raw_saml_response=None mirrors label.json's
    no_saml_response_reason exactly (see desk/pipeline.py's own docstring). Job A still
    runs because a real narrative exists -- the customer's actual problem (a typo'd
    password) has nothing to do with a broken trust chain, but comprehending what they
    said is still useful. Job B/C/grounding never run: there is no VerificationRun to
    compute a gap list or a failed-check set from."""
    narrative = load_narrative(NEGATIVE_CONTROL_DIR)
    assert narrative is not None  # this case's whole point is a real narrative present

    result = run_pipeline(
        raw_saml_response=None,
        ctx=load_context(NEGATIVE_CONTROL_DIR),
        narrative=narrative,
        clients=_clients(),
        fixtures=_fixtures(),
        replay_only=True,
    )

    assert result.verify_state == "no_saml_response"
    assert result.run is None
    assert result.job_a is not None
    assert result.job_a.tier_used == "fixture"
    assert result.job_b is None
    assert result.job_c is None
    assert result.grounding is None
    assert result.final_root_cause is None


def test_ambiguous_case_with_no_failed_check_never_invokes_job_c():
    """withheld_clock: verify_state is "ok" but no check FAILED (the missing SP clock
    evidence makes SAML-SKEW-01 not_verified, not failed) -- run_pipeline must not ask
    the model to guess a root cause from nothing. Job B still runs because a real gap
    exists (compute_gaps() is non-empty)."""
    ctx = load_context(WITHHELD_CLOCK_DIR)
    narrative = load_narrative(WITHHELD_CLOCK_DIR)
    raw = (WITHHELD_CLOCK_DIR / "saml_response.xml").read_bytes()

    result = run_pipeline(
        raw_saml_response=raw,
        ctx=ctx,
        narrative=narrative,
        clients=_clients(),
        fixtures=_fixtures(),
        replay_only=True,
    )

    assert result.verify_state == "ok"
    assert result.run is not None
    assert result.run.has_any_failed() is False
    assert result.job_a is not None
    assert result.job_b is not None
    assert result.job_c is None
    assert result.grounding is None
    assert result.final_root_cause is None


def test_no_narrative_and_no_saml_response_runs_nothing():
    """The fully-empty edge case no corpus case actually exercises: a hypothetical live
    case where the customer's bundle contained neither a SAMLResponse nor any
    comprehensible narrative. Confirms run_pipeline() degrades to an all-None result
    rather than raising -- it takes primitives only and places no requirement that a
    narrative or a SAMLResponse exist, matching desk/pipeline.py's own corpus-agnostic
    contract (there is no case_dir or label.json here at all)."""
    result = run_pipeline(
        raw_saml_response=None,
        ctx=load_context(NEGATIVE_CONTROL_DIR),
        narrative=None,
        clients=_clients(),
        fixtures=_fixtures(),
        replay_only=True,
    )

    assert result.verify_state == "no_saml_response"
    assert result.run is None
    assert result.job_a is None
    assert result.job_b is None
    assert result.job_c is None
    assert result.grounding is None
    assert result.final_root_cause is None


def test_run_pipeline_signature_takes_no_corpus_concepts():
    """A deliberately blunt check on the extraction's central claim: run_pipeline()'s
    parameter names carry no notion of a case_dir, a label, or a corpus. If this ever
    fails, the corpus-agnostic boundary the extraction was built around has eroded."""
    import inspect

    params = set(inspect.signature(run_pipeline).parameters)
    assert params == {"raw_saml_response", "ctx", "narrative", "clients", "fixtures", "replay_only"}
