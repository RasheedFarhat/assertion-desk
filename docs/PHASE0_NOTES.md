# Phase 0 — de-risking notes

**Status: PASS.** Both hard things the plan flagged as the real risk (plan §27, §34,
§36 condition 2) are proven working against real software, on the first working
session, well inside the four-session fallback trigger. Go.

## What was proven

1. **A real IdP.** Keycloak 26.7.0 + Postgres, brought up via `compose.yaml`
   (`--profile idp`), realm/SAML client/test user provisioned through the Admin REST
   API (`harness/capture/keycloak_admin.py`), not a hand-crafted realm-import JSON.
2. **A real SP.** A minimal Flask app (`harness/capture/sp_app.py`) using
   `python3-saml` (OneLogin), talking real SAML to real Keycloak.
3. **A real browser-driven login and HAR capture.** `harness/capture/playwright_login.py`
   drives headless Chromium through the actual login form and records a real HAR via
   Playwright's `record_har_path`. The captured `saml_response.xml` and `login.har` are
   not authored; they are what Keycloak and the browser actually produced.
4. **Independent XML-DSig verification.** `desk/verify/xmldsig.py` verifies the
   Response- and Assertion-level signatures using `signxml` + `cryptography`, with
   `defusedxml` gating the initial parse. It deliberately does not reuse `python3-saml`'s
   validation path, so the artifact producer and the artifact judge share no code.
5. **A real fault, injected and detected for the right reason.** A second RSA signing
   key was added to the realm via the Admin API with higher priority, making Keycloak
   rotate its active signing key. A fresh real login was captured under the new key.
   Verified against the *stale* (pre-rotation) trusted certificate, both signatures
   correctly fail. Verified against the *current* certificate (re-fetched from the
   realm's live metadata endpoint), both signatures correctly pass. This is the
   SAML-CERT-02 fault class from the plan's ~20-item catalogue, produced by causing it
   in real infrastructure rather than hand-writing a bad XML fixture.

Frozen proof of all of the above lives in `tests/verify/phase0_fixtures/` and is
exercised by `tests/verify/test_xmldsig_phase0.py`. Run it with:

```
.venv/bin/python3 -m pytest tests/verify/test_xmldsig_phase0.py -v
```

## Two real wrinkles hit, and how they were resolved

- **Keycloak 26.x moved `/health/ready` to the management port (9000), not the main
  HTTP port (8080).** `compose.yaml`'s healthcheck originally probed 8080 and reported
  `unhealthy` even though Keycloak was fully up and serving admin/token requests
  correctly. Fixed by pointing the healthcheck at port 9000 inside the container.
- **signxml (5.x) requires an X509v3 certificate with extensions to reason about
  embedded-cert chain trust, and rejects Keycloak's dev-mode self-signed realm cert
  outright because it's X509v1 with no extensions.** Rather than loosening signxml's
  trust logic, `verify_saml_response()` takes an explicit `trusted_cert_pem` and pins
  verification to a specific certificate fetched out-of-band from the realm's metadata
  endpoint. This sidesteps the v1/v3 question entirely and is also the architecturally
  correct behavior: an assertion's embedded `<X509Certificate>` is part of the untrusted
  message and proves nothing about identity on its own. This *is* what SAML-CERT-02
  exists to check in Phase 1 (does the signer match the IdP's advertised cert), so this
  wrinkle turned into the mechanism for the fault-detection proof rather than a detour.

## Known non-blocking issue, deliberately not fixed here

Keycloak's default SAML client emits one `<Attribute Name="Role">` element per realm
role instead of a single `Attribute` with multiple `AttributeValue` children.
`python3-saml`'s `get_attributes()` treats a duplicated `Name` as invalid and raises.
The minimal SP (`sp_app.py`) catches this so artifact capture and the demo login flow
aren't blocked by it, but the underlying behavior is real and worth keeping as a
candidate fault/edge case for the harness's catalogue later (Phase 3), not something to
paper over by loosening a library default.

## How to regenerate these fixtures from scratch

```
docker compose --profile idp up -d
.venv/bin/python3 harness/capture/keycloak_admin.py setup
.venv/bin/python3 harness/capture/sp_app.py &            # or run detached
.venv/bin/python3 harness/capture/playwright_login.py    # captures the "good" artifacts
# ... rotate a key via the Admin API (see PHASE0 git history / keycloak_admin.py) ...
.venv/bin/python3 harness/capture/playwright_login.py    # captures the "faulted" artifacts
```

## Decision

Per plan §27 / §36, Phase 0 is a genuine go/no-go. It passed on the first session.
Proceeding to Phase 1 (the full ~20-check deterministic verifier).
