# Phase 4 — AI layer, grounding, and first real numbers

**Read "Update, 2026-08-17" below before trusting any specific number in this file's opening
status block.** The tie-break bug that produced the 25.0%/0% figures below is fixed; current
numbers (65.0%/90.0%, and a proven-reproducible replay) are in `docs/MEASUREMENTS.md`.

**Status: BUILT AND MEASURED, full 50-case corpus, thresholds not yet met (see the 2026-08-17
update below for what changed since).** All three
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

## Update, 2026-08-17: tie-break fixed, two reproducibility bugs found and fixed, new numbers

Everything from here down was written 2026-08-16 or earlier and describes the deterministic
tie-break bug and the run-to-run tier variability as open, unfixed problems. As of 2026-08-17 both
are fixed, and the full-corpus numbers this file's "Known, named limitations" section points at
are stale. Current numbers live in `docs/MEASUREMENTS.md`
(`eval/runs/20260817T044253Z/`, superseding `full_corpus_live_1`). This section is the update;
the rest of the file is kept as-is below it, in the same spirit as the corrections already
layered into this file's opening section — the diagnostic reasoning that led here is still worth
reading, it just no longer describes the current state of the code.

**0. Corpus ground-truth incident: a shared-baseline certificate went stale and contaminated
signature checks across roughly 30 cases, silently.** `harness/capture/idp-cert.txt` pins the
certificate the SP trusts. `harness/capture/captured/saml_response.xml` is the one real, untouched
"nothing is wrong" baseline that every `CONTEXT_MISMATCH` case and every `ARTIFACT_MUTATION` case
whose mutation doesn't touch the signed content all reuse as their starting bytes
(`baseline.load_good_saml_response()`). At some point before 2026-08-16, the Keycloak realm's
signing key was rotated in order to build `cert_rotation`'s own fault artifacts, the shared
baseline was re-captured *after* that rotation and signed with the new key, and `idp-cert.txt` was
never refreshed to match. Every case built from the shared baseline — roughly 30 of the corpus's 50
— then silently failed `SAML-SIG-01`, `SAML-SIG-02`, and `SAML-CERT-02` as an artifact of that
mismatch, unrelated to whatever fault each case actually existed to test.

This went undetected because `harness/generate.py`'s `verify_and_selftest()` only ever checked that
each case's own declared `expected_states` were *present* — it never checked that nothing *else*
unexpectedly failed. A case whose fault has nothing to do with signatures could pick up two
spurious `SAML-SIG-*` failures and the self-test would still pass, because it never looked outside
the one check_id list the case declared.

**The fix has two parts.** First, a matched cert/response pair was regenerated so the shared
baseline is internally consistent again (`harness/capture/idp-cert.txt` and every case's
`check_results.json`/`context.json` derived from the shared baseline were regenerated as a result —
this is the source of the corpus-wide diff committed alongside this update). Second,
`verify_and_selftest()` now runs a second loop after its existing presence check: any check *not*
named in the case's `expected_states` that comes back `failed` or `review_required` is a hard error,
unless it is named in a new `KNOWN_BASELINE_NOISE` allowlist. That allowlist currently has exactly
one entry, `{"SAML-ATTR-01": "review_required"}` — a genuine, real finding (Keycloak's default SAML
role-list mapper emits one `<Attribute Name="Role">` element per role value instead of one element
with multiple `<AttributeValue>` children, which `SAML-ATTR-01` correctly flags as a duplicate
Attribute Name) that belongs in the corpus honestly labeled as baseline behavior, not as a fault
anyone injected. The allowlist is intentionally an explicit, reviewed list rather than a silent
skip, so a future contamination of the shared baseline fails loudly again instead of freezing
silently a second time.

**Consequence for the numbers below.** This fix and the tie-break fix (item 1) both landed before
the `20260817T044253Z` run and are confounded with each other: item 0 changed the underlying
`check_results` for about 30 cases before item 1's selection logic ever ran over them. No isolated
measurement of either fix's individual contribution exists. See `docs/MEASUREMENTS.md`'s "Why this
run supersedes the old one" for the honest combined framing — the old, superseded
`full_corpus_live_1` run was generated against the *contaminated* corpus (confirmed directly:
its `metrics.json` records `"deterministic_actual": "SAML-SIG-01"` for `assertion_expired`, which
requires the now-corrected spurious `SAML-SIG-01` failure to have been present at generation time).

**0a. A related but separate fix, same corpus regeneration: the S4 adversarial payload's delivery
mechanism was breaking the signature it was supposed to leave untouched.** `harness/adversarial.py`'s
S4 payload (`assertion_expired__adv_s4_obfuscated`) originally used `mutations.add_attribute()` to
hide a base64-encoded instruction inside a new `FriendlyName` value on a real signed
`saml:Attribute` element. XML canonicalization does not strip added attributes, so that mutation
changed what the signature covered and broke `SAML-SIG-01` as a mechanical side effect of the
mutation technique, independent of the payload content — directly contradicting this module's own
stated invariant (its docstring) that an injection payload must land on a fault's already-correct
check results. Fixed with a new primitive, `mutations.insert_xml_comment_near()`, which inserts the
payload as an XML comment immediately after the target element instead of as an attribute on it;
canonicalization strips comments before the digest is computed, so the signature is untouched. This
regenerated `assertion_expired__adv_s4_obfuscated`'s `saml_response.xml` and `label.json` alongside
the rest of the corpus. The S4 grounding-rejection finding written up in `docs/MEASUREMENTS.md`
(rejected for `uncited_check_reference`, not for engaging with the injected instruction) is read
directly from the post-fix `20260817T044253Z` run and is accurate as stated.

