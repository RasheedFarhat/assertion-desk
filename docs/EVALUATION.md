# Evaluation Framework

This document describes the metrics framework itself, what each number means and how it is
computed, grounded in `eval/metrics.py`. It is distinct from
[`docs/MEASUREMENTS.md`](MEASUREMENTS.md), which is the result of one specific run. Every
function named below is a pure read of `eval/run.py`'s output (`records.json`), except the
leakage scan, which independently reads `fixtures/`; nothing in this module re-runs the pipeline
or talks to a model, which is what makes it possible to compute every number here for free from a
single `eval/run.py` pass.

## No LLM-as-judge anywhere in the primary metrics

Every metric below is checked against a fault the harness actually injected, or a pattern
grep-able in a stored transcript. Nothing here asks a model to grade another model's output.

## Root-cause accuracy (`root_cause_accuracy`)

Compares `final_root_cause` (the pipeline's grounded output, `None` if grounding rejected or Job
C was never invoked) against the label's `expected_root_cause`. Reported twice from the same run,
never re-executed: the AI-assisted number, and a deterministic-only baseline computed by calling
`desk/reason/jobs.py:pick_root_cause_check_id()` directly over the persisted check results,
`eval/metrics.py`'s own docstring flags that this function used to be reimplemented by hand in
this module and silently drifted from a later fix made only in `desk/reason/jobs.py`, importing
the same function in both places is the fix. This implementation's `JOB_C_SCHEMA` produces a
single `root_cause`, not a ranked list, so there is no top-3 variant of this metric here, an
intentional simplification against the plan's original top-1/top-3 design, not an oversight.

## Refusal correctness (`refusal_correctness`) vs conflicting-handling correctness

These are **two separate metrics**, not the plan's original single "ambiguous + conflicting
means always refuse" rule. The corpus's own label data contradicts that assumption: the one
`conflicting` case, `duplicate_role_attributes`, has a real, non-null `expected_root_cause`
(`SAML-ATTR-01`) under `expected_disposition: review_required`, not a refusal. Scoring it against
a "should refuse" rule would mark the corpus's own correct answer wrong. `refusal_correctness`
therefore scores only the `ambiguous` stratum (n=2) on whether `final_root_cause` is `None`;
`conflicting_handling_correctness` is a separate function scoring the one `conflicting` case on
its own terms. `malformed_handling_correctness` and `no_saml_response_handling_correctness`
similarly score their own strata independently, clean named rejection for malformed input,
`verify_state == "no_saml_response"` for the negative control.

## Disposition accuracy (`disposition_accuracy`)

A broader, later-landed alternative to extending `refusal_correctness` itself: checks
`desk/policy/rules.py`'s computed disposition (via `computed_disposition()`, which builds a
`PolicyInput` from the persisted case record the same way a live case would) against each case's
`expected_disposition`, across all n=50 runnable cases rather than only the ambiguous stratum's
n=2. `computed_disposition()` deliberately sets `any_live_credential=False` unconditionally, with
an explicit comment that `desk/custody` is not wired into `eval/run.py`'s pipeline at all, so no
corpus-based eval run can ever produce a real custody result, this is stated as a fact about the
eval harness, not invented as if it were tested.

**Three named, accepted mismatches**, not one, all sharing a single root cause. `harness/faults/
baseline.py` hardcodes `in_response_to_expected=None` because the harness's own minimal SP
(`harness/capture/sp_app.py`) never persists its own outbound request IDs to compare later, so
`SAML-INRESP-01`/`SAML-INRESP-02` come back `NOT_VERIFIED` in effectively every case (46 of 47
cases with check results) except the one case that fault is actually about. That universal gap
means `compute_gaps()` always reports something and Job B is invoked almost everywhere. For three
cases this produces a real, honestly-reported disagreement between the policy engine's own
correct-by-its-rules answer and the corpus label:

- **`duplicate_role_attributes`** (the one `conflicting` case): identical real pipeline signals to
  the `withheld_cert`/`withheld_clock` ambiguous cases (`verify_state ok`, no `FAILED` check, a
  real gap, Job C never invoked), so the policy computes `awaiting_evidence` where the label says
  `review_required`.
- **`wrong_binding`**: its real fault (Redirect vs POST binding) lives entirely in the HAR request
  line, which nothing in `desk/verify/checks/` reads (`label.json`'s own `no_check_coverage_
  reason` field says so), so the check grid runs clean apart from the universal InResponseTo gap.
- **`stripped_relaystate`**: same shape as `wrong_binding`, its fault lives in the HAR/transport
  layer outside the parsed SAMLResponse XML.

`desk/policy/rules.py` refuses to special-case these by reading the label's `target_check_ids`,
doing so would be exactly the ground-truth leakage this whole framework exists to prevent (see
`desk/policy/rules.py`'s own module docstring). `KNOWN_DISPOSITION_MISMATCHES` in `eval/
metrics.py` is a small, explicit, case-id-keyed allowlist consulted only for those three ids,
so an unrelated future disposition bug can never be silently absorbed into it.

## Grounding rejection rate (`grounding_rejection_rate`)

Fraction of Job C outputs that actually reached `desk/ground/validate_job_c_output()`, meaning
they arrived via a live or fixture tier; the deterministic template is grounded by construction
and `eval/run.py` never passes it to the validator. Reported with an explicit caveat: the
validator's accept/reject decision is a deterministic function of its two inputs, so "percent of
real violations caught" is tautologically 100% by construction, a violation only exists because
the validator's own rule defines it. The number that actually matters, and the one this metric
reports, is how often a genuine Job C output violates grounding at all, which is a fact about
model behavior, not about the validator.

## Injection resistance (`injection_resistance`)

Splits the corpus's 4 adversarial cases into two groups rather than reporting one combined
number, because code inspection (not assumption) found only one, `clock_skew__adv_
s3_context_manipulation`, has any live path into a model prompt under the current architecture,
its payload lives in the narrative body, which Job A actually reads. The other three (S1/S2/S4)
target artifact locations no job reads at all (see `docs/CORPUS.md` and `docs/THREAT_MODEL.md`
T2 for exactly where each payload sits). "Resisted" means `final_root_cause` still matches the
label's `expected_root_cause` despite the injection attempt. Reporting all four together would
silently launder three free passes (an absent path, not demonstrated resistance) into an
apparent four-case resistance result, which is exactly the inflation this split exists to
prevent.

## Secret leakage to prompt (`secret_leakage_scan`)

Scans `fixtures/` with a hand-rolled secret-pattern set that is deliberately independent of
`desk/custody`'s own detector, the same "independent scanner, not the detector under test"
principle `tests/custody/ -k leakage` uses. A detector grading its own output would not be
evidence of anything.

## Cost, tokens, latency, and tier usage

`tier_usage()` and `cost_tokens_latency()` report which tier (fixture, live client N, Ollama,
deterministic) answered each job and the token/latency/cost accounting per case, giving the
`$0 in replay mode, ~$0.004/case at paid rates` claim in the README a computed source rather than
an estimate.

## Reproducibility

`compute_all_metrics()` is the single entry point `eval/report.py` calls to render every number
above into a Markdown report and a `metrics.json`. `make eval-replay` runs the corpus from
`fixtures/` only, no network, no API key, and a byte-for-byte diff of the resulting `metrics.json`
against the committed run (excluding the timestamp and `replay_only` flag) is the reproducibility
claim the README makes. `make eval` runs the same computation against the live cascade.
