# Phase 4 — AI layer, grounding, and first real numbers

**Status: BUILT AND MEASURED, full 50-case corpus, thresholds not yet met.** All three
Gemini-shaped reasoning jobs exist with enforced JSON schemas, `desk/reason/fallback.py`
implements the fixture-replay-then-live-then-Ollama-then-deterministic cascade end to end,
`desk/ground/validator.py` rejects every deliberately ungrounded output thrown at it in 12 unit
tests, and `eval/run.py` + `eval/metrics.py` + `eval/report.py` produced two honest reports: the
4-case smoke run below (`eval/runs/smoke_1/report.md`) written while the pipeline was still being
verified, and the real full-corpus run (`eval/runs/full_corpus_live_1/report.md`,
`docs/MEASUREMENTS.md`) once it finished. **The full-corpus run is complete and its numbers are
published in `docs/MEASUREMENTS.md`. Root-cause accuracy (25.0%) and injection resistance on the
one live-path adversarial case (0%) both failed their §23 thresholds** — a real, disclosed
result, traced to a specific, fixable defect (the deterministic tie-break, see below), not hidden
or re-run until it looked better. 127 tests pass across the whole repo (105 from Phases 0-3 + 22
new: 12 in `tests/ground/test_validator.py`, 8 in `tests/reason/test_fallback.py`, 2 in
`tests/reason/test_replay_determinism.py`).

**This file documents the smoke run and what was built during the phase; `docs/MEASUREMENTS.md`
is the authoritative full-corpus result and the actual §28 MVP-cutoff deliverable.** Everything
below this point was written before the full-corpus run finished and is preserved as-is because
its per-case findings (the tie-break bug, the Job A fixture-coverage variability, the
Docker/Ollama memory-pressure diagnosis) all turned out to directly explain the full-corpus
result once it landed — read `docs/MEASUREMENTS.md` first for the headline numbers, then this
file for how they were diagnosed.

**A note on how this file's numbers were arrived at.** The smoke run was regenerated once,
deliberately, partway through writing this document, because an earlier version of this section
cited a scratchpad-only run (`smoke_report.md`, never committed to the repo) whose exact figures
turned out not to match a fresh run of the identical 4 cases — see "Run-to-run tier variability"
below. Every number and per-case claim in this file now comes from the one run that is actually
on disk at `eval/runs/smoke_1/{records.json,metrics.json,report.md}` and reproducible by the
Verification section's commands, not from memory of an earlier run.

**Full-corpus accuracy, which an earlier version of this section could not yet give honestly, is
now published.** The 4-case smoke run below is not a claim about system quality, only a claim
that the pipeline runs correctly end to end. The full run against all 50 executable cases
(`corpus/MANIFEST.json` has 51 entries; `sha1_signature_downgrade` is the one `documented_gap`
case `eval/run.py` excludes, matching Phase 3's own accounting) has since completed; its real
numbers are in `docs/MEASUREMENTS.md`, not here — this file documents what was built and how the
smoke run's findings were diagnosed, not the final headline metrics.

## Environment constraint: no `GEMINI_API_KEY`, every live call went to local qwen3:1.7b

No Gemini API key is configured in this development environment. `desk/reason/client.py`'s
`build_clients()` (called from `eval/run.py`) therefore returns a client list where
`GeminiClient` is either absent or raises `ProviderUnavailable` immediately, and every live
call in every run to date — the smoke run and the in-progress full-corpus run alike — has gone
through the local Ollama fallback tier running `qwen3:1.7b`. This is a real, disclosed
limitation of the numbers in `eval/runs/smoke_1/report.md` and (eventually)
`docs/MEASUREMENTS.md`: they
measure the local-model tier of the cascade, not Gemini. The architecture and the fallback
mechanism are exercised and correct regardless of which tier answers; the prose-quality and
accuracy numbers specifically should be read as "what the free local fallback achieves," and
that caveat is repeated in `eval/report.py`'s own rendered output next to the tier-usage and
cost tables rather than only stated here once.

## The qwen3:1.7b fixture-coverage picture, verified case by case rather than assumed

Ground truth from `eval/runs/smoke_1/records.json`, read directly per case rather than taken
from the rendered report's aggregate tables (fixtures are additive-only and shared with the
concurrently-running full-corpus background job, so this reflects what happened to be true of
this one run, not a permanent property of any case):

