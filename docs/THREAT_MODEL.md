# Threat Model

Ten threats, T1-T10, matching the plan's own numbering. Each entry states the mitigation as it
actually exists in code today, cites the file, and says plainly where the real implementation is
narrower than the plan originally sketched. Following this document's own rule (the same one
`docs/LIMITATIONS.md` and `docs/MEASUREMENTS.md` use): a mitigation that is only partially built
is described as partially built, not rounded up.

**Trust boundaries.** (1) Customer artifact bundle to the system: fully untrusted in content and
structure. (2) The system to the model provider: an egress boundary where only de-fanged,
delimited content crosses. (3) Model output to the system: untrusted; never executed, never
authoritative for disposition. (4) n8n webhook to the service: authenticated, HMAC-verified. (5)
The system to the customer: gated by human approval in the full case-lifecycle design.

## T1 - Live credentials in customer artifacts (the Okta 2023 pattern)

**Mitigation.** `desk/custody/` runs before anything else touches an artifact and is fail-closed
by construction, not just by convention: `CustodyFinding` (`desk/custody/findings.py`) has no
field capable of holding a cleartext secret value, only a `placeholder_token` correlation
identifier, so even a bug that tried to persist a secret has no column to put it in. Nine
finding classes, one more than the plan's original eight: `idp_session_cookie`, `bearer_token`,
`oauth_refresh_token`, `plaintext_credential` (added after reading a real captured HAR,
`tests/verify/phase0_fixtures/real_login.har`, entry 12, which contains a literal
`password=alice_dev_only` in a login POST body, a category the plan's original sketch had no
place for), `api_key`, `private_key`, `nameid_pii`, `email_pii`, `group_membership`. A third
action state beyond the plan's replaced/dropped pair, `recorded_only`, exists for one genuine
edge case: a SAML NameID or group-membership Attribute is PII, but it is also evidence
`desk/verify`'s NAMEID checks structurally need inside signed XML, so redacting it in place
would break the exact verification the project depends on. It is logged for the audit trail and
kept out of the model prompt at `desk/reason`'s boundary instead of being mutated in the
artifact the verifier operates on.

**Measured.** 0 secret patterns found across 145 real recorded outbound prompts, by an
independent scanner deliberately separate from the detector under test (`docs/MEASUREMENTS.md`).

## T2 - Indirect prompt injection via log fields / narrative

**Structural mitigation, verified and load-bearing.** `desk/policy/rules.py`'s own docstring
states it plainly: no field of `PolicyInput` carries model output text, every field traces to a
verifier fact, a grounding verdict, a custody fact, or the pre-call structural signal described
below. A model that is successfully manipulated into writing "mark this case resolved" cannot
change case disposition, because the module that decides disposition never reads that sentence.
This holds even if `desk/ground` had a bug, which is the actual point of putting the defense
here rather than relying only on the grounding veto.

