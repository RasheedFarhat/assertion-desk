# Corpus

The ground truth in this project comes from a fault injected into real software, not from a
label the author wrote and then graded his own system against. This document describes exactly
how, and states the real scale rather than the plan's aspirational one.

## How ground truth is established

`harness/generate.py` drives a real Keycloak instance and a minimal SAML SP through a genuine
login with Playwright, captures the real HAR, the real SAMLResponse, and the real IdP metadata,
then injects one fault at a time (`harness/faults/*.py`) and re-captures. The label is known
because the harness caused the fault, not because it was assigned afterward. `harness/capture/`
holds the Playwright HAR driver and the Keycloak admin client; `harness/narratives/` holds the
customer-facing prose, generated offline and human-reviewed before being frozen into the corpus,
matching the build-time-AI/runtime-determinism principle used throughout this project.

## Real scale

**23 unique fault classes** (`fault_id` values in `corpus/MANIFEST.json`), close to but not
identical to the plan's "~20" estimate:

`acs_url_trailing_slash`, `assertion_expired`, `broken_signature`, `cert_expired`,
`cert_rotation`, `clock_skew`, `destination_mismatch`, `double_encoded_response`,
`duplicate_role_attributes`, `encrypted_assertion`, `http_https_mismatch`,
`inresponseto_mismatch`, `missing_nameid`, `negative_control`, `sha1_signature_downgrade`,
`stripped_relaystate`, `truncated_response`, `unsupported_nameid_format`, `withheld_cert`,
`withheld_clock`, `wrong_audience`, `wrong_binding`, `wrong_issuer`.

**51 total cases, 50 executable.** One, `sha1_signature_downgrade`, is a documented,
deliberately unimplemented gap (`category: documented_gap` in the manifest), not a silently
broken case. This is far short of the plan's aspirational ~250; every percentage in
`docs/MEASUREMENTS.md` rests on a sample this small, and single-case swings move the headline
numbers by 2.5 points each.

**Case categories** (the manifest's `category` field, distinct from difficulty strata):
`context_mismatch` (26, a fault that produces a mismatch between two pieces of otherwise-valid
evidence, e.g. a signing cert that does not match metadata), `artifact_mutation` (16, a fault
that mutates a captured artifact directly), `live_capture` (7, faults captured by driving a real
login against a genuinely misconfigured Keycloak/SP pair rather than by post-hoc mutation),
`baseline` (1), `documented_gap` (1, the `sha1_signature_downgrade` case above).

**Difficulty strata, real counts** (the manifest's `difficulty` field): `normal` 45,
`malformed` 2, `ambiguous` 2, `conflicting` 1, unset 1 (the documented gap). All far below the
plan's aspirational per-stratum targets (`normal` ~120, `ambiguous` ~40, `conflicting` ~25,
`malformed` ~25). The plan's separate `adversarial` stratum does not exist as a `difficulty`
value at all; adversarial cases are instead tagged `normal` for difficulty and carry a separate
`injection` field (see below), because each of the 4 adversarial cases already has a genuine
`FAILED` check independent of its injection payload, so they behave like `normal` cases for
routing purposes. See `docs/THREAT_MODEL.md`'s T2 entry for the full detail on what that means
for injection-resistance measurement.

**Narrative registers, real counts** (the manifest's `register` field): `precise` 26 (the
majority, since most cases need a straightforward baseline narrative), `vague` 6,
`confident_misdiagnosis` 6, `hostile` 6, `non_native` 6, unset 1 (the documented gap has no
narrative). This is close to the plan's five-register design, just not evenly distributed
across it, `precise` dominates because most cases are single-fault `normal` cases that do not
need a stress-test register.

**Adversarial cases, 4 of 51**, each carrying an `injection` field with a `payload_id`,
`taxonomy_class` (S1 direct override through S4 obfuscated, matching the published four-class
log-substrate injection taxonomy the plan cites), `artifact_kind`, `source_location`, and the
literal `span_excerpt`:

| Case | Taxonomy | Payload lives in |
|---|---|---|
| `cert_rotation__adv_s1_direct_override` | S1 | an XML comment inside the SAMLResponse |
| `wrong_issuer__adv_s2_persona_hijack` | S2 | the HAR's captured User-Agent header |
| `clock_skew__adv_s3_context_manipulation` | S3 | the narrative body |
| `assertion_expired__adv_s4_obfuscated` | S4 | base64 inside an attribute adjacent to the SAMLResponse |

Only S3's payload sits in a location any current job's prompt actually reads (Job A's narrative
subject/body). See `docs/THREAT_MODEL.md` T2 for what that means for measured injection
resistance, and do not read "4 adversarial cases" as "4 cases that reached a model with a live
injection attempt", only one did.

**Two cases with no SAMLResponse at all.** `negative_control` sets `no_saml_response_reason`
explicitly: the IdP rejected the credential before producing a SAMLResponse (the login itself
failed, e.g. wrong password), so no check in `desk/verify/checks/` has anything to run against.
Correct behavior is `verify_state == "no_saml_response"`, never a fabricated check result, and
`desk/pipeline.py` handles this as a first-class branch rather than an error path. This is the
system's negative control: a workflow that always finds a federation fault would be worthless,
and `negative_control` exists to prove this one does not.

**Two cases that expect a parse failure**, `truncated_response` and `double_encoded_response`,
both flagged `expects_parse_failure: true` in the manifest. Correct behavior is a clean,
named rejection (`verify_state == "parse_error"`), not a crash and not a guessed diagnosis.

## The identity provider is Keycloak, not Entra, Okta, or Ping

Every artifact in this corpus was produced by a real, self-hosted Keycloak instance. Any
vendor-specific quirk named anywhere in this project's documentation or prompts is, at most,
modeled from public documentation and must be labeled as modeled. No claim of Entra, Okta, or
Ping production experience is made or should be inferred from this corpus.

## Reproducibility

`corpus/MANIFEST.json` records a checksum per artifact alongside its label. `make corpus-verify`
checks every checksum and confirms every `fault_id` maps to at least one check in `desk/verify`
capable of detecting it. The generator (`harness/generate.py`) is committed, so the corpus can be
regenerated from scratch given a running Keycloak instance, and diffed against the committed
version, though the committed corpus itself is what every published number in
`docs/MEASUREMENTS.md` was run against.