| Case | Job A | Job B | Job C | What that means |
|---|---|---|---|---|
| `cert_expired` | fixture hit | fixture hit | miss → **deterministic** | `render_deterministic_job_c` fires; final root cause `SAML-SIG-01`, **wrong** (expected `SAML-CERT-01`) — see the tie-break note below |
| `clock_skew` | miss → **deterministic** | fixture hit | miss → **deterministic** | Both Job A and Job C fell all the way through; final root cause `SAML-SIG-01`, **wrong** (expected `SAML-SKEW-01`) |
| `duplicate_role_attributes` | miss → **deterministic** | n/a (no gaps once `verify_state == ok`) | miss → **deterministic** | Final root cause `SAML-SIG-01`, **wrong** (expected the `review_required` `SAML-ATTR-01` finding) — the deterministic template still lists `SAML-ATTR-01` as one of `claims[]`, it just isn't picked as `root_cause` |
| `negative_control` | live hit, tier `ollama` | n/a (`verify_state` never reaches `ok`) | n/a | The one Job A call that actually reached qwen3:1.7b live and returned a schema-valid parse this run; correctly reports no root cause either way |

This was read straight out of each case's `job_a`/`job_c`/`tier_used` fields — no probing or
inference needed once the record exists. Every one of the three "normal" cases in this run
resolved through `render_deterministic_job_c`, and every one of them picked `SAML-SIG-01` as
`root_cause`, which is wrong in all three. That is the tie-break limitation described below, not
three independent failures.

**Run-to-run tier variability, disclosed rather than smoothed over.** An earlier, scratchpad-only
run of these same 4 cases (never committed to the repo, and since discarded) showed a
meaningfully different tier picture: 3 of 4 Job A calls hit a fixture instead of 1, and
`clock_skew`'s and `duplicate_role_attributes`'s Job C calls hit fixtures (then, in `clock_skew`'s
case, got rejected by the grounding validator) instead of falling to deterministic. Both runs
called the same local Ollama daemon; this run happened while the full-corpus background job
(`eval/runs/full_corpus_live_1`) was also issuing live `qwen3:1.7b` calls concurrently, which is
the most likely reason more live attempts here failed or timed out and fell through — the
fallback cascade's own job (see T7 in the threat model) is exactly to keep producing a verdict
when that happens, and it did. The honest conclusion is not that either run is "the real
numbers" — it's that **qwen3:1.7b as run in this environment is not reliable enough for a single
live pass to be reproducible tier-for-tier**, which is precisely why the plan's §23 calls for
`k=3` repeats with a reported disagreement rate on any real headline claim, not a single run.
This file cites only the one run that is actually committed to the repo and reproducible via the
Verification section below; nothing here should be read as "the" qwen3:1.7b behavior, only as
what this one run did.

Separately, `tests/reason/test_replay_determinism.py`'s case selection was originally guessed
from a misremembered aggregate `tier_usage` total rather than checked directly, and picked two
cases that turned out not to be fully fixture-covered. The real three fully-covered cases (all
three jobs, every prompt) turned out to be `assertion_expired`, `assertion_expired__adv_s4_obfuscated`,
and `broken_signature__non_native`, found by iterating every case ID in the manifest and checking
`tier_used == "fixture"` on every job actually invoked. The test file's docstring documents this
correction directly, in the same spirit as this project's other self-corrected records (Phase 3's
`cert_rotation` cascade fix).