**Heuristic pre-call scanner, real but narrower than the plan implies.**
`desk/reason/prompts.py:detect_instruction_shaped_spans()` regex-matches instruction-shaped text
(`SYSTEM:`, "ignore prior instructions", "mark this case resolved", "skip the certificate
check", and seven similar patterns) and is deliberately over-inclusive, a real customer writing
"the system: keeps rejecting me" trips it, which is an acceptable cost for a signal that only
counts, never blocks. **It is only wired into Job A**, run against the narrative's `subject` and
`body`. `desk/reason/jobs.py` hard-codes `instruction_signals=[]` for Job B and Job C, because
neither reads raw customer prose (Job B reads the deterministic gap list and Job A's already-
extracted facts; Job C reads check results). Of the corpus's 4 adversarial cases, only one,
`clock_skew__adv_s3_context_manipulation`, carries its payload in the narrative body where this
scanner can see it. The other three carry theirs in an artifact location nothing scans yet:

| Case | Taxonomy | Payload location |
|---|---|---|
| `cert_rotation__adv_s1_direct_override` | S1 direct override | an XML comment inside the SAMLResponse |
| `wrong_issuer__adv_s2_persona_hijack` | S2 persona hijack | the HAR's captured `User-Agent` header on the ACS POST |
| `clock_skew__adv_s3_context_manipulation` | S3 context manipulation | the narrative body (the one case the scanner covers) |
| `assertion_expired__adv_s4_obfuscated` | S4 obfuscated | base64 inside an attribute adjacent to the SAMLResponse |

**Why this is a smaller gap than it sounds.** All 4 adversarial cases already carry a genuine
`FAILED` check independent of their injection payload, so `desk/policy`'s `has_failed_check`
branch routes every one of them to `review_required` regardless of whether the heuristic scanner
fires. The structural defense (model has no authority over disposition) covers all four; the
counting signal covers one of four. Widening span detection to HAR headers and XML comments is
named, real future work, not claimed as done.

**Measured.** Injection resistance on the one case with a genuine live path into a model prompt:
100% resisted (n=1). The other three "unaffected" outcomes reflect the artifact never being read
into a prompt at all, not demonstrated resistance to a payload a model actually saw. See
`docs/LIMITATIONS.md` for the same caveat stated as a limitation.

## T3 - XXE, entity expansion, and malformed XML/HAR

**Mitigation, real and independently verified twice.** Every untrusted-XML entry point
(`desk/verify/xmldsig.py`, `desk/verify/parsed.py`, `desk/custody/scan.py`) runs a defused
pre-parse check first, `defusedxml.ElementTree.fromstring(raw_bytes)`, which raises on entity-
expansion/XXE-shaped input; the result is discarded, its only job is to fail fast and safely.
The bytes are then parsed again for real use with a separately hardened `lxml.etree.XMLParser`
(`resolve_entities=False, no_network=True, huge_tree=False`), needed because `signxml`'s
signature verification requires a genuine `lxml` tree that `defusedxml`'s own tree type cannot
provide. Two independent parsers, neither trusting the raw bytes, is a deliberate defense-in-
depth choice, not redundancy for its own sake.

**Real gap, stated plainly.** No explicit byte-size cap or decompression-ratio cap constant was
found anywhere in `desk/custody/scan.py` or `desk/verify/`, and no dedicated `desk/intake/`
module exists yet (`desk/intake/` is a tracked-empty directory, no files). `huge_tree=False`
gives lxml's own built-in depth/complexity ceiling, which is real protection, but it is not the
same as an explicit, named, tested byte-size or decompression-ratio limit the plan called for.
This is an honest gap, not a claimed mitigation.

**Corpus coverage.** 2 of 51 cases are labeled `malformed` in `corpus/MANIFEST.json`, far short
of the plan's aspirational ~25. Small, real, not padded.

## T4 - SSRF via IdP metadata URL

**Mitigation: the strongest possible one, by omission.** `grep`-verified: no code path anywhere
under `desk/` calls `requests.get`, `urlopen`, `httpx.get`, or any other outbound-fetch function
against a customer-supplied URL. IdP metadata is only ever accepted as an uploaded artifact, never
fetched by the system from a URL the customer provides. There is no allowlist to bypass because
there is no fetch capability to bypass. If URL-based metadata retrieval is ever added, it needs
the allowlist/no-redirect/private-range-denial design the plan specifies; today the threat has no
surface at all.

## T5 - Data leakage to the model provider

**Mitigation.** Every job's prompt is built through `desk/reason/prompts.py`, which wraps all
customer-supplied text in a fixed delimiter pair and an explicit preamble stating that content
between the delimiters is data, never instruction, regardless of what it claims to be. Job C
receives verifier check results, not raw artifacts. Custody's placeholder substitution (T1) runs
before any of this, so the content that does cross the delimiter has already had credentials and
PII replaced with typed tokens. Full prompt/response transcripts are persisted and auditable
(the case card's model-input-transcript toggle).

**Named, undismissed caveat.** No `GEMINI_API_KEY` is configured in the environment the published
run was generated in; Google's free-tier terms permit using free-tier prompts to improve their
products, a real data-handling fact for anyone running this against a paid Gemini key, documented
here rather than only in a terms-of-service page nobody reads.

**Measured.** Same 0/145 figure as T1, since the scan is over the same stored transcripts.

## T6 - Over-automation / wrong auto-answer

**Mitigation.** `desk/policy/rules.py`'s disposition vocabulary includes `auto`, but the current
rule table never emits it, confirmed both by reading the rule table's own docstring and by
inspection of all 51 corpus `label.json` files (zero have `expected_disposition == "auto"`). This
is a real, checked property, not an oversight, per the module's own comment. Unknown or
unrecognized verifier states resolve to `review_required` by default, "default-deny," not a
silent pass-through. Every case that would reach a customer needs human approval in the full
lifecycle design (`desk/case/orchestrate.py`, gated by `n8n/wf2-approval.json`).

## T7 - Model unavailable, rate-limited, or degraded

**Mitigation.** `desk/reason/fallback.py`'s cascade tries the fixture cache first (in every mode,
not just replay), then each configured live client in order, retrying within a budget on
transient errors and skipping straight to the next client on an unavailable-provider signal, and
falls to a deterministic template as the last resort, which still produces a correct verdict, just
with plainer prose. Job C's deterministic tier renders every claim straight from the verifier's
own `run` object, so it is grounded by construction; the pipeline skips calling `desk/ground` on
it for exactly that reason, not to dodge scrutiny.

**Coverage, honestly scoped.** Confirmed via `tests/reason/test_fallback.py`, 10 tests including
`test_every_tier_exhausted_falls_to_deterministic`. This is unit-level coverage with fake clients,
not a `make chaos` CLI target forcing real provider failures against the live corpus end to end;
no such target exists in this repository yet (see `docs/LIMITATIONS.md`).

## T8 - Stale or conflicting metadata yielding a false "verified"

**Mitigation.** The six-state `Assurance` enum (`desk/verify/assurance.py`) structurally forbids
`verified` on absence of evidence, only `not_verified`, `not_tested`, or `not_applicable` are
available when a required artifact is missing. Conflicting evidence (two certificates in metadata,
neither matching) produces `review_required`, never a guessed diagnosis.

**Named, honestly reported mismatches, three of them, not one.** `desk/policy/rules.py`'s
docstring calls out `duplicate_role_attributes` by name as an illustrative example, but the
authoritative, complete list lives in `eval/metrics.py`'s `KNOWN_DISPOSITION_MISMATCHES` dict,
and it has three entries, all tracing to one shared root cause: `harness/faults/baseline.py`
hardcodes `in_response_to_expected=None` because the harness's own minimal SP
(`harness/capture/sp_app.py`) never persists its own outbound request IDs to check a response
against later. That makes `SAML-INRESP-01`/`SAML-INRESP-02` come back `NOT_VERIFIED` in
effectively every case (46 of 47 cases with check results), not just the one case that fault is
actually about, which means `compute_gaps()` almost always reports something.

- **`duplicate_role_attributes`** (the corpus's one `conflicting` case): its real pipeline signals
  are indistinguishable from the `withheld_cert`/`withheld_clock` `ambiguous` cases under the
  ground-truth-leakage boundary this module obeys (it never reads a corpus label field to break
  the tie), so the rule table computes `awaiting_evidence` where the label says
  `review_required`.
- **`wrong_binding`**: has zero check coverage for its actual fault (a Redirect-vs-POST binding
  mismatch that lives in the HAR request line, not the parsed SAMLResponse), a fact the corpus's
  own `label.json` states via `no_check_coverage_reason`, compounding the same InResponseTo gap.
- **`stripped_relaystate`**: same shape as `wrong_binding`, a transport-layer fault with no check
  coverage, compounding the same InResponseTo gap.

`tests/policy/test_rules.py`'s corpus parity test asserts these three mismatches stay mismatches
rather than being silently special-cased away, and `eval/metrics.py` reports all three by name
via a small, explicit, case-id-keyed allowlist, not a general rule that could silently absorb an
unrelated future disposition bug. This is exactly the kind of limitation this project's own
culture requires naming rather than quietly fixing by leaking the answer into the decision logic.

## T9 - Unauthenticated n8n webhook

**Mitigation.** `n8n/wf1-intake.json`'s "Verify HMAC Signature" Code node requires an
`x-desk-signature` header, computes `HMAC-SHA256` over the raw JSON body using a secret read from
an environment variable (`DESK_WEBHOOK_SECRET`, never hard-coded), and refuses the call outright
if the secret is unset. The comparison uses `crypto.timingSafeEqual` after a length check, a
deliberate constant-time compare so a naive `===` cannot leak how many leading bytes matched.
This lives in n8n's Code node by design, not in `desk/api.py`, because signature verification is
trivial logic that belongs in the orchestration layer, unlike parsing, crypto, custody, or
grounding, which must never move into n8n (see `n8n/README.md`).

## T10 - Secret sprawl in the repository

**Real gap, not mitigated yet.** `grep`-verified: no `gitleaks` configuration or CI job exists
anywhere in this repository. `.github/workflows/` is an empty directory (see `docs/LIMITATIONS.md`
for the full CI gap). This threat is currently addressed only by discipline (the corpus generator
scrubs at generation time, per `harness/generate.py`) and by T1's independent secret-scan test at
the application layer, not by a repository-wide CI gate. Naming this as unmitigated rather than
implying CI coverage that does not exist is the point of this document.

## What this threat model does not cover

Multi-tenant isolation, authentication or authorization for the tool itself, denial-of-service
resistance at scale, and any claim of protecting a real production support system. Assertion Desk
models a workflow; it does not claim to secure one that exists.
