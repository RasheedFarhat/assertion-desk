<div align="center">

<h1>Assertion Desk</h1>

<p><strong>Deterministic evidence before generated explanations.</strong></p>

<p>A security-first SAML support-triage lab that treats both customer evidence and model output as untrusted.</p>

<p><a href="#run-the-proof">Quickstart</a> · <a href="#how-it-works">Architecture</a> · <a href="#measured-not-marketed">Evaluation</a> · <a href="docs/THREAT_MODEL.md">Threat model</a> · <a href="docs/LIMITATIONS.md">Limitations</a></p>

<p><code>make eval-replay</code> · 50-case offline proof · demo-scoped, not production-ready</p>

</div>

## Why it exists

In 2023, an attacker accessed files in Okta's customer support system. Some were HAR files containing session tokens that could be used to hijack legitimate sessions, a failure mode documented in [Okta's incident report](https://sec.okta.com/articles/2023/11/unauthorized-access-oktas-support-case-management-system-root-cause/). The same artifacts that make SSO failures diagnosable can also contain live credentials.

Assertion Desk explores a safer order of operations: quarantine sensitive material, establish SAML facts with deterministic checks, allow a model to explain only those facts, validate its claims, and require human approval before anything customer-facing is published.

> **The verifier decides what is true. The model decides how to explain it.**

## Run the proof

The primary demo is a committed, checksummed corpus replay. After dependency installation it requires **no API key, model service, Keycloak instance, or network access**, and a cache miss fails loudly instead of contacting a provider.

```bash
git clone https://github.com/RasheedFarhat/assertion-desk.git
cd assertion-desk
python3 -m venv .venv
.venv/bin/python3 -m pip install -r requirements.txt
make eval-replay
```

The replay runs all 50 executable cases, writes a fresh report and `metrics.json`, and reproduces the committed evaluation baseline. Then explore the system from three angles:

```bash
make demo   # five representative cases, replay-only
make test   # full desk/, eval/, and harness/ suite
make help   # every supported target and its prerequisites
```

<details>
<summary><strong>Native xmlsec prerequisites</strong></summary>

`python3-saml` and `xmlsec` require native XML Security libraries before `pip install`.

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y \
  libxml2-dev libxslt1-dev libxmlsec1-dev libxmlsec1-openssl pkg-config
```

macOS with Homebrew:

```bash
brew install libxml2 libxmlsec1 pkg-config
```

</details>

## How it works

Only Jobs A, B, and C involve a language model. Everything that establishes truth, accepts or rejects claims, chooses a disposition, or authorizes publishing is deterministic or human-controlled. The diagram draws that boundary explicitly: the deterministic core has full authority over facts, the AI layer is confined to producing prose from facts it did not decide, and grounding sits between them as a veto, not a suggestion.

```mermaid
flowchart TD
    A["Customer artifact bundle<br/>prose + HAR + SAMLResponse + IdP metadata<br/><b>UNTRUSTED</b>"]

    subgraph DET["Deterministic core -- decides what is TRUE -- no AI anywhere in this box"]
        direction TB
        B["desk/custody<br/>quarantine credentials + PII<br/>before anything else reads them"]
        C["desk/verify<br/>~20 SAML checks, six-state assurance"]
        D["gap computation<br/>what is not_verified, and why"]
        G["desk/ground<br/>reject any claim citing an unknown check<br/>or a state the verifier never produced"]
        P["desk/policy<br/>review_required / escalate / awaiting_evidence"]
        B --> C --> D
        G --> P
    end

    subgraph AI["desk/reason -- subordinate -- decides only what to SAY"]
        direction TB
        J["Job A -- read the customer's prose"]
        K["Job B -- draft an evidence request"]
        L["Job C -- explain a failed check<br/>never invoked without one"]
    end

    H["Human reviewer<br/>approve, override, or escalate"]
    Z["Published reply / evidence request"]

    A --> B
    D -->|"context + gaps only,<br/>never raw artifacts"| J
    D --> K
    D -->|"only if a check failed"| L
    J --> G
    K --> G
    L --> G
    P -->|"anything customer-facing"| H
    H --> Z
```

The pipeline follows one direction:

1. Untrusted customer evidence enters custody, where sensitive material is scanned, redacted, and recorded.
2. A deterministic verifier runs 20 SAML checks.
3. Job A extracts context from the defanged narrative. Job B may write an evidence request; Job C may explain failed verifier checks.
4. The grounding layer rejects unsupported model claims.
5. Deterministic policy chooses a disposition.
6. A human reviewer decides whether to publish or escalate.

The architecture enforces six useful invariants:

- Missing evidence can produce `not_verified`, never `verified`.
- Job C is not invoked unless the verifier produced a failed check.
- Job C receives check results and extracted narrative context, never raw artifacts.
- Model prose is not a field in the deterministic disposition policy.
- A grounding rejection leaves the publishable root cause empty.
- Fixture replay reproduces the published evaluation without calling a live model.

The implementation details and dependency boundaries are mapped in [Architecture](docs/ARCHITECTURE.md); the three narrow model jobs are justified field by field in [AI Design](docs/AI_DESIGN.md).

## Measured, not marketed

These results come from two committed runs against the same 50 executable cases (of 51 corpus entries, with one explicitly documented generator gap): the 2026-08-17 local-fallback pass (`qwen3:1.7b` via Ollama) and the 2026-08-19 live Gemini pass (`gemini-3.1-flash-lite`, not the flagship — see the warning below).

| Measurement | `qwen3:1.7b` | `gemini-3.1-flash-lite` | What it means |
|---|---:|---:|---|
| AI-assisted root-cause accuracy | 65.0% (26/40) | **72.5%** (29/40) | Both below the 85% target; the failed threshold is intentionally visible. |
| Deterministic-only root-cause baseline | 90.0% (36/40) | 90.0% (36/40) | Identical by construction (no LLM in this path) — the simpler path outperforms *both* model-assisted passes. |
| Deterministic disposition accuracy | 94.0% (47/50) | 94.0% (47/50) | Three known mismatches, zero unexpected mismatches. |
| Ambiguous-case refusal | 100% (2/2) | 100% (2/2) | Withheld evidence did not produce a guessed root cause. |
| Malformed-input handling | 100% (2/2) | 100% (2/2) | Both malformed responses became named parse errors, not crashes. |
| Secret patterns in stored prompts | 0 / 145 | 0 / 145 | An independent scanner found no JWT, bearer, session-cookie, or private-key pattern. |
| Grounding rejection rate | 25.0% (10/40) | **0.0%** (0/42) | One in four `qwen3` Job C outputs was withheld for violating grounding rules; flash-lite's were all accepted. |
| Injection resistance, all payloads | 4 / 4 resisted | 4 / 4 resisted | One (S3) has a real live prompt path; the other three are structurally inapplicable, so a pass reflects absence of a path more than demonstrated resistance. |

> [!WARNING]
> The `gemini-3.1-flash-lite` numbers are a real, live measurement — not the flagship `gemini-3.6-flash` the pipeline defaults to. The flagship's free-tier quota is a hard 20 requests/day/project, far short of a full pass; flash-lite was substituted via an env override for this run only. Neither run is a repeated-run variance study, a production benchmark, or evidence of general injection resistance at scale. Read the [full measurements](docs/MEASUREMENTS.md), [qwen3 metrics](eval/runs/20260817T044253Z/metrics.json), and [Gemini metrics](eval/runs/20260819T051200Z_gemini_flash_lite/metrics.json) before interpreting the headline figures.

The most important result is the uncomfortable one, and it held across both models: the AI-assisted path is not accurate enough yet, and is less accurate at root-cause naming than the deterministic checks alone. `qwen3`'s misses skewed toward the grounding layer declining to guess and a repeatable bias toward one specific check; `gemini-3.1-flash-lite`'s misses are different but equally systematic — a consistent cert-expiry/condition-expiry mix-up and a complete failure to ever name the missing-NameID check across all five phrasings of that case. Different model, different failure mode, same conclusion: named rather than tuned away.

## Honest project status

| Implemented and exercised | Demo-scoped or partial | Not implemented |
|---|---|---|
| Fail-closed HAR/XML/prose custody scanners<br/>20 deterministic SAML checks<br/>Three schema-bound model jobs<br/>Grounding veto and deterministic policy<br/>Case lifecycle and hash-linked trace<br/>Offline fixture replay and CI gates | `POST /cases` wraps frozen corpus cases<br/>SQLite stores Case, TraceEvent, and Approval only<br/>Pipeline detail is cached in process<br/>n8n workflows require manual import and credentials<br/>Gemini is configured as primary; measured so far only via a free-tier `gemini-3.1-flash-lite` substitute, not the flagship | Live customer artifact upload<br/>Complete durable evidence/model storage<br/>Customer-reply artifact re-ingestion<br/>Real ITSM integration<br/>Authentication or multi-tenancy<br/>Production WSGI deployment<br/>OIDC, SCIM, or WS-Fed |

> [!IMPORTANT]
> The web API is a corpus-backed demonstration, not live intake. The custody package is implemented and independently tested, but full artifact-bundle custody is not wired into `POST /cases`; only Job A's narrative passes through custody on the current case path.

Persistence is implemented and tested with SQLite. The SQL was written with portability in mind, but PostgreSQL has not been exercised here. Policy dispositions are `auto`, `review_required`, `escalate`, and `awaiting_evidence`; `blocked` is a case lifecycle state, not a disposition. The current rule table defines `auto` but never emits it.

## Try the web demo

Start the Flask development server:

```bash
make serve
```

In a second terminal, create a case from the frozen `cert_expired` corpus scenario:

```bash
curl -s -X POST http://127.0.0.1:5050/cases \
  -H 'Content-Type: application/json' \
  -d '{"corpus_case":"cert_expired"}' | python3 -m json.tool
```

Copy the returned `id`, then open:

```text
http://127.0.0.1:5050/cases/<id>/card
```

The server-rendered card shows the verification grid, model outputs, reconstructed and hash-verified model-input transcripts, grounding result, policy decision, approvals, and hash-linked trace.

<details>
<summary><strong>HTTP surface</strong></summary>

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Process health check. |
| `POST` | `/cases` | Create and run a frozen-corpus demo case. |
| `GET` | `/cases` | List cases, optionally filtered by `state`. |
| `GET` | `/cases/<id>` | Durable case data plus cached pipeline detail when available. |
| `GET` | `/cases/<id>/card` | Render the human-readable case card. |
| `POST` | `/cases/<id>/post-for-review` | Move a reasoned case into human review. |
| `POST` | `/cases/<id>/decision` | Record an approval or escalation decision. |
| `POST` | `/cases/<id>/publish` | Publish an approved case. |

</details>

<details>
<summary><strong>Live evaluation and optional services</strong></summary>

Run the live provider cascade instead of fixture-only replay:

```bash
make eval
```

`GEMINI_API_KEY` enables Gemini. Without it, the cascade tries the configured Ollama endpoint and then the deterministic renderer. Optional Compose profiles are defined for the application, Keycloak, n8n, and Ollama:

```bash
docker compose --profile idp up -d
docker compose --profile local-model up -d
docker compose --profile core --profile orchestration up -d
```

Use `make serve` for the tested local HTTP demo. The n8n profile is orchestration scaffolding: its four workflows must be imported and configured manually, and its evidence-reply loop is incomplete. See [n8n/README.md](n8n/README.md).

</details>

<details>
<summary><strong>Corpus regeneration and ROI</strong></summary>

The committed corpus is sufficient for replay. Regenerating it is an explicit infrastructure task:

```bash
docker compose --profile idp up -d
make corpus
```

The ROI calculator refuses to invent its two most important inputs. Supply measured manual and review times from the [human baseline protocol](docs/HUMAN_BASELINE.md):

```bash
make roi ARGS="--baseline-minutes 45 --review-minutes 5"
```

The numbers above are an invocation example, not a measured result. [Human Baseline](docs/HUMAN_BASELINE.md) also cites published IT-ticket and root-cause-diagnosis benchmarks as motivating context; none of them are SAML-specific or hands-on-diagnosis-specific enough to stand in for a real measurement, so they are never passed to this calculator.

</details>

## Explore the repository

| Area | Responsibility |
|---|---|
| [`desk/`](desk/) | Custody, verification, model jobs, grounding, policy, case lifecycle, persistence, and Flask API. |
| [`harness/`](harness/) | Keycloak/Playwright capture, 23 fault classes, narrative registers, and adversarial overlays. |
| [`corpus/`](corpus/) | Frozen cases and checksummed `MANIFEST.json` ground truth. |
| [`fixtures/`](fixtures/) | Write-once model transcripts used for deterministic replay. |
| [`eval/`](eval/) | Corpus runner, metrics, Markdown reports, committed runs, and ROI calculator. |
| [`n8n/`](n8n/) | Intake, approval, evidence-chase, and nightly-evaluation workflow exports. |
| [`tests/`](tests/) | Package-level verification of the core, evaluation, and harness behavior. |
| [`.github/workflows/`](.github/workflows/) | Test, replay-diff, CodeQL, and repository secret-scanning gates. |

## Documentation

| Track | Read next |
|---|---|
| Design | [Architecture](docs/ARCHITECTURE.md) · [AI Design](docs/AI_DESIGN.md) · [Threat Model](docs/THREAT_MODEL.md) |
| Evidence | [Corpus](docs/CORPUS.md) · [Evaluation Framework](docs/EVALUATION.md) · [Measurements](docs/MEASUREMENTS.md) |
| Boundaries | [Limitations](docs/LIMITATIONS.md) · [Failure Demos](docs/FAILURE_DEMOS.md) · [Human Baseline](docs/HUMAN_BASELINE.md) |

The dated `PHASE0`–`PHASE4` notes in [`docs/`](docs/) preserve the build history, including bugs found, assumptions rejected, and decisions made along the way.

## Questions and feedback

Assertion Desk is maintained by [Rasheed Farhat](https://github.com/RasheedFarhat). Open an [issue](https://github.com/RasheedFarhat/assertion-desk/issues) for questions, reproducibility problems, or technical feedback.

No license is currently published, so this repository does not make a reuse or redistribution grant.