**Likely cause of the Job A misses, named honestly rather than left unexplained.**
`corpus/cases/*/narrative.json` is not part of the checksummed artifact set in
`corpus/MANIFEST.json` (only `saml_response.xml`, `label.json`, and `login.har` are hashed
there). `render_narrative()` in `harness/generate.py` is a deterministic template render over
`FAULT_NARRATIVE_FACTS`, not a live call, so identical inputs always produce identical text —
but if the narrative *facts* for a given fault were edited after a fixture was first recorded
against the old narrative text, the prompt hash changes and the old fixture becomes orphaned
(still on disk, silently unreachable) while the current narrative has no matching entry. All
four `narrative.json` files inspected share one mtime, meaning they were rewritten together in
a single `harness/generate.py` invocation; `cert_expired`'s Job A fixture happening to survive
that regeneration while `clock_skew`'s and `duplicate_role_attributes`'s did not is consistent
with only some entries in `FAULT_NARRATIVE_FACTS` having been edited since those fixtures were
first recorded. This is stated as the consistent, evidence-backed explanation, not a certainty
— the exact edit history was not traced further. The actionable finding either way: **narrative
text is not manifest-checksummed, so a corpus regeneration can silently invalidate recorded
fixtures for any case whose narrative changed, without any integrity check catching it.** See
"Known, named limitations" below.

## The `test_replay_determinism.py` case-selection bug, as a methodology lesson

