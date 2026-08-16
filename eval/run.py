"""Runs the full frozen corpus (corpus/cases/) through the real Phase 1-4 pipeline
(desk/verify -> desk/reason -> desk/ground) and persists one record per case plus a
combined records.json under eval/runs/<timestamp>/. Nothing in this file computes an
accuracy number -- that is eval/metrics.py's job, reading these records back in.

Corpus taxonomy this file has to respect (reverse-engineered from corpus/MANIFEST.json
and harness/generate.py by direct inspection, not assumed):

  documented_gap (1 case, sha1_signature_downgrade). label.json is the only file on
  disk -- no context.json, no check_results.json, no narrative.json. It documents a
  fault the check catalogue can't detect yet (see harness/faults/base.py's own
  DOCUMENTED_GAP handling). Not runnable. discover_case_ids() excludes it before the
  main loop; it is reported separately, never silently dropped and never counted as a
  failure.

  no_saml_response (1 case, negative_control). label.json's no_saml_response_reason is
  set: the IdP rejected the credential before producing a SAMLResponse, so
  harness/generate.py never calls run_all_checks on it at all -- it passes run=None
  directly (resolved.raw is None there). run_verification() mirrors that exactly rather
  than synthesizing an empty-bytes parse error, which looks similar but is caused
  differently and was rejected during Phase 4 smoke-testing for exactly that reason.

  malformed (2 cases: truncated_response, double_encoded_response). expects_parse_failure
  is true; run_all_checks runs normally and is expected to set run.parse_error. Job A/B/C
  are never invoked once a parse error is set (run_case's verify_state gate), matching
  desk/reason/jobs.py's contract that Job C requires a real, error-free VerificationRun.

  ambiguous (2: withheld_cert, withheld_clock) and conflicting (1:
  duplicate_role_attributes) run through the identical pipeline as every other case --
  what distinguishes them is the *expected* answer, not special handling here.
  Concretely: duplicate_role_attributes' expected_root_cause is SAML-ATTR-01, not null,
  under expected_disposition "review_required" -- so "ambiguous + conflicting means
  always refuse" is not a rule this file encodes anywhere. That grading logic belongs in
  eval/metrics.py, keyed off each label's own expected_root_cause/expected_disposition.

  adversarial (4 cases, identified by label["injection"] being non-null). Run through the
  identical pipeline as any other case -- adversarial-ness is a property of narrative/HAR/
  XML content the pipeline reads, not a different code path here. eval/metrics.py
  separates these out for the injection-resistance metric using the same label field.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from desk.ground.validator import GroundingResult, validate_job_c_output
from desk.reason.client import GeminiClient, OllamaClient, ReasonClient
from desk.reason.fallback import ReplayMiss
from desk.reason.fixtures import DEFAULT_FIXTURE_DIR, FixtureCache
from desk.reason.jobs import JobResult, run_job_a, run_job_b, run_job_c
from desk.verify.context import VerificationContext
from desk.verify.gaps import compute_gaps
from desk.verify.verifier import VerificationRun, run_all_checks
from harness.generate import _ctx_to_json, _run_to_json  # noqa: F401  -- _ctx_to_json is
# imported for symmetry/future use, _run_to_json is load-bearing (check_stored_parity).
# Reused rather than duplicated: harness.generate imports cleanly with no Keycloak/
# Playwright cost (confirmed empirically, ~0.2s), and importing the corpus's own
# serializer beats hand-copying it and risking silent drift from what actually froze the
# corpus -- the same anti-duplication principle harness/generate.py's own docstring states
# about shared HAR artifacts.

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO_ROOT / "corpus"
CASES_DIR = CORPUS_DIR / "cases"
MANIFEST_PATH = CORPUS_DIR / "MANIFEST.json"
RUNS_DIR = Path(__file__).resolve().parent / "runs"


@dataclass
class JobRecord:
    """Trimmed view of a JobResult for persistence. Drops nothing an eval metric or the
    report needs, but keeps records.json readable by a human without a schema in hand."""

    job: str
    tier_used: str
    accepted: bool
    schema_violations: list[str]
    parsed: dict[str, Any] | None
    latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    instruction_signals: list[dict] = field(default_factory=list)

    @classmethod
    def from_job_result(cls, r: JobResult) -> "JobRecord":
        return cls(
            job=r.job,
            tier_used=r.tier_used,
            accepted=r.accepted,
            schema_violations=r.schema_violations,
            parsed=r.parsed,
            latency_ms=r.latency_ms,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            instruction_signals=r.instruction_signals,
        )


@dataclass
class GroundingRecord:
    accepted: bool
    claims_total: int
    claims_verified: int
    violations: list[dict]

    @classmethod
    def from_result(cls, g: GroundingResult) -> "GroundingRecord":
        return cls(
            accepted=g.accepted,
            claims_total=g.claims_total,
            claims_verified=g.claims_verified,
            violations=[dataclasses.asdict(v) for v in g.violations],
        )


@dataclass
class CaseRecord:
    case_id: str
    label: dict[str, Any]
    verify_state: str  # "ok" | "parse_error" | "no_saml_response" | "error"
    verify_error: str | None
    check_counts: dict[str, int] | None
    check_results: list[dict] | None
    stored_parity_ok: bool | None  # None only when there's nothing to compare
    job_a: JobRecord | None
    job_b: JobRecord | None
    job_c: JobRecord | None
    grounding: GroundingRecord | None
    final_root_cause: str | None
    injection: dict | None
    error: str | None = None  # set only on verify_state == "error"


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def load_label(case_dir: Path) -> dict:
    return json.loads((case_dir / "label.json").read_text())


def load_context(case_dir: Path) -> VerificationContext:
    raw = json.loads((case_dir / "context.json").read_text())
    return VerificationContext(
        sp_entity_id=raw["sp_entity_id"],
        acs_url=raw["acs_url"],
        idp_entity_id=raw["idp_entity_id"],
        trusted_cert_pem=raw.get("trusted_cert_pem"),
        in_response_to_expected=raw.get("in_response_to_expected"),
        sp_clock=datetime.fromisoformat(raw["sp_clock"]) if raw.get("sp_clock") else None,
        clock_skew_tolerance_seconds=raw.get("clock_skew_tolerance_seconds", 180),
        evaluation_time=datetime.fromisoformat(raw["evaluation_time"]) if raw.get("evaluation_time") else None,
    )


def load_narrative(case_dir: Path) -> dict | None:
    path = case_dir / "narrative.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_stored_check_results(case_dir: Path) -> dict | None:
    path = case_dir / "check_results.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def check_stored_parity(run: VerificationRun | None, stored: dict | None) -> bool:
    """True if a fresh run_all_checks() call reproduces exactly what harness/generate.py
    froze into check_results.json. A mismatch means the verifier's behavior has drifted
    since the corpus was generated -- the corpus needs regenerating, not the eval adjusted
    to match. Uses the corpus's own serializer (_run_to_json) so this is the identical
    equality harness/generate.py's own self-test relies on."""
    return _run_to_json(run) == stored


