# Assertion Desk

[![CI](https://github.com/RasheedFarhat/assertion-desk/actions/workflows/ci.yml/badge.svg)](https://github.com/RasheedFarhat/assertion-desk/actions/workflows/ci.yml)
[![Eval Replay](https://github.com/RasheedFarhat/assertion-desk/actions/workflows/eval-replay.yml/badge.svg)](https://github.com/RasheedFarhat/assertion-desk/actions/workflows/eval-replay.yml)
[![CodeQL](https://github.com/RasheedFarhat/assertion-desk/actions/workflows/codeql.yml/badge.svg)](https://github.com/RasheedFarhat/assertion-desk/actions/workflows/codeql.yml)
[![gitleaks](https://github.com/RasheedFarhat/assertion-desk/actions/workflows/gitleaks.yml/badge.svg)](https://github.com/RasheedFarhat/assertion-desk/actions/workflows/gitleaks.yml)

A support-triage system for broken enterprise SSO that quarantines the customer's live
credentials before anything reads them, verifies the SAML federation trust chain
deterministically, and will not let an AI assert a fact its verifier did not independently
confirm.

## Why this exists

In October 2023, Okta's support system was breached after customers uploaded HAR files to
support tickets to help diagnose login problems, and an attacker read live session tokens
straight out of those files. A HAR export is still the standard artifact for debugging a
broken SSO integration today, and more than half of enterprise SSO support tickets turn out
to be a plain IdP misconfiguration, a rotated certificate, a mistyped ACS URL, that a
deterministic check can find in milliseconds once the credential-bearing evidence has been
made safe to look at.

Assertion Desk is the support desk built around that order of operations: quarantine first,
verify deterministically, then let a model read the human and write the answer, never the
other way around.

## Measured results

Full corpus (50 executable cases of 51 in `corpus/MANIFEST.json`), run 2026-08-17, no
`GEMINI_API_KEY` configured, so every model call in this run went to the local Ollama
fallback tier (`qwen3:1.7b`), never Gemini. These are honest numbers for the free local
fallback path, not the system's intended Gemini-primary path. Full breakdown, including why
the 65.0% number is what it is, in [`docs/MEASUREMENTS.md`](docs/MEASUREMENTS.md).

| Metric | Threshold | Measured | Met? |
|---|---:|---:|:---:|
| Root-cause accuracy, top-1, AI-assisted (`normal` stratum, n=40) | ≥ 85% | **65.0%** (26/40) | **No** |
| Refusal correctness (`ambiguous` stratum, n=2) | ≥ 90% | **100.0%** (2/2) | Yes |
| Injection resistance, the one case with a genuine live model path (n=1) | 0% outcome change | **100% resisted** (1/1) | Yes, n=1 |
| Secret leakage to prompt, independent scan of 145 recorded outbound prompts | 0 | **0** | Yes |
| Cost per case, this run (fixture cache + local Ollama, no Gemini call occurred) | reported | **$0** | n/a |
| Deterministic-only baseline, same 40 cases, model disabled | reported, not thresholded | **90.0%** (36/40) | n/a |

**The number that matters most here is reported honestly even though it failed:** AI-assisted
root-cause accuracy trails the deterministic-only baseline by 25 points, driven by two named,
disclosed causes, not one undifferentiated bug: the grounding validator correctly declining to
guess (9 of 14 misses) and a specific, repeatable model bias toward citing one particular check
(5 of 14 misses). Neither is hidden or tuned away. See
[`docs/MEASUREMENTS.md`](docs/MEASUREMENTS.md) for the case-by-case breakdown.

Reproduce every number above yourself, no API key, no network, $0:

```
make eval-replay
```

That command runs the full corpus from committed `fixtures/`, writes a fresh report and
`metrics.json`, and a byte-for-byte diff against the committed
`eval/runs/20260817T044253Z/metrics.json` (excluding the timestamp and the `replay_only` flag)
is the reproducibility claim itself.

## 90-second demo

Not recorded yet. `make demo` runs a five-case CLI walkthrough (clean diagnosis, conflicting
evidence, missing evidence, a negative control, and an injection attempt) that covers the same
ground the recording will; see the target's own comment in `Makefile` for the exact case list.
A server-rendered case card with the model-input-transcript toggle already exists behind
`make serve`, so this is a recording task, not a missing feature.

## Architecture

**The verifier decides what is true. The model decides what to say about it.**

```
customer artifact bundle  (UNTRUSTED: prose, HAR, SAMLResponse, IdP metadata)
        │
        ▼
  desk/custody     secret & PII quarantine -> typed placeholders          NO AI
        │          measured: 0 secrets reached 145 outbound prompts
        ▼
  desk/verify      ~20 federation checks -> six-state assurance           NO AI
        │          verified | failed | review_required | not_verified |
        │          not_tested | not_applicable -- absence of evidence
        │          can never produce "verified"
        ▼
  desk/reason      3 schema-bound Gemini calls (Ollama fallback,          AI
        │          fixture replay) -- Job C reads check results and
        │          Job A's structured facts, never the raw artifacts
        ▼
  desk/ground      rejects any model claim citing an unknown check ID     NO AI
        │          or a state the verifier didn't produce
        │          measured: 25% of real model outputs rejected
        ▼
  desk/policy      auto | review | escalate | block                      NO AI
        ▼
  desk/case        state machine, hash-linked trace, Postgres/SQLite
        ▼
  n8n WF1-WF4      webhook intake, human approval, evidence chase,
                   nightly eval report -- orchestration only, never
                   authoritative (the pipeline runs with n8n stopped)
```

The model is never asked for a root cause unless the verifier already produced a `failed`
check to reason about, and every claim it makes downstream of that is cross-checked against a
real check ID and a real assurance state before a human or a customer ever sees it. Remove the
model entirely and the deterministic-only path still answers 90.0% of the `normal` stratum
correctly, which is the honest measure of how much of this problem is actually deterministic.

## What this proves and what it does not

**Proves, with real measurement:** the full pipeline runs end to end across five strata
(normal, ambiguous, conflicting, adversarial, malformed, plus a negative control) with zero
crashes; the custody stage leaked zero secrets into 145 real outbound prompts; the grounding
validator rejects real model output at a meaningful rate (25%) rather than never firing; the
fallback cascade degrades to a working answer whenever a live tier is unavailable; and a live
run and an offline `--replay-only` run of the same corpus now produce byte-for-byte identical
published metrics, verified by an exact field diff.

**Does not prove:** that the system is accurate enough to be useful yet. 65.0% top-1
AI-assisted accuracy against an 85% target is a real, failed threshold. It says nothing about
Gemini's actual accuracy, since no Gemini call occurred in the measured run (no API key was
configured in this environment). It does not establish general injection resistance, four
total adversarial cases and one genuine live model path is a small sample. And it is not a
claim about a real production support system: the corpus's ground truth comes from a fault
harness driving a real, self-hosted Keycloak instance, not from Okta, Entra, or Ping, and
`mocks/itsm/` is a stub, not ServiceNow, Jira, or Zendesk.

## Quickstart

```
git clone https://github.com/RasheedFarhat/assertion-desk.git && cd assertion-desk
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# The reproducibility check: no key, no network, $0.
make eval-replay

# A five-case CLI walkthrough of the same corpus.
make demo

# The server-rendered case card (POST a demo case, then open its /card URL).
make serve

# Full test suite.
make test
```

## ROI calculator

`eval/roi.py` (plan section 24) turns a case count and two timed minutes-per-case figures
into hours and dollars saved per year, with every input printed back before the result. It
has no default for the two inputs that matter most, `--baseline-minutes` and
`--review-minutes`, and refuses to run without them. Those numbers can only come from a real
stopwatch study, which has not been run yet; see [`docs/HUMAN_BASELINE.md`](docs/HUMAN_BASELINE.md)
for the protocol. Every other input (tenant count, ticket volume, the IdP-misconfiguration
share, the fully-loaded hourly cost, the measured $0/case inference cost) has a cited default
and can be overridden:

```
make roi ARGS="--baseline-minutes 45 --review-minutes 5"
```

`make eval` runs the live cascade (Gemini primary if `GEMINI_API_KEY` is set, Ollama fallback,
deterministic-only last resort) instead of replaying fixtures. Corpus regeneration and the
optional n8n/Keycloak/local-model services are behind Docker Compose profiles:

```
docker compose --profile idp up -d              # Keycloak, for corpus regeneration only
docker compose --profile orchestration up -d     # n8n; see n8n/README.md before activating
docker compose --profile local-model up -d       # Ollama, for the fallback tier
```

The committed corpus and fixtures mean none of the above are required to reproduce the
numbers in this README.

## Repository layout

```
desk/         intake, custody, verify, reason, ground, policy, case, api.py
harness/      fault injectors + real Keycloak/Playwright artifact capture
corpus/       frozen, checksummed cases (MANIFEST.json)
fixtures/     recorded model responses for deterministic replay
eval/         run.py, metrics.py, report.py, roi.py
n8n/          four workflow exports (intake, approval, evidence chase, eval report)
mocks/itsm/   a ticket stub -- explicitly not ServiceNow, Jira, or Zendesk
docs/         architecture, AI design, threat model, corpus, evaluation, limitations,
              measurements, and dated phase notes (PHASE0-4)
tests/        one package per desk/eval/harness module
.github/      CI (pytest + corpus-verify), eval-replay diff gate, CodeQL, gitleaks
```

`docs/` holds seven standalone write-ups plus the phase-by-phase build notes:
[`ARCHITECTURE.md`](docs/ARCHITECTURE.md) (module map and data flow),
[`AI_DESIGN.md`](docs/AI_DESIGN.md) (the 10-question justification per model job),
[`THREAT_MODEL.md`](docs/THREAT_MODEL.md) (T1-T10, each with a measured-or-not status),
[`CORPUS.md`](docs/CORPUS.md) (the fault catalogue and how ground truth is established),
[`EVALUATION.md`](docs/EVALUATION.md) (every metric's exact definition),
[`LIMITATIONS.md`](docs/LIMITATIONS.md) (accuracy, scale, and persistence boundaries stated
plainly), [`MEASUREMENTS.md`](docs/MEASUREMENTS.md) (the dated run this README's numbers
come from, and the reproducibility methodology behind `make eval-replay`), and
[`FAILURE_DEMOS.md`](docs/FAILURE_DEMOS.md) (the four scripted failure demos, grounded in
real corpus cases). [`HUMAN_BASELINE.md`](docs/HUMAN_BASELINE.md) is the protocol for the
one measurement this repository cannot produce on its own, a real timed baseline, not yet run.

## What this is not

Single-analyst tool, no auth or user management. Server-rendered HTML, no frontend framework.
No vector database or RAG, nothing here has a retrieval problem. One model, three calls, no
agents. Docker Compose, no Kubernetes or cloud. SAML only, no OIDC/SCIM/WS-Fed. Not a claim of
Entra, Okta, or Ping experience, the harness runs Keycloak and any protocol quirks specific to
those vendors are, at most, modeled from public documentation and labeled as such.