**1. The deterministic tie-break bug is fixed, and fixed in the place that actually mattered.**
The original fix attempt patched only `render_deterministic_job_c` (`desk/reason/jobs.py`) and
left `eval/metrics.py`'s deterministic-only baseline computation with its own separate, still-buggy
copy of the same rule — the two silently disagreed, and the eval's headline "deterministic-only
accuracy" number never moved even after the renderer itself was corrected. The real fix extracts a
single shared function, `pick_root_cause_check_id()`, that both `render_deterministic_job_c` and
`eval/metrics.py` call. Its rule: prefer a `failed` check over a `review_required` one; among
`failed` checks, prefer a non-signature check over a `SAML-SIG-*` one (a signature check failing
alongside something more specific is usually that thing's side effect, not an independent
finding); within whichever pool wins, use the checks' registration order for a stable pick.
Combined with item 0 above, this moved the deterministic-only baseline from 12.5% (5/40) to 90.0%
(36/40) and the AI-assisted number from 25.0% to 65.0% — see `docs/MEASUREMENTS.md` for the full
breakdown of what the remaining 25-point AI-assisted gap is actually made of (mostly grounding
correctly declining to guess, plus a specific, repeatable model bias toward citing `SAML-SIG-01`).

**2. The `ReplayMiss` crash on `--replay-only` is fixed.** Before this fix, `--replay-only` raised
on any case whose live run had legitimately exhausted every configured client and fallen through
to the deterministic template, because replay mode had no way to distinguish "this prompt was
never run live" (a genuine gap, should raise) from "this prompt was run live and correctly fell
through to deterministic" (should not raise). The fix adds a deterministic-fallback marker:
`FixtureCache.mark_deterministic()` (`desk/reason/fixtures.py`) records, alongside the fixture
namespace but in a separate `_deterministic/` subdirectory (so nothing that globs `fixtures/*.json`
expecting a `ModelResponse`-shaped record, like the secret-leakage scanner, mistakes a marker for
one), that a live run tried every client for an exact prompt and none answered.
`desk/reason/fallback.py`'s `run_with_fallback()` checks `is_marked_deterministic()` before raising
`ReplayMiss`, so replay mode can legitimately terminate in the deterministic template exactly as
the live run did.

**3. Two further reproducibility bugs, found while proving the fixes above actually work, and
fixed the same day:**

- **`OllamaClient.generate()` (`desk/reason/client.py`) set `temperature: 0` but never passed a
  `seed`.** Ollama draws a new seed per request when none is pinned, so the identical prompt run
  twice, even at temperature 0, could legitimately sample two different outputs — this is what the
  "Run-to-run tier variability" section below was actually observing, not an inherent property of
  local models that has to be lived with. Fixed by adding `"seed": 0` to the request options.
- **`FixtureCache.put()` (`desk/reason/fixtures.py`) unconditionally overwrote any existing
  fixture.** Combined with the seed bug, a later, unrelated live call to a prompt that already had
  a recorded fixture could silently replace the answer backing a previously published number with
  a different, unreviewed one — this is the exact mechanism behind the `assertion_expired` /
  `assertion_expired__adv_s4_obfuscated` fixture-collision finding written up in
  `docs/MEASUREMENTS.md`. Fixed by making `put()` write-once: the first real response recorded for
  a given prompt+model+schema key stays authoritative, and a later call to the same key is a no-op.

**Proof, not just a claim.** A fresh full-corpus live run and a fresh full-corpus `--replay-only`
run were diffed field-by-field across all 56 keys in `metrics.json` and matched exactly except the
two fields that are supposed to differ (`generated_from`'s timestamp, and `replay_only` itself).
That is the concrete evidence that `make eval-replay` (plan §23/§36 verification step 5) now
actually reproduces published numbers offline, which was not true before these fixes. All 135
tests pass: the 127 already committed (105 from Phases 0-3 + 22 from the original Phase 4 work,
including `test_fallback.py`'s 8 replay-marker tests for the pre-existing `ReplayMiss` fix) plus 8
new this session in a new file, `tests/reason/test_jobs.py`, covering `pick_root_cause_check_id()`
and the tie-break's demotion rule directly (see item 1 above) — confirmed by diffing collected
test counts with and without this session's changes stashed, not assumed. Zero regressions from
any of this session's fixes.

**What this changes about the "Known, named limitations" and "Decision" sections below.** The
tie-break bullet under "Known, named limitations" and the corresponding paragraph in "Decision"
describe the pre-fix state (25.0%/12.5%, tie-break named as the single fixable cause, not yet
fixed) and are left as written below rather than edited in place, because they are an accurate
record of what was true on 2026-08-16. Read them as history. `docs/MEASUREMENTS.md` is the current
source of truth for headline numbers going forward.

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
