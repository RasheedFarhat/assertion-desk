# Limitations

A concrete, verified list of what this system cannot currently do, why, and what file proves
it. The rule for this document is the same one `docs/MEASUREMENTS.md` and `n8n/README.md`
already follow: a limitation gets named the moment it is found, with the file and line that
shows it, not softened into marketing hedging. Nothing here is deferred silently.

## Accuracy

- **AI-assisted root-cause accuracy is 65.0% (26/40) against an 85% threshold, and it currently
  trails the deterministic-only baseline (90.0%, 36/40) by 25 points.** This is the single
  most important number in the project and it is a failed target, not a met one. Full
  breakdown in `docs/MEASUREMENTS.md`. Of the 14 misses: 9 are the grounding validator
  correctly declining to guess (arguably not defects), and 5 share one specific, repeatable
  bias, the model defaulting to citing `SAML-SIG-01` when a more specific check
  (`SAML-NAMEID-01`, `SAML-NAMEID-02`, `SAML-ENC-01`) is the actual cause. Closing that bias
  is named as the highest-leverage next step in `docs/MEASUREMENTS.md` and has not been done.
- **No number in this repository reflects Gemini.** No `GEMINI_API_KEY` is configured in the
  environment the published run was generated in, so every model call in that run went to the
  local Ollama fallback tier (`qwen3:1.7b`). The architecture, schema enforcement, and
  grounding veto are exercised correctly regardless of which tier answers, but the accuracy
  and prose-quality numbers should not be read as representative of the system's intended
  Gemini-primary path.
- **The published run is one live pass, not the plan's `k=3`-repeats design.** What has been
  established is that a live pass and an offline `--replay-only` pass of the identical corpus
  now produce byte-for-byte identical metrics (the two reproducibility bugs described in
  `docs/MEASUREMENTS.md` are fixed), which is a real and useful claim. It is not the same
  claim as measuring disagreement across repeated live runs, and that measurement has not been
  taken.
- **Injection resistance rests on n=4 adversarial cases, one of which has a genuine live path
  into a model prompt.** The other three payloads target artifact locations (an XML comment, a
  HAR User-Agent header, a base64-encoded attribute value) that no job currently reads, so 2 of
  3 "unaffected" outcomes reflect absence of a path, not demonstrated resistance to a payload a
  model actually saw. `desk/policy/rules.py` never lets a model claim set the case disposition
  (confirmed by reading the module: every `PolicyInput` field traces to a verifier fact, a
  grounding verdict, or a pre-call structural signal, never parsed model text), which is the
  structural defense the plan calls for, but it has not been exercised by anywhere near enough
  adversarial variety to call injection resistance proven in general.

## Corpus

- **51 cases total, 50 executable, not the plan's aspirational ~250.** `corpus/MANIFEST.json`
  has 51 entries; one (`sha1_signature_downgrade`) is a documented, deliberately unimplemented
  gap. The ground truth is real, produced by injecting faults into a live Keycloak instance
  rather than authored by hand, which is the point, but the sample size behind every
  percentage in `docs/MEASUREMENTS.md` is small enough that single-case swings move the
  headline numbers by 2.5 points each.
- **Roughly 30 of the 51 cases share one baseline SAML response and certificate pair.** A
  corpus-contamination incident (documented in `docs/PHASE4_NOTES.md` and summarized in
  `docs/MEASUREMENTS.md`) already showed that a stale shared baseline can silently corrupt
  every case built from it at once. The bug that incident caused is fixed and now caught by a
  hardened self-test, but the underlying structural fact, many cases inherit one shared
  baseline rather than each being independently generated end to end, remains and is worth
  knowing before trusting any claim that the 51 cases are 51 fully independent trials.
- **The identity provider is Keycloak, not Entra, Okta, or Ping.** Any vendor-specific quirk
  named in this repo's documentation or prompts is, at most, modeled from public documentation
  and must be labeled as modeled. No claim of Entra, Okta, or Ping production experience is
  made or should be inferred from this project.
- **Customer narratives are frozen and human-reviewed, not sourced from real tickets.** They
  cover five registers (precise, vague, confidently self-misdiagnosed, hostile, non-native
  phrasing), but they are still authored text standing in for real customer language.

## Persistence and the live-system gaps

These are read directly from `desk/api.py`'s own module docstring and `desk/case/store.py`,
not inferred:

- **`desk/case/store.py` has SQL tables for `cases`, `trace_events`, and `approvals` only.**
  `CheckResult`, `ModelInvocation`, `GroundingResult`, `InjectionSignal`, and `PolicyDecision`,
  all named in the plan's data model, have no persistence layer. The full pipeline result and
  policy decision behind a case live in an **in-process, non-durable dict** keyed by case id.
  `GET /cases/<id>` says so explicitly in its own response (`detail_note`) when the cache has
  no entry, which happens after any process restart or for a case that predates the current
  process.