The bug itself: the test's `FULLY_FIXTURE_COVERED_CASE_IDS` was written from a remembered
aggregate number rather than a direct check against `fixtures/`. The fix: a ground-truth probe
(`run_corpus([case_id], ..., replay_only=True)` per case, catching `ReplayMiss` and checking
every returned job's `tier_used`) that can be re-run any time `fixtures/` changes rather than
trusting a cached mental model of it. The test file's own docstring now documents both the
mistake and the correction technique, matching this project's established habit of writing
down its own errors rather than quietly fixing them (Phase 1's several corrections, Phase 3's
`cert_rotation` cascade note). Re-run this probe, don't hand-edit the constant, if `fixtures/`
grows.

## Docker-hosted Ollama: what "the Docker VM's memory pressure" actually meant

`desk/reason/client.py`'s `OllamaClient` docstring notes it was "confirmed working end-to-end
... once the Docker VM's memory pressure was resolved." Verified directly against this repo's
own `compose.yaml`: it defines exactly two services, `keycloak-db` and `keycloak` (plus their
Postgres volume) — **no `ollama` service exists in this project's Compose stack.** Ollama runs
natively on the host and is reached at `http://localhost:11434`, entirely outside Docker. The
memory pressure was not this project competing with itself; it was the unrelated
`mcp-detect-wazuh.*` containers (from a different repo, left running on the same machine)
competing with Ollama for RAM on Docker Desktop's shared Linux VM on macOS, since Docker
Desktop's VM has a fixed memory ceiling regardless of which containers are using it. Stopping
those three containers is what resolved it. They remain stopped for the duration of Phase 4 and
must stay stopped, or `qwen3:1.7b` calls in this project start failing again for a reason that
has nothing to do with this project's own code.

## Deterministic-template tie-break, injection-path coverage, and the metric split

- **The deterministic fallback's tie-break limitation — confirmed directly in code, not just
  observed in output.** `render_deterministic_job_c` (`desk/reason/jobs.py`) picks
  `next((r for r in notable if r.assurance == Assurance.FAILED), notable[0])` — the first `FAILED`
  check in `run.results` list order, preferred over any `REVIEW_REQUIRED` check. It renders every
  `FAILED`/`REVIEW_REQUIRED` row into `claims[]` (so the real finding is never silently dropped),
  but `root_cause` itself is only ever the first `FAILED` row. In this run, `SAML-SIG-01` is
  apparently a `FAILED` check that sorts earlier than the actually-relevant check
  (`SAML-CERT-01`, `SAML-SKEW-01`, `SAML-ATTR-01`) in all three normal-stratum cases, so all three
  land on the same wrong root cause via the deterministic tier. This is a named, accepted
  limitation of the deterministic tier, not a bug in the sense of doing something other than what
  it says it does — but it is a real accuracy cost, and it is the direct cause of this run's 0%
  root-cause accuracy and 0% conflicting-handling correctness (see `eval/runs/smoke_1/report.md`).
  It only bites when Job C falls all the way to deterministic; a case where the live tier answers
  is not subject to this specific failure mode (though it can of course be wrong in other ways).
- **Injection-path coverage is reported split, not pooled.** `eval/runs/smoke_1/report.md`'s
  injection section separates S3 (context manipulation via the narrative — a real path into a
  model prompt) from S1/S2/S4 (direct override, persona hijack, obfuscated — payload targets an
  artifact/location no job currently reads), because pooling all four into one resistance
  number would silently count three structural free passes as demonstrated resistance. The
  4-case smoke corpus has n=0 adversarial cases in either bucket; the full 50-case run will be
  the first one with real n here.
- **The corrected ambiguous/conflicting metric split.** `eval/metrics.py`'s module docstring
  records the finding that the original plan (§23) treated ambiguous and conflicting as one
  "should refuse" metric, which the corpus's own label data contradicts:
  `duplicate_role_attributes` (the one `conflicting` case) has a non-null
  `expected_root_cause` under `review_required`, not a refusal. Scoring it against "should
  refuse" would mark the corpus's own correct answer wrong, so refusal correctness and
  conflicting-handling correctness are two separate metrics. The same finding independently
  surfaced at the grounding layer (`desk/ground/validator.py`'s `_LEGAL_ROOT_CAUSE_STATES`,
  exercised directly by `test_review_required_root_cause_is_a_legal_diagnosis` in
  `tests/ground/test_validator.py`).

## Known, named limitations carried into this phase (not fixed here, not hidden)

- **`corpus/MANIFEST.json` does not checksum `narrative.json`.** Only `saml_response.xml`,
  `label.json`, and `login.har` are hashed per case. Prompts for Jobs A and B are built from
  narrative text, so a corpus regeneration can silently change those prompts (and therefore
  invalidate recorded fixtures) without the manifest's own integrity check noticing. This is the
  most concrete, actionable gap found this phase and is not fixed here — fixing it means
  deciding whether narrative text should be manifest-checksummed like the other artifacts or
  deliberately excluded because it is allowed to vary (e.g. across the five narrative
  registers), which is a corpus-design decision, not a one-line patch.
- **No `Makefile` exists yet.** The plan's `make eval-replay` / `make demo` / `make chaos`
  language describes Phase 5-6 deliverables. Every command in this phase's Verification section
  below is a direct `.venv/bin/python3` / `pytest` invocation, matching Phase 3's own pattern —
  not a gap introduced this phase, just not yet true that the plan's exact reproduction command
  works today.
- **All live numbers to date are qwen3:1.7b-only** (see above) — no Gemini comparison exists
  yet. The plan's §29 "could-have" Gemini-vs-Ollama-vs-local comparison table has not been
  attempted.
- **The full 50-case run has completed; see `docs/MEASUREMENTS.md` for the real headline
  figures.** They did not meet the plan's §23 thresholds (25.0% root-cause accuracy against an
  85% target, 0% injection resistance on the one live-path adversarial case), both traced to the
  deterministic tie-break bug documented above and, for the injection case, to the same failure
  mode being indistinguishable in this architecture from a successful injection. Fixing the
  tie-break is the single highest-leverage next step and was deliberately left for a future phase
  rather than patched in to improve the reported number after the fact.
- **This run never reached Gemini.** No `GEMINI_API_KEY` was configured for the full-corpus run
  either, so every live call went to local `qwen3:1.7b`, and it was a single pass rather than the
  plan's `k=3` repeats. Both are named as open gaps in `docs/MEASUREMENTS.md` rather than silently
  treated as good enough.
- **`desk/policy` does not exist yet** (Phase 5). Refusal correctness is scored purely on
  `final_root_cause is None`; there is no computed disposition to check
  `expected_disposition` against.

