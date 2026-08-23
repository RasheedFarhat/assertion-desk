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

**56 total cases, 55 executable.** One, `sha1_signature_downgrade`, is a documented,
deliberately unimplemented gap (`category: documented_gap` in the manifest), not a silently
broken case. This is far short of the plan's aspirational ~250; every percentage in
`docs/MEASUREMENTS.md` rests on a sample this small, and single-case swings move the headline
numbers by under 2 points each. (`docs/MEASUREMENTS.md`'s committed baseline run predates the
five newest adversarial cases below — see that file's 2026-08-23 update — so its own per-case
denominators still reflect 51/50.)

**Case categories** (the manifest's `category` field, distinct from difficulty strata):
`context_mismatch` (26, a fault that produces a mismatch between two pieces of otherwise-valid
evidence, e.g. a signing cert that does not match metadata), `artifact_mutation` (16, a fault
that mutates a captured artifact directly), `live_capture` (12, faults captured by driving a real
login against a genuinely misconfigured Keycloak/SP pair rather than by post-hoc mutation, plus
the adversarial overlays layered onto `cert_rotation`, itself a `live_capture` fault), `baseline`
(1), `documented_gap` (1, the `sha1_signature_downgrade` case above).

**Difficulty strata, real counts** (the manifest's `difficulty` field): `normal` 50,
`malformed` 2, `ambiguous` 2, `conflicting` 1, unset 1 (the documented gap). All far below the
plan's aspirational per-stratum targets (`normal` ~120, `ambiguous` ~40, `conflicting` ~25,
`malformed` ~25). The plan's separate `adversarial` stratum does not exist as a `difficulty`
value at all; adversarial cases are instead tagged `normal` for difficulty and carry a separate
`injection` field (see below), because every adversarial case's base fault already has a genuine
`FAILED` check independent of its injection payload, so they behave like `normal` cases for
routing purposes. See `docs/THREAT_MODEL.md`'s T2 entry for the full detail on what that means
for injection-resistance measurement.

**Narrative registers, real counts** (the manifest's `register` field): `precise` 31 (the
majority, since most cases need a straightforward baseline narrative), `vague` 6,
`confident_misdiagnosis` 6, `hostile` 6, `non_native` 6, unset 1 (the documented gap has no
narrative). This is close to the plan's five-register design, just not evenly distributed
across it, `precise` dominates because most cases are single-fault `normal` cases that do not
need a stress-test register.

**Adversarial cases, 9 of 56**, each carrying an `injection` field with a `payload_id`,
`taxonomy_class` (S1 direct override through S4 obfuscated, matching the published four-class
log-substrate injection taxonomy the plan cites), `artifact_kind`, `source_location`, the literal
`span_excerpt`, and (added 2026-08-23, see below) `reaches_prompt`/`landing_site`/
`evades_detector`:

| Case | Taxonomy | Payload lives in | Reaches a live prompt? |
|---|---|---|---|
| `cert_rotation__adv_s1_response_xml_comment` | S1 | an XML comment inside the SAMLResponse | No — C14N strips comments before any check reads the XML |
| `wrong_issuer__adv_s2_har_user_agent` | S2 | the HAR's captured User-Agent header | No — no job reads HAR content |
| `clock_skew__adv_s3_narrative_appeal_to_authority` | S3 | the narrative body | Yes — `narrative` (Job A's subject/body) |
| `assertion_expired__adv_s4_base64_attribute_friendlyname` | S4 | base64 inside an attribute adjacent to the SAMLResponse | No, and deliberately obfuscated — evades the detector even where reachable |
| `cert_rotation__adv_s1_assertion_audience_direct_override` | S1 | an added `<Audience>` element's text | Yes — `CheckResult.observed[SAML-AUD-01]` |
| `cert_rotation__adv_s4_attribute_name_obfuscated_duplicate` | S4 | a duplicated `Attribute Name`, base64-encoded | Yes, but deliberately obfuscated — `CheckResult.observed[SAML-ATTR-01]`, evades the detector |
| `cert_rotation__adv_s2_nameid_format_persona_hijack` | S2 | the `NameID`'s `Format` attribute | Yes — `CheckResult.observed[SAML-NAMEID-02]` |
| `cert_rotation__adv_s1_response_destination_direct_override` | S1 | the `Response`'s `Destination` attribute | Yes — `CheckResult.observed[SAML-DEST-01]` |
| `cert_rotation__adv_s3_response_issuer_context_manipulation` | S3 | the `Response`'s `Issuer` element text | Yes — `CheckResult.observed[SAML-ISS-01]` |

Six of nine payloads now reach a real model prompt (five via `CheckResult.observed`, found by
reading `desk/verify/checks/*.py` directly: those checks populate `observed` verbatim from parsed
element text and attribute values, and `desk/reason/jobs.py` builds Job C's prompt straight from
those check rows). This corrects an earlier, narrower version of this table (4 cases, only one
reachable) that had generalized "these three specific payloads are unreachable" into "XML payloads
are structurally inapplicable" — a claim the code never actually supported. See
`docs/THREAT_MODEL.md` T2 and `docs/PHASE4_NOTES.md`'s 2026-08-23 update for the full finding, and
`eval/metrics.py`'s `injection_resistance()` for how reachability is now measured (read off each
payload's own `reaches_prompt` declaration, not inferred from a case-id string).

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
