"""SAML-CERT-01 / SAML-CERT-02: properties of the pinned trusted certificate itself,
independent of whether any given signature verifies against it.

These are deliberately separate from SAML-SIG-01/02. A signature can be cryptographically
valid using a certificate that is, itself, expired -- that's a real and distinct failure
mode (the org's IdP admin let the signing cert lapse) and deserves its own check ID rather
than being folded into "signature verified: yes/no".

CERT-02 (thumbprint match) compares the response's *embedded* signing certificate against
the pinned trusted certificate by SHA-256 fingerprint. This is the SAML-CERT-02 fault class
proven in Phase 0 (a rotated Keycloak signing key produces an embedded cert whose thumbprint
no longer matches a stale pinned cert)."""

from __future__ import annotations

import hashlib

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from lxml import etree as LET

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import NS, ParsedSamlResponse
from desk.verify.pem import wrap_pem


def _load_trusted_cert(ctx: VerificationContext) -> x509.Certificate | None:
    if ctx.trusted_cert_pem is None:
        return None
    return x509.load_pem_x509_certificate(wrap_pem(ctx.trusted_cert_pem).encode())


def check_cert_validity_window(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    cert = _load_trusted_cert(ctx)
    if cert is None:
        return CheckResult(
            check_id="SAML-CERT-01",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected="a pinned IdP signing certificate",
            reason="no trusted_cert_pem supplied",
        )

    now = ctx.now()
    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc
    observed = f"valid {not_before.isoformat()} to {not_after.isoformat()}"

    if not_before <= now <= not_after:
        return CheckResult(
            check_id="SAML-CERT-01",
            assurance=Assurance.VERIFIED,
            observed=observed,
            expected=f"validity window containing {now.isoformat()}",
            reason="pinned certificate is within its validity window",
        )

    return CheckResult(
        check_id="SAML-CERT-01",
        assurance=Assurance.FAILED,
        observed=observed,
        expected=f"validity window containing {now.isoformat()}",
        reason="pinned certificate is expired or not yet valid" + (" (expired)" if now > not_after else " (not yet valid)"),
    )


def _embedded_cert_der(parsed: ParsedSamlResponse, kind: str) -> bytes | None:
    """Find the ds:X509Certificate embedded in the Response or (single supported) Assertion
    signature block and return its raw base64-decoded DER bytes, or None if absent."""
    import base64

    if kind == "Response":
        # lxml elements are falsy based on child count, not identity -- `a or b` would
        # wrongly fall through to b even when `a` correctly matched a childless leaf
        # element like X509Certificate, so this is `is not None`, not `or`.
        el = parsed.root.find("ds:Signature//ds:X509Certificate", NS)
        if el is None:
            el = parsed.root.find("ds:Signature/ds:KeyInfo/ds:X509Data/ds:X509Certificate", NS)
    else:
        assertion = parsed.root.find("saml:Assertion", NS)
        el = None if assertion is None else assertion.find(
            "ds:Signature/ds:KeyInfo/ds:X509Data/ds:X509Certificate", NS
        )
    if el is None or not el.text:
        return None
    return base64.b64decode(el.text.strip())


def check_cert_thumbprint(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    trusted = _load_trusted_cert(ctx)
    if trusted is None:
        return CheckResult(
            check_id="SAML-CERT-02",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected="a pinned IdP signing certificate to compare against",
            reason="no trusted_cert_pem supplied",
        )

    embedded_der = _embedded_cert_der(parsed, "Assertion")
    if embedded_der is None:
        embedded_der = _embedded_cert_der(parsed, "Response")
    if embedded_der is None:
        return CheckResult(
            check_id="SAML-CERT-02",
            assurance=Assurance.NOT_VERIFIED,
            observed=None,
            expected="an embedded ds:X509Certificate in the response",
            reason="response has no embedded signing certificate to compare",
        )

    trusted_thumb = trusted.fingerprint(hashes.SHA256()).hex(":")
    embedded_thumb = hashlib.sha256(embedded_der).hexdigest()
    embedded_thumb_colon = ":".join(embedded_thumb[i : i + 2] for i in range(0, len(embedded_thumb), 2))

    if trusted_thumb == embedded_thumb_colon:
        return CheckResult(
            check_id="SAML-CERT-02",
            assurance=Assurance.VERIFIED,
            observed=embedded_thumb_colon,
            expected=trusted_thumb,
            reason="embedded signing certificate thumbprint matches the pinned trusted certificate",
        )

    return CheckResult(
        check_id="SAML-CERT-02",
        assurance=Assurance.FAILED,
        observed=embedded_thumb_colon,
        expected=trusted_thumb,
        reason="embedded signing certificate thumbprint does not match the pinned trusted certificate "
        "(stale metadata after a key rotation is the common real-world cause)",
    )