- **`POST /cases` is a demo intake.** It wraps one of the frozen corpus cases under
  `corpus/cases/`, the same cases `eval/run.py` drives, rather than accepting a live
  customer-supplied artifact bundle. `desk/intake/` (HAR/XML upload parsing with size and
  entity limits) does not exist yet; the plan's own repo layout (section 26) lists it as
  planned, and there is no source under that path today.
- **There is no `/cases/<id>/artifacts` endpoint.** WF3 (the n8n evidence-chase workflow) can
  poll for cases awaiting evidence and send a chase email, but it cannot re-ingest a customer's
  reply and feed it back into the pipeline. `desk/case/state.py`'s own transition table defines
  `awaiting_evidence -> verifying` as the intended destination (a source comment attributes it
  to WF3), so the state exists and is real, but nothing in the current API can drive a case
  there. Closing this loop is real future work, not something faked with an endpoint that does
  not exist. Full detail in `n8n/README.md`'s "What WF3 does not do" section.
- **There is no customer-contact field anywhere in the data model.** Checked directly: no
  `customer_email`, `contact_email`, or `reporter_email` field exists in `desk/` or `mocks/`.
  WF3's customer-facing send therefore targets a configurable demo address, never something
  extracted from a case, matching the plan's explicit rule that Gmail integration here
  operates against a demo account only.
- **`mocks/itsm/` is an empty directory.** The mock ticket system named in the plan's repo
  layout has not been built. `POST /cases/<id>/publish` transitions the case's own state and
  appends a trace event; it does not write to any ticketing system, mock or otherwise.

## Evaluation infrastructure

- **`eval/baselines/` is empty.** No metrics baseline has ever been committed, so the
  regression-detection step in `n8n/wf4-eval-report.json` has nothing to diff against yet. The
  workflow treats a missing baseline as "nothing to compare," not an error, and does not
  silently promote the first run to baseline status, that has to be a deliberate human
  decision.
- **`.github/workflows/` exists as an empty directory.** No CI, no automated `eval-replay` gate
  on pull requests, no CodeQL, no gitleaks scan are wired yet, despite being named in the
  plan's repository structure. Nothing in this repository is currently enforced by CI; every
  guarantee in this document rests on running the commands by hand.
- **WF4's `make eval-replay` step needs the repository and a provisioned `.venv` on whatever
  machine runs it.** n8n's Execute Command node runs inside n8n's own container under the
  default `orchestration` Compose profile, which has no repo bind-mount by design. Running WF4
  for real means running n8n directly on a host with the repo checked out, not the
  containerized profile as shipped. Detail in `n8n/README.md`.

## What this project does not claim to be

- **Single-analyst tool.** No authentication or user management for the tool itself.
- **Not a production system.** No multi-tenant isolation, no DoS resistance at scale, no claim
  of protecting a real support system in production. It models a workflow.
- **SAML only.** No OIDC, SCIM, or WS-Fed support in this version.
- **Docker Compose, not Kubernetes or cloud.** No Terraform, no managed infrastructure.
- **No fine-tuning.** All three model jobs use off-the-shelf Gemini/Ollama models with schema
  constraints, not a custom-trained model.
- **Not ServiceNow, Jira, or Zendesk.** `mocks/itsm/` is a stub for demonstrating the shape of
  a ticket-system integration, and it is currently empty besides.
- **No production cloud, no commercial vulnerability scanners, no SOC platform.** Nothing in
  this repository touches AWS, Azure, GCP, Nessus, Tenable, or a commercial SIEM.

## What is genuinely solid

Naming limitations only tells half the story, and the same evidence-first standard applies
here. Independently verified, not just claimed: zero secret patterns across 145 real recorded
outbound prompts, scanned by code deliberately separate from the custody detector under test;
the grounding validator rejecting 25% of real model outputs rather than the tautological 100%
"catch rate" the metric alone would suggest; the fallback cascade falling through fixture,
then live, then Ollama, to a correct deterministic answer with every tier exhausted, covered at
the unit level by `tests/reason/test_fallback.py::test_every_tier_exhausted_falls_to_deterministic`
(note: this is a unit test with fake clients, not the dedicated `make chaos` CLI target the
plan describes against the live corpus, that target does not exist yet); a live run and an
offline replay run now matching field-for-field; and a corpus whose labels come from a fault
actually injected into real software rather than from a label this project's author wrote.
