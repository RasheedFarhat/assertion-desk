# Phase 1 — deterministic verifier notes

**Status: PASS.** All ~20 checks (plan §27) run against real artifacts and return a
correct six-state result, including `not_verified` when a check's required evidence is
absent. 61 tests pass across the repo (3 Phase 0 + 58 Phase 1).

## What was built

- **`desk/verify/parsed.py`** — a hardened, defused-XML parser (`resolve_entities=False,
  no_network=True, huge_tree=False`) that turns raw SAMLResponse bytes into a
  `ParsedSamlResponse`/`ParsedAssertion` pair covering every field the check catalogue
  needs: IDs, issuer, NameID + format, SubjectConfirmation method, SCD InResponseTo /
  NotOnOrAfter / Recipient, Conditions window, Audience list, signed/encrypted flags,
  and attribute names (duplicates kept as-is — "that's data, not a bug").
- **`desk/verify/context.py`** — `VerificationContext`: the SP's own known config
  (`sp_entity_id`, `acs_url`, `idp_entity_id`, always supplied) plus optional evidence
  that may or may not be available for a given case (`trusted_cert_pem`,
  `in_response_to_expected`, `sp_clock`, `evaluation_time`).
- **`desk/verify/checks/`** — 20 checks across 9 modules (signature, cert, issuer,
  audience, destination, inresponseto, timing, subject, status, attributes,
  encryption), each `(parsed, ctx) -> CheckResult`, collected in `ALL_CHECKS`.
- **`desk/verify/verifier.py`** — `run_all_checks()` orchestrates the catalogue,
  converts a parse failure or a single check's unexpected exception into a reported
  result rather than a crash, and never lets one broken check take the whole run down.
- **`desk/verify/gaps.py`** — turns NOT_VERIFIED results into a closed-enum artifact
  request (`har | saml_response | idp_metadata | sp_clock | sp_request_log`), asserted
  closed so a future typo in the mapping table fails loudly. This constrains Phase 4's
  Job B (the missing-evidence-request writer) to only ever ask for something real.

The check catalogue (20, not the originally-sketched 21 — a planned SIG-03 "at least
one signature present" check was dropped as redundant with SIG-01/02's own NOT_VERIFIED
branches):

```
SAML-SIG-01/02      response/assertion signature verifies against a pinned cert
SAML-CERT-01/02     pinned cert validity window / embedded-vs-pinned thumbprint match
SAML-ISS-01/02      response/assertion Issuer matches the configured IdP entity ID
SAML-AUD-01         SP entity ID present in Audience
SAML-DEST-01        Response Destination matches the configured ACS URL
SAML-RECIP-01       SubjectConfirmationData Recipient matches the configured ACS URL
SAML-INRESP-01/02   response/SCD InResponseTo matches the SP's expected value
SAML-SKEW-01        Response IssueInstant within tolerance of the SP's own clock
SAML-COND-01/02     Conditions / SCD windows not expired, evaluated against ctx.now()
SAML-NAMEID-01/02   NameID present / Format recognized
SAML-SCM-01         SubjectConfirmation Method is the bearer method
SAML-STATUS-01      IdP reported Success
SAML-ATTR-01        no duplicate Attribute Name values (Keycloak's known quirk)
SAML-ENC-01         assertion is plaintext (encrypted → not_applicable, not a failure)
```

## The hard rule that shaped the design

**No pinned cert means NOT_VERIFIED, full stop.** Signature and cert checks never fall
back to trusting whatever certificate happens to be embedded in the response, even if
the raw math would validate against it. An embedded `<X509Certificate>` is part of the
untrusted message; only an out-of-band pinned cert (fetched from the IdP's real
metadata endpoint, per Phase 0) counts as evidence. Absence of that evidence produces
`not_verified`, never a guess.

## Two real bugs caught before they shipped