def run_verification(
    case_id: str, case_dir: Path, label: dict, ctx: VerificationContext
) -> tuple[str, VerificationRun | None, str | None]:
    """Returns (verify_state, run, verify_error). Mirrors harness/generate.py's own
    branching exactly: a case with no_saml_response_reason set never calls
    run_all_checks -- it gets run=None directly, matching what the real corpus generator
    does (resolved.raw is None there). Synthesizing an empty-bytes parse error instead was
    tried during Phase 4 smoke-testing and produces a superficially similar but
    differently-caused result; this function does not repeat that shortcut."""
    if label.get("no_saml_response_reason"):
        return "no_saml_response", None, None

    saml_path = case_dir / "saml_response.xml"
    if not saml_path.exists():
        # Every other case in the corpus carries a saml_response.xml. A case missing one
        # without no_saml_response_reason set is a harness bug, not something to skip
        # quietly.
        return "error", None, f"{case_id}: no saml_response.xml on disk and no_saml_response_reason unset"

    raw_bytes = saml_path.read_bytes()
    run = run_all_checks(raw_bytes, ctx)
    if run.parse_error is not None:
        return "parse_error", run, None
    return "ok", run, None


def _check_results_to_json(run: VerificationRun) -> list[dict]:
    return [
        {
            "check_id": r.check_id,
            "assurance": r.assurance.value,
            "observed": r.observed,
            "expected": r.expected,
            "reason": r.reason,
            "evidence_ref": r.evidence_ref,
        }
        for r in run.results
    ]


