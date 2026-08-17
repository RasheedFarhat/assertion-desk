# AI Design

Every model call in this system is answerable against the same 10-question bar the plan set
out before any code was written. This document answers it against the real schemas in
`desk/reason/schemas.py`, not the plan's illustrative sketch, since that sketch's own
`claimed_idp` field for Job A turned out not to exist once the schema was actually built (see
the module's own docstring). Field names below are copied from the schema dicts directly.

**Provider.** Gemini primary, Ollama local fallback (`qwen3:1.7b` in the published run),
fixture replay checked first regardless of mode. Temperature 0, JSON-schema-constrained output
for all three jobs, enforced twice, once by the provider's own schema parameter
(`response_json_schema` for Gemini, `format` for Ollama) and independently again by
`schemas.py:validate_against_schema`, a hand-rolled JSON Schema checker used as a provider-
agnostic post-hoc check regardless of which tier answered.

## Job A — narrative comprehension

1. **Why not deterministic?** The input is a customer's free-text subject and body, e.g. "our
   Entra guy did something Tuesday and now half the team is stuck." No parser recovers scope,
   timing, and a stated recent change from that; it requires reading comprehension.
2. **Receives:** the narrative's `subject` and `body` only. No check results, so extraction
   cannot be biased by what the verifier already found.
3. **Produces (`JOB_A_SCHEMA`, all 11 fields required, `additionalProperties: false`):**
   `scope` (enum: `all_users` / `subset` / `single_user` / `new_users_only` / `unknown`) with
   `scope_confidence`; `onset` (nullable string) with `onset_confidence`; `recent_change`
   (nullable string) with `recent_change_confidence`; `already_tried` (array of strings);
   `reporter_role` (nullable string) with `reporter_role_confidence`; `wrong_belief` (nullable
   string) with `wrong_belief_confidence`. Field names deliberately match
   `harness/narratives/facts.py`'s `NarrativeFacts` TypedDict so the eval harness can grade
   extracted facts against frozen ground truth field for field.
4. **Output format:** the schema above, hand-rolled JSON Schema, not the `jsonschema` package
   and not Gemini's OpenAPI-flavored `Schema` object, because one dict has to serve three
   different consumers (Gemini's parameter, Ollama's parameter, and the module's own checker).
5. **Low confidence:** there is no hard cutoff that swaps a value for `unknown` inside Job A
   itself; every field carries its own confidence score and downstream consumers (Job C's
   prompt, `desk/pipeline.py`) read the confidence alongside the value rather than the module
   silently discarding low-confidence answers.
6. **Hallucination containment:** these are claims about what the *customer said*, not claims
   about the system. `desk/pipeline.py` passes `job_a_facts` into Job B and Job C as customer-
   asserted context, never as verified fact, and `desk/ground` never checks Job A's output
   against the verifier at all, because Job A makes no claim the verifier could confirm or
   deny.
7. **Approval gate:** no. Job A's output never reaches a customer directly.
8. **Auditable:** yes. `desk/reason/fixtures.py`'s fixture cache and `desk/case`'s trace both
   persist the full prompt and response; the case card's model-input-transcript toggle shows
   the literal bytes sent.
9. **Cost:** small, a few hundred to low-thousand input tokens, a few hundred output tokens.
10. **Unavailable:** the fallback cascade (`desk/reason/fallback.py`) tries fixture, then live
    client in order, then the next client, and ultimately falls to a deterministic path; Job A
    not running at all means `job_a_facts` stays `None` and Job B/Job C proceed without
    customer-asserted context rather than blocking.

## Job B — evidence-gap request

1. **Why not deterministic?** `desk/verify/gaps.py:compute_gaps()` already computes, purely
   deterministically, which `not_verified` checks have a named artifact that would resolve
   them. Turning that machine list into a short, specific, non-condescending customer message
   is a writing task, not a computation.
2. **Receives:** the deterministic gap list from `compute_gaps()`, plus Job A's facts (nullable)
   for tone and context, never the raw customer artifacts.
3. **Produces (`JOB_B_SCHEMA`, all 3 fields required, `additionalProperties: false`):**
   `subject` (string), `body` (string), `requested_artifacts` (array, `minItems: 1`, each item
   constrained to the exact same closed enum `desk/verify/gaps.py`'s `REQUESTED_ARTIFACTS` table
   maps gaps to, e.g. `REQUESTED_ARTIFACT_IDP_METADATA` from `SAML-SIG-01`,
   `REQUESTED_ARTIFACT_SP_REQUEST_LOG` from `SAML-INRESP-01`).
4. **Output format:** the schema above; the enum constraint on `requested_artifacts` is the
   containment mechanism, the model cannot name an artifact that isn't in the closed set the
   verifier's own gap table produces.
5. **Low confidence:** falls through the same cascade as Job A; the deterministic tier renders a
   template listing the raw gap artifacts, worse prose, factually identical.
6. **Hallucination containment:** it cannot request an artifact outside the enum. It is not
   asked to diagnose anything, only to phrase a request for evidence the verifier already
   decided is missing.
7. **Approval gate:** yes, in the full plan design, Job B output is customer-facing and gated by
   `desk/case`'s `human_review`/approval states before publish. (`desk/case/orchestrate.py`
   drives the state transition; `n8n/wf2-approval.json` is the intended human-approval channel,
   currently a manual-import workflow, see `n8n/README.md`.)
8. **Auditable:** yes, same trace mechanism as Job A.
9. **Cost:** small, similar order of magnitude to Job A.
10. **Unavailable:** deterministic template rendering of the raw gap list.

## Job C — explanation synthesis

1. **Why not deterministic?** A template can print "SAML-CERT-02 failed." It cannot adapt an
   explanation's register to a customer who already holds a wrong belief about the cause (Job
   A's `wrong_belief` field), or choose which failed check is the lead finding when several
   fired at once.
2. **Receives:** the completed `VerificationRun` (check results, not raw artifacts) and Job A's
   facts. Never the raw customer artifacts, and never invoked at all unless
   `run.has_any_failed()` is true, i.e. the model is never asked to guess a root cause it has no
   evidence for.
3. **Produces (`JOB_C_SCHEMA`, all 4 fields required, `additionalProperties: false`):**
   `summary` (string), `root_cause` (nullable string), `fix_steps` (array of strings), and
   `claims` (array, `minItems: 1`, mandatory and non-empty by schema, each item `{text,
   check_id, asserted_state}`, all three required, `additionalProperties: false`, where
   `asserted_state` is constrained to `_ASSURANCE_VALUES = sorted(a.value for a in Assurance)`,
   the verifier's own six-state enum, rather than a hand-typed duplicate that could drift from
   it). `claims` being mandatory and non-empty is deliberate: an explanation with zero claims
   would be prose with nothing for `desk/ground` to check, which the module treats as a
   grounding failure in its own right (`desk/ground/validator.py`'s `empty_claims` violation
   kind).
4. **Output format:** the schema above.
5. **Low confidence:** if the verifier produced no failed check, Job C is not invoked; the case
   routes to `awaiting_evidence` or stays clean. There is no "guess anyway" path.
6. **Hallucination containment, the core mechanism.** `desk/ground/validate_job_c_output()`
   walks every entry in `claims[]` and rejects the whole output if any claim cites a `check_id`
   the verifier never ran, asserts an `asserted_state` different from the state that check
   actually produced, or the free-text `summary`/`root_cause` prose references a check ID absent
   from `claims[]`. A rejection is a recorded `GroundingResult`, not a retry-until-it-passes
   loop, and `desk/pipeline.py` leaves `final_root_cause` as `None` on rejection rather than
   publishing anything. Measured in the published run: 25% of real (non-deterministic-template)
   Job C outputs rejected. The deterministic-template tier (`tier_used == "deterministic"`)
   skips the grounding call entirely, not because it is exempt from scrutiny but because it
   derives every claim straight from `run` by construction, so there is nothing left for
   `desk/ground` to catch, and calling it anyway would understate the real catch rate by
   diluting it with outputs that were never capable of being wrong.
7. **Approval gate:** yes, same mechanism as Job B.
8. **Auditable:** yes. Prompt, response, the `GroundingResult` (accepted/violations), and every
   claim-to-check binding are all persisted in the trace.
9. **Cost:** the largest of the three jobs, since it includes the full check-result set in the
   prompt, still a few thousand tokens.
10. **Unavailable:** falls through fixture, then the next live client, then a deterministic
    template that renders the failed checks in plain language, covered at the unit level by
    `tests/reason/test_fallback.py::test_every_tier_exhausted_falls_to_deterministic` (a unit
    test with fake clients, not a forced-failure run against the live corpus, see
    `docs/LIMITATIONS.md`).

## One model, three calls, no agents

Nothing in this pipeline requires a model to plan, choose a tool, or loop. `desk/pipeline.py`
calls Job A, then conditionally Job B and Job C, in a fixed order it controls entirely; the
model never decides what to call next. Adding an agent loop here would introduce non-
determinism into a system whose central claim is that non-determinism is constrained to three
narrow, schema-bound, independently-checked jobs. Declining to add one is a design choice, not
an omission.

## Why the model never sets disposition

Restated from `docs/ARCHITECTURE.md` because it is the answer to the most common skeptical
question about this design: `desk/policy/rules.py`'s `PolicyInput` is built entirely from
`desk/verify`, `desk/ground`, and `desk/custody` outputs. None of Job A, B, or C's parsed JSON
is ever passed into it. A model output can be rejected by `desk/ground` (Job C only) or ignored
downstream (Job A, B are advisory/drafting inputs, not verified facts), but it can never itself
become a policy decision.