- **lxml element truthiness.** `elem_a or elem_b` in `checks/cert.py`'s embedded-cert
  lookup silently fell through to `elem_b` even when `elem_a` correctly matched a
  childless leaf element (`<X509Certificate>text</X509Certificate>` has no child
  elements, so lxml's legacy `Element.__bool__` reports it falsy). Fixed with explicit
  `is None` checks everywhere an lxml `.find()` result is used in a boolean position.
  Caught by code review while writing, not by a failing test.
- **A stale hardcoded `evaluation_time` in the debug CLI** (`verifier.py`'s
  `__main__` block) pinned "now" to midnight on the fixture's own capture date, which
  is earlier than the fixture's real ~06:52 UTC timestamps, producing spurious "not yet
  valid" failures. Removed the pin; the CLI now judges against real wall-clock time via
  `ctx.now()`'s own default, with a comment explaining why a live debug tool shouldn't
  freeze time the way a test fixture does.

## The property tests, and the premise that was wrong

The plan's Phase 1 exit criterion calls for "a property test that no check ever returns
`verified` when its required artifact is missing." The first draft of that test
asserted something stronger than the plan actually requires: that a context missing
optional evidence, or a response missing its Assertion, should zero out *every* check
in the whole catalogue. That's wrong. `SAML-ISS-01`, `SAML-DEST-01`, `SAML-AUD-01`, and
several others correctly and honestly verify using only the SP's own always-known
identity config (`sp_entity_id`, `acs_url`, `idp_entity_id`) — that config isn't
"evidence that can be missing" in the same sense a pinned cert or an SP clock is.

The fix: two named, scoped properties instead of one blanket one.

- `test_evidence_dependent_check_never_verifies_without_its_evidence` — parametrized
  over the 7 checks whose VERIFIED branch specifically requires optional evidence
  (`SIG-01/02`, `CERT-01/02`, `INRESP-01/02`, `SKEW-01`), run against a context that
  supplies only the SP's own identity config. Every one of them is `not_verified`.
- `test_assertion_scoped_check_never_verifies_on_an_empty_response` — parametrized
  over the 13 checks that require a parsed Assertion to say anything at all, run
  against a hand-built Response with no Assertion element but a fully-populated
  context otherwise. Every one of them is `not_verified`; the 5 Response-level checks
  that don't need an Assertion (`CERT-01`, `ISS-01`, `DEST-01`, `SKEW-01`, `STATUS-01`)
  are deliberately excluded, because verifying them here is correct, not a leak — a
  response that looks right but carries no assertion at all is real, useful
  information a support engineer wants to see, not a gap to hide.

This was a design bug in the test, not in the checks or the verifier. 38 of 40 tests
were already green when it was caught; the fix only touched test assertions.

## Verified end to end against real fixtures

```
.venv/bin/python3 -m desk.verify.verifier tests/verify/phase0_fixtures/good_saml_response.xml \
  tests/verify/phase0_fixtures/good_trusted_cert.txt
# counts: verified 14, failed 2 (Conditions/SCD legitimately expired -- the fixture is old),
#         review_required 1 (ATTR-01, Keycloak's duplicate-Role quirk), not_verified 3

.venv/bin/python3 -m desk.verify.verifier tests/verify/phase0_fixtures/faulted_saml_response.xml \
  tests/verify/phase0_fixtures/faulted_stale_trusted_cert.txt
# counts: verified 11, failed 5 (adds SIG-01/02 + CERT-02 for the rotated-key fault), review_required 1, not_verified 3
```

Run the suite:

```
.venv/bin/python3 -m pytest tests/verify/ -v
```

## Decision

Phase 1 exit criteria (plan §27) are met: all 20 checks run against real artifacts,
return correct six-state results, `not_verified` is structurally impossible to
mistake for `verified` (enforced at `CheckResult.__post_init__`), and the two
scoped property tests hold. Proceeding to Phase 2 (custody / de-fanging).