def run_case(
    case_id: str,
    case_dir: Path,
    label: dict,
    *,
    clients: list[ReasonClient],
    fixtures: FixtureCache,
    replay_only: bool,
) -> CaseRecord:
    ctx = load_context(case_dir)
    narrative = load_narrative(case_dir)
    stored = load_stored_check_results(case_dir)

    verify_state, run, verify_error = run_verification(case_id, case_dir, label, ctx)

    stored_parity_ok = None
    check_counts = None
    check_results = None
    if verify_state in ("ok", "parse_error") and run is not None:
        stored_parity_ok = check_stored_parity(run, stored)
        check_results = _check_results_to_json(run)
        if verify_state == "ok":
            check_counts = run.counts()
    elif verify_state == "no_saml_response":
        # harness/generate.py freezes check_results.json as the literal JSON null for
        # this case (resolved.raw is None -> _run_to_json(None) -> None) -- confirmed by
        # direct inspection of corpus/cases/negative_control/check_results.json.
        stored_parity_ok = stored is None

    job_a_result = job_b_result = job_c_result = None
    grounding_record = None
    final_root_cause = None
    job_a_facts: dict[str, Any] | None = None

    # Job A depends only on the narrative (subject/body) -- desk/reason/jobs.py's
    # run_job_a takes no VerificationRun at all. Gating it on verify_state == "ok" would
    # wrongly skip comprehension for negative_control, whose whole point is a real
    # narrative with no SAMLResponse behind it (the customer's actual problem is a typo'd
    # password, not a broken trust chain) -- confirmed by direct inspection that
    # negative_control does carry a narrative.json. So Job A runs whenever a narrative
    # exists, full stop; only Job B and Job C are gated on a completed, error-free run.
    if narrative is not None:
        job_a = run_job_a(
            narrative["subject"], narrative["body"], clients=clients, fixtures=fixtures, replay_only=replay_only
        )
        job_a_result = JobRecord.from_job_result(job_a)
        job_a_facts = job_a.parsed

    if verify_state == "ok":
        assert run is not None  # verify_state == "ok" guarantees this

        gaps = compute_gaps(run)
        if gaps:
            job_b = run_job_b(gaps, job_a_facts, clients=clients, fixtures=fixtures, replay_only=replay_only)
            job_b_result = JobRecord.from_job_result(job_b)

        if run.has_any_failed():
            job_c = run_job_c(run, job_a_facts, clients=clients, fixtures=fixtures, replay_only=replay_only)
            job_c_result = JobRecord.from_job_result(job_c)

            if job_c.accepted:
                if job_c.tier_used == "deterministic":
                    # Grounded by construction: render_deterministic_job_c derives every
                    # claim straight from `run`, so there is nothing for desk/ground to
                    # check that isn't true by definition. Skipping the call here (rather
                    # than calling it and asserting it always passes) keeps
                    # eval/metrics.py's grounding-rejection-rate honestly scoped to
                    # outputs that were actually capable of being wrong.
                    final_root_cause = job_c.parsed.get("root_cause")
                else:
                    grounding = validate_job_c_output(job_c.parsed, run)
                    grounding_record = GroundingRecord.from_result(grounding)
                    if grounding.accepted:
                        final_root_cause = job_c.parsed.get("root_cause")
                    # else: final_root_cause stays None. A rejected Job C output
                    # publishes nothing -- that is the entire reason desk/ground exists.
    # verify_state in ("parse_error", "no_saml_response"): no checks (or no usable
    # checks) exist for Job B/C to work from, so neither is invoked and final_root_cause
    # stays None, matching every such case's own expected_root_cause in the corpus.

    return CaseRecord(
        case_id=case_id,
        label=label,
        verify_state=verify_state,
        verify_error=verify_error,
        check_counts=check_counts,
        check_results=check_results,
        stored_parity_ok=stored_parity_ok,
        job_a=job_a_result,
        job_b=job_b_result,
        job_c=job_c_result,
        grounding=grounding_record,
        final_root_cause=final_root_cause,
        injection=label.get("injection"),
    )


def discover_case_ids(manifest: dict) -> list[str]:
    """Every case in MANIFEST.json except documented_gap entries, which have no
    context.json/narrative.json/check_results.json to run against (see module
    docstring). Sorted for reproducible run ordering."""
    return sorted(cid for cid, c in manifest["cases"].items() if c.get("category") != "documented_gap")


