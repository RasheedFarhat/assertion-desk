# Phase 2 — custody notes

**Status: PASS.** Typed secret and PII detection runs across HAR, XML, and free text;
placeholder substitution and custody records are in place; the scan fails closed on
every malformed-input case tried. 96 tests pass across the repo (3 Phase 0 + 58 Phase 1
+ 35 Phase 2).

## What was built

- **`desk/custody/findings.py`** — `FindingClass` (9 values, including
  `PLAINTEXT_CREDENTIAL`, an addition beyond the plan's original sketch, justified by a
  literal `password=alice_dev_only` in the real captured HAR), `Liveness`, `Action`
  (`replaced` / `dropped` / `recorded_only` — the third value is new this phase, see
  below), and the frozen `CustodyFinding` dataclass. No field on `CustodyFinding` can
  hold a raw value — there is no `value`/`raw`/`secret` field anywhere, a schema-level
  guarantee checked structurally in `tests/custody/test_custody.py`.
- **`desk/custody/placeholders.py`** — `placeholder_for()` derives a stable
  `{{PREFIX:hash8}}` token from the raw value's SHA-256, so the same secret always maps
  to the same placeholder within an artifact. `finding_class_for_placeholder()` (new
  this phase) reverses that mapping, needed by the cross-artifact sweep below.
- **`desk/custody/detectors/`** — five small, independent modules doing pattern-only
  classification: `cookies.py` (known session-cookie names plus an entropy/length
  fallback), `tokens.py` (JWT structural detection and expiry-based liveness),
  `credentials.py` (password field names, flow-artifact param names like
  `session_code`), `keys.py` (PEM blocks, AWS access keys, API-key field names),
  `pii.py` (email regex, known group/role attribute names from Keycloak's
  `<Attribute Name="Role">` quirk).
- **`desk/custody/scan.py`** — the orchestrator. `run_custody(kind, raw_bytes)`
  dispatches to `_scan_har` / `_scan_xml` / `_scan_text` and wraps every path in
  fail-closed exception handling: any internal error becomes `CustodyFailure`, never a
  silently empty result.
- **`desk/custody/record.py`** — `build_custody_record()` rolls a `CustodyResult`'s
  finding list into a `CustodyRecord`: a canonical-JSON SHA-256 hash (stable regardless
  of finding order), counts by finding class, and an `any_live_credential` flag. This is
  the object the plan's section 13 demo script's "custody record sha256: 4f2b…" line
  refers to, and it is built to hash-chain into a later `TraceEvent` the same way
  Control Plane's evidence ledger does.

## The custody / verifier scope boundary

The de-fanged copy `scan.py` returns exists for what leaves the deterministic-verifier
boundary — model prompts, persisted storage, logs. `desk/verify` always operates on an
artifact's ORIGINAL, unredacted bytes; it never reads this module's output. That
boundary is what makes `Action.RECORDED_ONLY` correct rather than a leak: SAML NameID
and group/role Attribute values are PII, but they're also verifier-required evidence
(`SAML-NAMEID-01/02` check NameID's presence and format; `SAML-ATTR-01` reads the
attribute values), and redacting them out of signed XML would break the exact
verification this project's core mechanism depends on. `scan_xml()` records both as
findings (for the data-minimization audit trail) but leaves them untouched in the
returned bytes.

This is safe specifically because none of the three planned Gemini reasoning jobs ever
receives raw XML. Re-reading plan §16 during this phase confirmed it directly: Job A
gets only the de-fanged customer narrative and subject; Job B gets the gap list, Job
A's facts, and a fixed catalogue; Job C gets check results (IDs, states, mismatched
values) plus Job A's facts, explicitly "**Not** the raw artifacts." NameID never reaches
a model prompt through any path in the architecture, so leaving it un-redacted in the
XML copy doesn't touch the T1 threat model at all — that copy's real consumers are
persisted storage, logs, and case-card display, not prompts.

A private key embedded in XML, by contrast, has no verifier dependency at all, so it
really is a stray secret and `scan_xml()` does redact it (`Action.REPLACED`) — checked
structurally rather than assumed impossible, since nothing in the real fixtures actually
contains one.

## Three real leakage bugs, found by an independent scanner and fixed

The plan's Phase 2 exit criterion requires leakage to be "verified by an independent
scanner rather than by the detector itself." Built one: extract known real secret
values directly from the original HAR fixture — cookie values by known name,
`session_code` from the structured query-string array, the literal password — using
plain dict/regex logic that shares no code path with `scan.py`, then substring-search
those exact values in the returned `defanged_bytes`. That scanner caught real bugs, not
hypothetical ones.

