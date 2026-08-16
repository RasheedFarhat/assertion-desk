"""Phase 0 go/no-go tests (plan §27): verification passes on a real good artifact and
fails, for the right reason, on a real faulted one.

The fixtures here are not authored. They are frozen output of:
  1. harness/capture/keycloak_admin.py  -- provisioned a real Keycloak realm/SAML client
  2. harness/capture/playwright_login.py -- drove a real browser login, capturing a real HAR
     and a real signed SAMLResponse (good_saml_response.xml / real_login.har)
  3. A real key rotation performed against the running Keycloak (a new higher-priority
     rsa-generated key provider), followed by a second real login captured after rotation
     (faulted_saml_response.xml), verified against the pre-rotation cert
     (faulted_stale_trusted_cert.txt) -- exactly the SAML-CERT-02 "cert thumbprint doesn't
     match metadata" fault class from the plan's ~20-fault catalogue.

See docs/PHASE0_NOTES.md for the full narrative and the exact commands used to produce
these fixtures, so they can be regenerated from scratch against a fresh Keycloak.
"""

from __future__ import annotations

import os

from desk.verify.xmldsig import verify_saml_response

FIXTURES = os.path.join(os.path.dirname(__file__), "phase0_fixtures")


def _read(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def _read_text(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


def test_good_artifact_verifies():
    saml_response = _read("good_saml_response.xml")
    trusted_cert = _read_text("good_trusted_cert.txt")

    report = verify_saml_response(saml_response, trusted_cert_pem=trusted_cert)

    assert report.checks, "expected at least one <Signature> to be found and checked"
    assert report.all_verified(), [
        (c.element, c.verified, c.reason) for c in report.checks
    ]
    kinds = {c.element for c in report.checks}
    assert kinds == {"Response", "Assertion"}, "expected both Response- and Assertion-level signatures"


def test_faulted_artifact_fails_for_the_right_reason():
    """The assertion was signed with a rotated key; the trusted cert is the pre-rotation
    one, exactly modeling a customer whose cached IdP metadata is stale. Verification
    must fail, and it must fail because the signature doesn't validate against that cert
    -- not crash, not silently pass, not fail for an unrelated reason."""
    saml_response = _read("faulted_saml_response.xml")
    stale_trusted_cert = _read_text("faulted_stale_trusted_cert.txt")

    report = verify_saml_response(saml_response, trusted_cert_pem=stale_trusted_cert)

    assert report.checks, "expected at least one <Signature> to be found and checked"
    assert not report.all_verified()
    for check in report.checks:
        assert check.verified is False
        assert "signature" in check.reason.lower()


def test_real_har_was_captured_and_is_nonempty():
    """Not a signature test -- confirms the other Phase 0 artifact (a real browser-driven
    HAR capture) exists and has real content, not a stub."""
    path = os.path.join(FIXTURES, "real_login.har")
    assert os.path.exists(path)
    assert os.path.getsize(path) > 100_000  # a real multi-request login HAR, not a placeholder

    import json

    with open(path) as f:
        har = json.load(f)
    entries = har["log"]["entries"]
    assert len(entries) > 5
    urls = [e["request"]["url"] for e in entries]
    assert any("saml/acs" in u for u in urls), "expected the captured HAR to include the real ACS POST"
