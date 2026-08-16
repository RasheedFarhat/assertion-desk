# Phase 3 — corpus notes

**Status: PASS, with the honest headline being a real count, not the plan's aspirational
one.** The corpus has **51 manifest entries**, not ~250. Every one of them is either a
real artifact set with a verified, self-tested check outcome, or a named documented gap —
none is padding. 105 tests pass across the repo (3 Phase 0 + 58 Phase 1 + 35 Phase 2 + 9
Phase 3).

## Why 51, not ~250, and why that's the right number here

The plan's §23 sketch (`normal` ~120, `ambiguous` ~40, `conflicting` ~25, `adversarial`
~40, `malformed` ~25) assumed dozens of cases per stratum. That assumption doesn't survive
contact with how this corpus is actually grounded: every case's ground truth comes from a
real `FaultSpec` (a real Keycloak misconfiguration or a real, inspectable byte mutation),
not from a template the generator can crank out variations of on demand. There are 19
executable faults in the catalogue, full stop — inventing 100 more `normal`-stratum cases
would mean inventing fault mechanisms with no real artifact behind them, which is exactly
the manufactured-evidence failure mode this project's own truthfulness standard exists to
rule out (see `harness/faults/conflicting.py`'s docstring for the same reasoning applied
to the "two certs, neither matching" case that was *not* built).

What actually multiplies honestly is the **narrative register** axis (the same artifacts,
read through five differently-worded customer reports) and the **adversarial overlay**
axis (an injection payload layered on top of an already-verified case). Both were used:

- **22 base cases** — the 19 executable `ALL_FAULTS` entries (`sha1_signature_downgrade`
  excluded, it's `DOCUMENTED_GAP`) plus the 2 `ambiguous.py` cases plus the 1
  `conflicting.py` case, each at the `precise` narrative register, `case_id == fault_id`.
- **24 register variants** — a curated 6-fault "hero" subset (`cert_rotation`,
  `cert_expired`, `wrong_issuer`, `broken_signature`, `missing_nameid`, `clock_skew`,
  chosen to spread across `LIVE_CAPTURE`/`CONTEXT_MISMATCH`/`ARTIFACT_MUTATION` and
  across signature/cert/issuer/timing/nameid check families) × the 4 non-precise
  registers (`vague`, `confident_misdiagnosis`, `hostile`, `non_native`). Running all 19
  executable faults × 5 registers (95 cases) was considered and rejected: past the first
  half-dozen, an additional register variant on the same artifacts tests the narrative
  renderer, not the verifier or the corpus's evidentiary claim, and inflating the count
  that way would be exactly the kind of aspirational-target padding this note is arguing
  against.
- **4 adversarial overlays** — one per S1-S4 taxonomy class (`arXiv 2605.24421`), each
  layered onto one base case (§ below).
- **1 documented gap** — `sha1_signature_downgrade`, recorded with its `gap_reason`, no
  fabricated artifacts.

`malformed` isn't a separate stratum with its own count in this manifest; it's a property
two existing `ARTIFACT_MUTATION` faults already have (`truncated_response`,
`double_encoded_response`, both `expects_parse_failure=True`) rather than a bucket that
needed inventing more cases to fill.

**The honest comparison the plan itself asks for:** ~250 frozen, checksummed, regenerable
cases where every one traces to a real fault mechanism is a stronger evidentiary claim
than ~250 cases where most are narrative-only variations. 51/51 real is better than a
padded 250.

## `harness/generate.py` — what it does and the self-test discipline it enforces

One orchestrator, four passes (base cases, register variants, adversarial overlays,
documented gaps), each writing real files to `corpus/cases/<case_id>/` and accumulating
`corpus/MANIFEST.json`. The pass that matters most: **every case's real
`run_all_checks()` output is compared against its `FaultSpec`'s own
`expected_states`/`expects_parse_failure` before anything is written, and a mismatch is a
hard `SelfTestFailure`, not a warning.** This is automation of a discipline that was
already being done by hand during this phase — it's exactly what caught
`cert_rotation`'s undocumented `SAML-SIG-01`/`SAML-SIG-02` cascade (see
`harness/faults/cert_rotation.py`'s docstring) before this file existed. Automating it
means every future fault edit or corpus regeneration gets the same check for free.

On this run, **every one of the 50 executable cases passed self-test on the first try**
after the fixes already made earlier in this phase (the `cert_rotation` cascade, the
`LiveArtifacts`/`live_loader` interface). That's a real signal that the hand-verification
done case-by-case earlier in this phase (`ambiguous.py`, `conflicting.py`,
`cert_rotation.py`) was accurate, not that the self-test is toothless — it's the same
assertion path `harness/generate.py` runs, just automated.

## The `BASELINE` category addition and why

`harness/faults/base.py`'s `FaultCategory` gained a fifth value, `BASELINE`, used by
exactly one case (`conflicting.py`'s `duplicate_role_attributes`): the real Phase 0
capture, completely untouched, no transform of any kind. The real assertion's
`AttributeStatement` happens to carry six `Role` attributes with a repeated `Name` value
(a real IdP attribute-mapping quirk, not something this project injected), and
`SAML-ATTR-01` already reports `review_required` on exactly that artifact with zero
changes. Calling that `CONTEXT_MISMATCH` — the category's own name implies something
drifted or was overridden — would misdescribe what happened. Nothing drifted; the real
data was already conflicting. `BASELINE` names that honestly.

## The `LiveArtifacts`/`live_loader` interface fix

`LIVE_CAPTURE` faults originally carried only `live_dir: str | None`, a bare directory
name. That turned out to be an insufficient interface once `harness/generate.py` actually
needed to load files from it: `cert_rotation`'s directory holds four files playing three
different roles (a pre-rotation response kept only for Phase 0's own before/after
comparison, the real post-rotation response that IS the case, and two candidate certs
where only the stale one belongs in this case's context), and `negative_control`'s
directory holds a real HAR but deliberately zero `SAMLResponse` artifacts. A generic
"copy every file in `live_dir`" rule would have had to guess at each fault's shape.

Fixed by adding a `LiveArtifacts` `TypedDict` (`raw_saml_response`, `trusted_cert_pem`,
`har_path`, `no_saml_response_reason`) and a `live_loader: Callable[[], LiveArtifacts]`
field, with `FaultSpec.__post_init__` now requiring both `live_dir` and `live_loader`
together on any `LIVE_CAPTURE` fault. `cert_rotation.py` and `negative_control.py` each
got a small `_load()` implementing it. `harness/generate.py`'s `resolve_artifacts()` ends
up with exactly one code path per category, same as every other category, while each
fault module keeps full ownership of what its own capture directory means.

## The `cert_rotation` cascading-effect correction

Caught during this phase's hand-testing, before `harness/generate.py` existed:
`cert_rotation`'s original `target_check_ids=["SAML-CERT-02"]` was incomplete. With the
stale cert pinned, the response is genuinely signed with the *new* key, so
`SAML-SIG-01`/`SAML-SIG-02` also fail for real, not just the separate thumbprint
comparison. Fixed to name all three, matching `cert_expired.py`'s existing convention for
honestly naming cascading side effects rather than reporting only the "headline" check.
`SAML-CERT-02` stays the recorded root cause (the specific, actionable diagnosis); the two
signature failures are the same underlying mechanism restated, not independent findings.

## The HAR-duplication decision

`harness/capture/captured/login.har` is ~4MB. Most cases reuse it byte-for-byte — nothing
about a `CONTEXT_MISMATCH` fault or an XML-only `ARTIFACT_MUTATION` fault changes HAR
bytes. Copying it into all 51 case directories would have made `corpus/` roughly 200MB for
zero information gain. Decision: a case only gets a case-local `login.har` on disk when
its fault mechanism actually produced different HAR bytes — a `har_transform`
(`stripped_relaystate`, `wrong_binding`, and the two adversarial overlays that mutate HAR
headers or attach an `S2` payload to one) or a `LIVE_CAPTURE` fault with its own real
capture (`negative_control`). Every other case's `label.json` carries `har_ref:
"shared_baseline_har"` and the shared file gets exactly one entry in
`MANIFEST.json["shared_artifacts"]`, with its own sha256. Measured result:
**`corpus/` is 17MB total** (two duplicated ~4MB HARs plus 49 lightweight case
directories), not ~200MB. `tests/harness/test_corpus.py::test_har_ref_is_consistent_with_case_local_artifact`
pins the rule so a future case can't silently duplicate the HAR without a reason or skip
duplicating one that actually needs it.

## The adversarial overlay wiring

`harness/adversarial.py`'s four `S1`-`S4` payloads (from the `arXiv 2605.24421`
log-substrate taxonomy) are layered onto a base case's already-verified real artifacts,
not treated as a 21st fault class — see that module's own docstring for why that's the
correct modeling choice (an injection payload targets Job A/B/C and `desk/ground`'s veto,
which don't exist yet; it says nothing about what `desk/verify` concludes). Pairing
chosen and reasoned about in `harness/generate.py`'s `ADVERSARIAL_PLAN`:

| Payload | Base case | Why that base |
|---|---|---|
| S1 (XML comment) | `cert_rotation` | The project's own killer-demo pairing (plan §13); a real `LIVE_CAPTURE` response rather than a synthetic one |
| S2 (HAR User-Agent) | `wrong_issuer` | Needs exactly one real ACS POST entry in the HAR (`mutations._find_acs_post_entry` raises otherwise); `wrong_issuer`'s `CONTEXT_MISMATCH` HAR is the real, unmodified baseline. `negative_control`'s HAR has zero ACS POST entries and would fail this payload outright |
| S3 (narrative appeal to authority) | `clock_skew` | Any fault with a narrative works; `clock_skew` isn't a certificate finding at all, so "skip the certificate check" reads as a non sequitur closer to a real social-engineering attempt than a payload that happens to match its own base case |
| S4 (obfuscated, base64 in an Attribute) | `assertion_expired` | Needs an untouched `Attribute[0]` with no pre-existing `FriendlyName`; `assertion_expired` is `CONTEXT_MISMATCH` (unmodified XML), so that element is the real one |

Every one of the 4 overlay cases was **re-verified after injection** against the base
fault's own `expected_states`, and all 4 passed: the injected instruction, comment, or
obfuscated payload changed none of the deterministic verifier's conclusions. That's the
deterministic half of the injection-resistance claim proven now, at Phase 3. The other
half — whether the *model* complies with the injected instruction and whether
`desk/ground` then rejects that output — is Phase 4's job, not this one's; this phase can
only prove the floor the model would have to fall through.

## `harness/narratives/facts.py` — full coverage confirmed

`FAULT_NARRATIVE_FACTS` was extended this phase with `withheld_cert`, `withheld_clock`,
and `duplicate_role_attributes` (the `ambiguous.py`/`conflicting.py` cases, which sit
outside `ALL_FAULTS` but are real corpus cases a customer would have opened a ticket
about). Verified directly: 22 entries, exact 1:1 coverage against the union of all
fault-like `FaultSpec`s in the project (19 executable `ALL_FAULTS` + 2 `AMBIGUOUS_CASES` +
1 `CONFLICTING_CASES`), zero missing, zero extra.

## Known, named limitations carried into this phase (not fixed here, not hidden)

- **The "two certs, neither matching" conflicting case was not built.**
  `VerificationContext` has exactly one `trusted_cert_pem` field; it doesn't model a set
  of candidate certs. Faking that case would mean testing against an invented context
  shape the real verifier doesn't have. `duplicate_role_attributes` (real, `BASELINE`) is
  what the `conflicting` stratum got instead. See `harness/faults/conflicting.py`.
- **`sha1_signature_downgrade` has no executable case.** No `SAML-SIG-ALGORITHM-01` check
  exists in the catalogue; building one honestly means adding that check first, which is
  Phase 4+ scope, not a corpus-generation problem. Recorded as a `DOCUMENTED_GAP` manifest
  entry with its `gap_reason`, not silently dropped from the count.
- **RelayState and binding-type faults (`stripped_relaystate`, `wrong_binding`) have
  `no_check_coverage_reason` set, not `target_check_ids`.** Both live in the HAR/transport
  layer; no check in `desk/verify/checks/` reads either. Verification still runs to
  completion on their (unmodified) SAMLResponse; the corpus case exists to prove the
  *system* handles them (a real HAR-level fault with no check catalogue coverage),
  not to claim a check catches them.
- **Register-variant coverage is 6 of 19 executable faults, not all of them**, a
  deliberate scope decision explained above, not an oversight.

## Verification

```
.venv/bin/python3 -m harness.generate        # regenerates corpus/cases/ + corpus/MANIFEST.json
.venv/bin/python3 -m pytest tests/harness/ -v
.venv/bin/python3 -m pytest -q                # full repo: 105 passed
```

`tests/harness/test_corpus.py` checks: manifest-totals internal consistency; every
manifest artifact's sha256 matches the file on disk (and the shared baseline HAR's own
sha256 matches too); no base or documented-gap fault is silently absent from the
manifest; every `target_check_id` any case claims is drawn from the **real** canonical
check_id set (derived by actually running `run_all_checks` against the good baseline, not
hand-transcribed from `desk/verify/checks/` source — so a rename there is caught here
too); every non-gap case names at least one outcome kind
(`target_check_ids`/`expects_parse_failure`/`no_check_coverage_reason`); documented gaps
carry no fabricated artifacts; `har_ref` values are consistent with what's actually on
disk; and every adversarial case's `injection.payload_id` traces to a real
`ALL_PAYLOADS` entry.

## Decision

Phase 3 exit criteria (plan §27, adjusted per the honest-count reasoning above) are met:
a real, checksummed, regenerable corpus exists; every case's label is self-tested against
the actual deterministic verifier rather than hand-predicted and trusted; every fault ID
maps to a real, verifier-confirmed check_id or a named, honest reason it doesn't; and the
adversarial stratum's deterministic-verifier half is proven, not assumed. Proceeding to
Phase 4 (three Gemini reasoning jobs with enforced schemas, fixture recording and replay,
Ollama fallback, `desk/ground`'s grounding validator, and the first published accuracy /
refusal-correctness / injection-resistance / leakage / cost numbers — the plan's MVP
cutoff).