def build_clients() -> list[ReasonClient]:
    """Gemini primary, Ollama fallback (plan section 16's cascade). Both are always
    constructed -- GeminiClient self-reports ProviderUnavailable at call time via its own
    GEMINI_API_KEY check, so tier-selection logic lives in exactly one place
    (desk/reason/fallback.py) rather than being duplicated here as a pre-flight check."""
    return [GeminiClient(), OllamaClient()]


def run_corpus(
    case_ids: list[str],
    *,
    clients: list[ReasonClient],
    fixtures: FixtureCache,
    replay_only: bool,
) -> list[CaseRecord]:
    """Runs every case with per-case isolation: one case raising is recorded as
    verify_state="error" with the exception text and does not stop the run (plan section
    27, Phase 4 exit criteria). ReplayMiss is the one exception let through uncaught --
    in replay_only mode a fixture miss must stop the run loudly, matching
    desk/reason/fallback.py's own contract for `make eval-replay`."""
    records: list[CaseRecord] = []
    for case_id in case_ids:
        case_dir = CASES_DIR / case_id
        label = load_label(case_dir)
        try:
            record = run_case(
                case_id, case_dir, label, clients=clients, fixtures=fixtures, replay_only=replay_only
            )
        except ReplayMiss:
            raise
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: one bad case must
            # never sink the whole corpus run
            record = CaseRecord(
                case_id=case_id,
                label=label,
                verify_state="error",
                verify_error=None,
                check_counts=None,
                check_results=None,
                stored_parity_ok=None,
                job_a=None,
                job_b=None,
                job_c=None,
                grounding=None,
                final_root_cause=None,
                injection=label.get("injection"),
                error=f"{type(exc).__name__}: {exc}",
            )
        records.append(record)
    return records


def persist(
    records: list[CaseRecord],
    *,
    out_dir: Path,
    manifest: dict,
    replay_only: bool,
    documented_gap_ids: list[str],
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    cases_out = out_dir / "cases"
    cases_out.mkdir(exist_ok=True)
    for r in records:
        (cases_out / f"{r.case_id}.json").write_text(
            json.dumps(dataclasses.asdict(r), indent=2, sort_keys=True) + "\n"
        )
    combined = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "replay_only": replay_only,
        "corpus_generated_at": manifest.get("generated_at"),
        "corpus_totals": manifest.get("totals"),
        "documented_gap_ids": documented_gap_ids,
        "case_count": len(records),
        "cases": [dataclasses.asdict(r) for r in records],
    }
    records_path = out_dir / "records.json"
    records_path.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n")
    return records_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the frozen Assertion Desk corpus through the real pipeline.")
    parser.add_argument(
        "--replay-only",
        action="store_true",
        help="Never touch the network; raise ReplayMiss on any fixture miss (make eval-replay's contract: no API key, $0, deterministic).",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="Run only this case_id. Repeatable. Default: every runnable case in the corpus.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Where to write records.json and per-case JSON. Default: eval/runs/<UTC timestamp>/",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=None,
        help=f"Fixture cache directory. Default: {DEFAULT_FIXTURE_DIR}",
    )
    args = parser.parse_args()

    manifest = load_manifest()
    case_ids = args.cases if args.cases else discover_case_ids(manifest)
    documented_gap_ids = [cid for cid, c in manifest["cases"].items() if c.get("category") == "documented_gap"]

    clients = build_clients()
    fixtures = FixtureCache(args.fixtures_dir) if args.fixtures_dir else FixtureCache()

    out_dir = args.out_dir or (RUNS_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

    t0 = time.monotonic()
    records = run_corpus(case_ids, clients=clients, fixtures=fixtures, replay_only=args.replay_only)
    elapsed_s = time.monotonic() - t0

    records_path = persist(
        records, out_dir=out_dir, manifest=manifest, replay_only=args.replay_only, documented_gap_ids=documented_gap_ids
    )

    error_count = sum(1 for r in records if r.verify_state == "error")
    parity_fail_count = sum(1 for r in records if r.stored_parity_ok is False)
    print(f"Ran {len(records)} case(s) in {elapsed_s:.1f}s -> {records_path}")
    if documented_gap_ids:
        print(f"Skipped {len(documented_gap_ids)} documented_gap case(s): {documented_gap_ids}")
    if parity_fail_count:
        print(f"WARNING: {parity_fail_count} case(s) failed stored-check-result parity -- corpus may be stale")
    if error_count:
        print(f"WARNING: {error_count} case(s) raised and were recorded as verify_state=error -- see records.json")


if __name__ == "__main__":
    main()