## Verification

```
.venv/bin/python3 -m pytest tests/ground/ -v          # 12 passed
.venv/bin/python3 -m pytest tests/reason/ -v           # 10 passed
.venv/bin/python3 -m pytest -q                         # full repo: 127 passed

# Smoke run against the 4 cases with the richest labels (cert_expired, clock_skew,
# duplicate_role_attributes, negative_control), live tier = qwen3:1.7b:
.venv/bin/python3 -m eval.run \
  --case cert_expired --case clock_skew \
  --case duplicate_role_attributes --case negative_control \
  --out-dir eval/runs/smoke_1
.venv/bin/python3 -m eval.report eval/runs/smoke_1/records.json \
  --out eval/runs/smoke_1/report.md --metrics-out eval/runs/smoke_1/metrics.json

# Replay-only re-run of the same 4 cases: no network, no API key, byte-identical output
.venv/bin/python3 -m eval.run --replay-only \
  --case cert_expired --case clock_skew \
  --case duplicate_role_attributes --case negative_control \
  --out-dir eval/runs/smoke_1_replay
```

`tests/ground/test_validator.py` checks: a genuinely grounded output is accepted; a
`review_required` root cause is accepted as a legal diagnosis (the `duplicate_role_attributes`
finding, replicated directly); and each of empty claims, an unknown check ID, a state
contradiction, an uncited check reference in prose, a root cause pointing at a passing check,
and a root cause pointing at a gap (`not_verified`) are all rejected, with multiple violations
on one output all reported rather than only the first. `tests/reason/test_fallback.py` forces
every tier of the cascade (fixture hit, fixture priority ordering, live success on the first
client, `ProviderUnavailable` skipping straight to the next client with no retry,
`ProviderError` retried up to budget then falling through, recovery within the retry budget,
every tier exhausted falling to deterministic, `record_fixtures=False` not persisting a live
success) plus both `replay_only` behaviors (loud `ReplayMiss` on a genuine miss, a real fixture
still hit). `tests/reason/test_replay_determinism.py` runs the three fully-fixture-covered
cases twice through `replay_only=True` and asserts byte-identical JSON output with zero live
client calls, plus that every job actually reached the fixture tier rather than falling through
to a trivially-self-agreeing deterministic render.

## Decision

Phase 4 exit criteria (plan §27, §28 MVP cutoff) are **built and measured, thresholds not met.**
Every architectural piece the plan called for exists, is self-tested, and is verified against a
live model end to end: schema-bound reasoning across all three jobs, the fixture-replay-then-
live-then-deterministic fallback cascade, and a grounding validator that actually rejects a
meaningful share (25%) of real model output rather than never firing. The full 50-case run
completed and `docs/MEASUREMENTS.md` publishes real accuracy, refusal-correctness,
injection-resistance, leakage, and cost numbers across the whole corpus, exactly as §28 requires
— but two of those numbers (root-cause accuracy, injection resistance on the one live-path
adversarial case) fell well short of the plan's own §23 thresholds, and the run used the local
qwen3:1.7b fallback rather than Gemini and was a single pass rather than `k=3` repeats.

**Whether this counts as "MVP cutoff met" depends on what §28 actually promised.** It promised
*published, reproducible numbers*, not *numbers that clear every threshold* — and the plan's own
§23 says explicitly to publish a bad number rather than tune it away. Read that way, Phase 4 is
complete: the evidence is real, honestly reported, and the shortfall is traced to one identified,
fixable defect rather than left as an unexplained mystery. Read the other way, the system is not
yet accurate enough to be the finished product any of Phases 5-6 will demo. Both readings are
recorded here rather than only the flattering one. Next: decide whether to fix the
`render_deterministic_job_c` tie-break before proceeding to Phase 5, or carry the known defect
forward and fix it later — then commit Phase 4 as a whole either way, since the code, tests, and
honestly-reported numbers are all real and complete as of this run.
