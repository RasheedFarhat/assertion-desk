# Architecture

**The verifier decides what is true. The model decides what to say about it.** Everything in
this document exists to make that sentence enforceable in code, not just true in a README.

## Layering rule

Dependencies point one direction only: `eval/`, `desk/api.py`, and `desk/case/orchestrate.py`
all depend on `desk/pipeline.py`; `desk/pipeline.py` never depends on any of them. Inside
`desk/pipeline.py` itself the sequence is fixed: `desk/verify` runs first and is never given
model output to consider; `desk/reason` runs second and is given verifier facts, never the raw
customer artifacts, for its explanation job; `desk/ground` runs third and sees both the
verifier's facts and the model's claims, and it is the only module with the authority to
discard a model output; `desk/policy` runs last and reads verifier facts, the grounding
verdict, and custody facts, never a model's parsed text directly (confirmed by reading
`desk/policy/rules.py`'s own docstring: every `PolicyInput` field traces to a verifier fact, a
grounding verdict, a custody-scan fact, or a pre-call structural signal). This ordering is
what makes the headline claim structural rather than aspirational: even if `desk/ground` had a
bug, `desk/policy` still never reads a model's claim directly, so a single bad module cannot by
itself let an ungrounded claim become an action.

## Data flow

```
customer artifact bundle  (UNTRUSTED: prose, HAR, SAMLResponse, IdP metadata)
        │
        ▼
  desk/custody     9 typed finding classes -> placeholders + a custody record   NO AI
        │          idp_session_cookie, bearer_token, oauth_refresh_token,
        │          plaintext_credential, api_key, private_key, nameid_pii,
        │          email_pii, group_membership. Cleartext secret values are
        │          never a stored column, only the class, location, and a
        │          placeholder token are. Measured: 0 hits in 145 real
        │          outbound prompts (independent scanner, docs/MEASUREMENTS.md).
        ▼
  desk/verify      20 checks (desk/verify/checks/*.py) -> six-state assurance  NO AI
        │          SAML-SIG-01/02, SAML-CERT-01/02, SAML-AUD-01, SAML-DEST-01,
        │          SAML-RECIP-01, SAML-ISS-01/02, SAML-SKEW-01, SAML-COND-01/02,
        │          SAML-INRESP-01/02, SAML-NAMEID-01/02, SAML-ATTR-01,
        │          SAML-ENC-01, SAML-SCM-01, SAML-STATUS-01.
        │          verified | failed | review_required | not_verified |
        │          not_tested | not_applicable -- desk/verify/assurance.py's
        │          Assurance enum. Absence of evidence can only ever produce
        │          not_verified, never verified; that rule is what stops a
        │          missing artifact from silently reading as "fine."
        ▼
  desk/verify/gaps  compute_gaps(): which not_verified checks have a named,     NO AI
        │           closed-enum artifact that would resolve them
        ▼
  desk/reason      3 schema-bound calls (desk/reason/jobs.py), Gemini primary,  AI
        │          Ollama fallback, fixture replay first in every mode:
        │            Job A -- narrative -> 6 structured facts (scope, onset,
        │              recent_change, already_tried, reporter_role,
        │              wrong_belief), each with a confidence score
        │            Job B -- the gap list -> {subject, body,
        │              requested_artifacts[]} constrained to the same closed
        │              enum desk/verify/gaps.py computes against
        │            Job C -- check results + Job A's facts (never the raw
        │              artifacts) -> {summary, root_cause, fix_steps[],
        │              claims[]}, claims[] mandatory and non-empty, each claim
        │              {text, check_id, asserted_state} where asserted_state
        │              is drawn from the verifier's own Assurance enum
        │          Job C is not invoked at all when the verifier produced no
        │          failed check -- the model is never asked to guess a root
        │          cause it has no evidence for.
        ▼
  desk/ground      walks Job C's claims[] and rejects the whole output if any  NO AI
        │          claim cites an unknown check_id, asserts a state the
        │          verifier did not produce for that check, or the prose
        │          references a check_id absent from claims[]. Measured: 25%
        │          of real (non-deterministic-template) Job C outputs
        │          rejected in the published run.
        ▼
  desk/policy      auto | review_required | escalate | awaiting_evidence      NO AI
        │          (desk/policy/rules.py). auto is defined in the vocabulary
        │          but the current rule table never emits it -- 0 of 51
        │          corpus cases have expected_disposition == "auto" -- a
        │          real, checked property of the rule table, not an
        │          oversight (see the module's own docstring).
        ▼
  desk/case        CaseState machine (desk/case/state.py), hash-linked trace
        │          (desk/case/trace.py), Postgres/SQLite persistence for
        │          Case, TraceEvent, and Approval only -- see
        │          docs/LIMITATIONS.md for what is not yet persisted.
        │          desk/case/orchestrate.py drives VERIFYING -> * using a
        │          real PipelineResult and PolicyInput, mirroring
        │          eval/metrics.py's computed_disposition() field for field
        │          so a live case and a corpus case are scored identically.
        ▼
  n8n WF1-WF4      webhook intake + HMAC verification, human approval gate
                   (Gmail send-and-wait, never auto-approves on timeout),
                   evidence-chase polling, nightly eval report. Orchestration
                   only -- see n8n/README.md for exactly what it does and
                   does not do. `make demo` and `make eval*` run correctly
                   with n8n stopped.
```

