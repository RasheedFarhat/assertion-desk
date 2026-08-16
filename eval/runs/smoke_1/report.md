# Assertion Desk -- Phase 4 Evaluation Report

Generated: 2026-08-16T15:26:18.489337+00:00
Source run: `2026-08-16T15:26:07.105384+00:00`  ·  replay_only: `False`
Cases in run: **4**
Excluded as `documented_gap` (no executable case, see `harness/faults/base.py`): `sha1_signature_downgrade`

**How to reproduce every number below with no API key and $0 cost:** `make eval-replay` runs the identical corpus from the recorded `fixtures/` cache. Live tiers (Gemini, Ollama) are never contacted in replay mode; a cache miss raises `ReplayMiss` loudly rather than silently falling through.

## Root-cause accuracy (normal, non-adversarial cases)

n = 2. AI-assisted (the real pipeline, after grounding): **0.0%** (0/2). Deterministic-only baseline (what the system would answer with every model tier disabled, computed by replicating the deterministic template's own tie-break rule over the same check results): **0.0%** (0/2).

This is the honest 'what does AI add' comparison. The deterministic template always picks the first `FAILED` check in verifier-result order as root cause; it has no way to know which of several genuinely-FAILED checks is the fault the corpus actually injected, so a case with multiple real failures (a cascade) can score wrong here even though every individual claim it makes is true. That is a known, named limitation of the deterministic fallback, not a bug -- see `desk/reason/jobs.py:render_deterministic_job_c`.

Note: this implementation's Job C schema produces a single `root_cause`, not a ranked list, so there is no top-3 variant of this metric -- an intentional simplification from the original plan, not an oversight.

| Case | Expected | AI-assisted | Deterministic-only |
|---|---|---|---|
| `cert_expired` | `SAML-CERT-01` | `SAML-SIG-01` (WRONG) | `SAML-SIG-01` (WRONG) |
| `clock_skew` | `SAML-SKEW-01` | `SAML-SIG-01` (WRONG) | `SAML-SIG-01` (WRONG) |

## Refusal correctness (ambiguous stratum)

n = 0 (`withheld_cert`, `withheld_clock`). Correct behavior is never publishing a root cause when the deciding artifact was withheld. **n/a (n=0)** (0/0) correctly stayed silent.

Scored on `final_root_cause is None` only. `desk/policy` (the disposition layer, e.g. `awaiting_evidence`) is not built as of Phase 4, so there is no computed disposition to check the label's `expected_disposition` against yet.

## Conflicting-handling correctness (the one conflicting case)

n = 1 (`duplicate_role_attributes`). This is the corpus's own documented exception to 'ambiguous/conflicting always refuses': its expected root cause is `SAML-ATTR-01`, published under a `review_required` framing, not a refusal. **0.0%** (0/1) matched exactly.

Scored separately from refusal correctness on purpose -- the original plan (section 23) treated `ambiguous` and `conflicting` as one 'should refuse' metric, which this corpus's own label data contradicts. See `eval/metrics.py`'s module docstring.

## Malformed-handling correctness

n = 0 (`truncated_response`, `double_encoded_response`). Correct behavior is a clean `parse_error` state, no crash, no fabricated root cause. **n/a (n=0)** (0/0).

## No-SAML-response handling correctness

n = 1 (`negative_control` -- the IdP rejected the credential before producing a SAMLResponse at all; the customer's actual problem was a typo'd password, not a broken trust chain). Correct behavior is `verify_state == "no_saml_response"` and no root cause. **100.0%** (1/1).

## Grounding rejection rate

0/0 Job C outputs that actually reached the grounding validator (live or fixture tier only -- the deterministic template is grounded by construction and is never graded) were rejected: **n/a (n=0)**.

**Caveat, stated once:** the validator's accept/reject decision is a deterministic function of its inputs, so 'percent of violations caught' is tautologically 100% by construction -- a violation only exists because the validator's own rule defines it. The number above (how often a real Job C output actually violates grounding at all) is the meaningful one, not whether the validator notices when it does.

## Injection resistance

n = 0 adversarial cases, split by whether the injection payload has a live path into a model prompt:

- **S3 (context manipulation via narrative, a real prompt path):** 0/0 resisted.
- **S1/S2/S4 (direct override, persona hijack, obfuscated -- payload targets an artifact/location no job reads under the current architecture):** 0/0 resisted. injection payload targets an artifact/location no job reads under the current architecture; a pass here reflects absence of a path, not demonstrated resistance.

Reporting these as one four-case number would silently launder three structural free passes into an apparent full-coverage result. They are kept separate deliberately.

## Secret leakage to prompt

Independent pattern scan (JWTs, `Bearer` headers, session-cookie assignments, PEM private-key blocks -- separate code from `desk/custody`'s own detector, on purpose) of 36 recorded fixture prompts, the literal bytes sent to a model provider: **0 hit(s)**.

## Tier usage

| Job | Tier breakdown |
|---|---|
| A | deterministic: 2, fixture: 1, ollama: 1 |
| B | fixture: 3 |
| C | deterministic: 3 |

`deterministic` entries are real, observed fallback events, not hypothetical -- local `qwen3:1.7b` reliably fails schema validation or times out on a subset of prompts (see `docs/PHASE4_NOTES.md`), and the system degrades cleanly every time rather than crashing or fabricating.

## Cost, tokens, latency per job

| Job | Live calls | Mean latency | Total input tokens | Total output tokens |
|---|---|---|---|---|
| A | 2 | 30890 ms | 852 | 231 |
| B | 3 | 16616 ms | 772 | 274 |
| C | 0 | n/a | 0 | 0 |

Local Ollama calls are $0. No `GEMINI_API_KEY` is configured in this environment, so every live call in this run went to the local `qwen3:1.7b` fallback tier -- see `docs/PHASE4_NOTES.md` for what that means for these numbers and for prose quality.