- **`request.queryString[]` was never scanned.** HAR carries a structured array
  parallel to (and redundant with) the URL's own query string. The URL was being
  redacted; the parallel array wasn't, so the same `session_code` leaked right next to
  its redacted twin. Fixed with `_scan_query_string_array()`.
- **`postData.params[]` was never scanned.** Same redundancy for form-urlencoded POST
  bodies: `.text` was being redacted, the parallel structured `.params[]` array wasn't.
  Fixed with `_scan_post_params_array()`.
- **An opaque token embedded in unlabeled HTML response body.** Keycloak's login flow
  echoes the same `session_code` value inside a later redirect's HTML response body,
  embedded in a login form's `action` URL with no field-name context and no
  JWT/PEM/email/AWS-key shape — nothing a standalone pattern rule can catch without
  becoming false-positive-prone. Fixed by adding a transient, function-scoped
  `known_values: dict[str, str]` map, populated every time any value is redacted
  anywhere during the primary per-entry HAR scan, followed by one final recursive sweep
  (`_sweep_known_values`) substituting any already-confirmed secret value wherever else
  it appears — subject to a 12-character floor to avoid coincidental short-substring
  matches. This is deliberately not new pattern detection; it's consistent redaction of
  a secret the scan has already proven is one.

After all three fixes, the independent scanner finds **0 of 7 known secret values**
leaking into the defanged HAR (down from 2 of 7 before), and total findings on the real
fixture rose from 18 to 22 as the newly-covered locations started being counted.

## A code-quality bug caught by re-reading, not by a test

An intermediate fix attempt had `_scan_header_array` call `findings.extend()` on a
value that was actually `list[tuple[CustodyFinding, str]]`, plus a dead
`_raw_value_for()` helper whose body unconditionally returned the whole header string —
wrong for any Cookie header carrying more than one `name=value` pair. Caught by
re-reading the file before running it, not by a failing test. Fixed by unifying all
three header-classify functions (`_classify_authorization_header`,
`_classify_cookie_header`, `_classify_set_cookie_header`) to the same
`tuple[str, list[tuple[CustodyFinding, str]]]` return shape, so the call site has one
code path instead of three slightly different ones.

## Verified end to end against real fixtures

```
HAR (tests/verify/phase0_fixtures/real_login.har):
  22 findings — 17 idp_session_cookie, 3 api_key, 2 plaintext_credential
  any_live_credential: True
  independent leakage scan: 0/7 known secrets survive

good_saml_response.xml:  7 findings (1 NameID + 6 group-membership), defanged bytes byte-identical to input
faulted_saml_response.xml: 7 findings, defanged bytes byte-identical to input
```

Run the suite:

```
.venv/bin/python3 -m pytest tests/custody/ -v
```

## Fail-closed, confirmed against 11 malformed-input cases

`tests/custody/test_custody.py`'s `MALFORMED_CASES` parametrization covers XXE entity
injection, non-XML garbage, unterminated XML (both `saml_response` and `idp_metadata`
kinds), non-UTF-8 bytes (HAR and both text kinds), a HAR missing `log.entries`, a HAR
whose `entries` is the wrong type, non-JSON HAR, and an unrecognized artifact kind — 11
cases total, every one raising `CustodyFailure` rather than returning a clean or partial
result. A twelfth test simulates an internal detector crash (not a malformed-input case
— a well-formed HAR whose internal handling breaks) via `monkeypatch`, confirming the
same fail-closed behavior for errors that have nothing to do with bad input.

## A known, named gap

`_scan_free_text` has no field-name context to work with, so a password stated in plain
prose ("my password is X") with no recognizable pattern shape (not JWT/PEM/email/AWS-key
shaped) is **not** detected — only password values arriving in a named field (a form
param, a JSON key) are caught. `test_narrative_bare_password_mention_is_a_known_gap`
pins this behavior explicitly rather than hiding it, so a future change to it is a
deliberate decision, not a silent regression in either direction. This belongs in
`docs/LIMITATIONS.md` once that file exists.

## Decision

Phase 2 exit criteria (plan §27) are met: zero secret patterns survive into the
de-fanged artifacts on the corpus so far, verified by a scanner with no shared code path
with the detector under test; the malformed-input suite fails closed in every case
tried; and `CustodyFinding`'s schema is confirmed, both structurally and behaviorally
against a real run, incapable of carrying a cleartext secret. Proceeding to Phase 3
(corpus: the remaining ~19 fault injectors, five narrative registers, and the
adversarial/conflicting/malformed strata).