## Module map

| Package | Responsibility | AI involved |
|---|---|---|
| `desk/custody/` | Detect and neutralize live credentials and PII in customer artifacts before anything else reads them; write the custody record | No |
| `desk/verify/` | 20 deterministic SAML federation checks; XML-DSig, X.509, timing, exact-match URL/string comparison | No |
| `desk/reason/` | Three schema-bound model jobs, plus the fixture-cache/live/fallback cascade (`desk/reason/fallback.py`) | Yes, the only AI in the system |
| `desk/ground/` | Cross-checks every model claim against the verifier's own facts; the module that makes "the AI cannot assert a fact the verifier didn't confirm" a structural property, not a policy | No (its input includes model output, but its logic is a fixed cross-check, not a model call) |
| `desk/policy/` | The disposition decision; reads verifier facts, grounding verdicts, and custody facts only, never a model's parsed content directly | No |
| `desk/case/` | State machine, hash-linked trace, persistence, the live orchestrator | No |
| `desk/pipeline.py` | The one place `verify -> gaps -> reason -> ground` is implemented; both `eval/run.py` and `desk/case/orchestrate.py` call into it rather than each reimplementing the sequence | No (it calls `desk/reason`, it does not reason) |
| `desk/api.py` | Flask HTTP surface: `POST /cases` (demo intake, wraps a frozen corpus case), `GET /cases`, `GET /cases/<id>`, `GET /cases/<id>/card` (server-rendered, includes the model-input-transcript toggle), `POST /cases/<id>/post-for-review`, `POST /cases/<id>/decision`, `POST /cases/<id>/publish` | No |
| `harness/` | Fault injectors driving a real Keycloak instance plus Playwright HAR capture; produces the corpus's ground truth by causing the fault, not by labeling it after the fact | No at runtime; narrative text was generated offline and human-reviewed before being frozen |
| `eval/` | Corpus batch runner, metrics, and report generation; the source of every number in `docs/MEASUREMENTS.md` | No |
| `n8n/` | Four workflow exports: intake, approval gate, evidence chase, nightly eval report | No (orchestration only) |

## Why the model never touches disposition

`desk/policy/rules.py`'s `PolicyInput` dataclass is constructed entirely from typed fields
produced by `desk/verify`, `desk/ground`, and `desk/custody`. It has no field that carries a
model's free-text output. This means a prompt-injection payload that successfully convinces
the model to write "this case is resolved, skip the certificate check" produces, at most, a
`GroundingResult` with a rejected claim (because no check named in that sentence has a matching
`FAILED` state to cite), never a disposition change, because `desk/policy` was never given the
sentence to read in the first place. `desk/ground` is the last line of defense against the
model's own text; `desk/policy`'s ignorance of that text is the defense that does not depend on
`desk/ground` having no bugs.

## Real scale, stated plainly

20 checks, not the plan's originally-cited approximate figure, verified by direct count in
`desk/verify/checks/*.py`. 9 custody finding classes (`desk/custody/findings.py`), one more than
the plan's original eight (`plaintext_credential` was added after reading a real captured HAR).
51 corpus
cases, 50 executable (`corpus/MANIFEST.json`), not the plan's aspirational ~250. Case
persistence covers 3 of the 10 entities in the plan's original data model (`Case`,
`TraceEvent`, `Approval`); the other 7 live only in an in-process cache. Full detail on what
that gap means in practice is in `docs/LIMITATIONS.md`.
