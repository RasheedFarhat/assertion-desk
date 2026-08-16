"""Independent XML-DSig verification for captured SAMLResponse artifacts.

Deliberately does not reuse python3-saml's validation path (harness/capture/sp_app.py).
The thing that produces the artifact (the SP) and the thing that judges it (this module)
must not share code, or a bug in one silently validates the other.

Verifies the signature over the top-level <Response> if present, and independently over
each <Assertion>, using signxml + cryptography, with defusedxml doing the XML parsing so
untrusted input can't trigger XXE / entity expansion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import defusedxml.ElementTree as DET
from cryptography import x509
from lxml import etree as LET
from signxml import XMLVerifier
from signxml.exceptions import InvalidSignature

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}


@dataclass
class SignatureCheckResult:
    element: str  # "Response" or "Assertion"
    element_id: str | None
    verified: bool
    reason: str
    signer_cert_subject: str | None = None


@dataclass
class VerificationReport:
    checks: list[SignatureCheckResult] = field(default_factory=list)

    def all_verified(self) -> bool:
        return len(self.checks) > 0 and all(c.verified for c in self.checks)


def _defused_parse_check(raw_bytes: bytes) -> None:
    """Fail fast (and safely) on malicious XML before doing anything else with it."""
    DET.fromstring(raw_bytes)  # raises on entity expansion / XXE-shaped input; discards result


def _lxml_tree(raw_bytes: bytes) -> LET._ElementTree:
    parser = LET.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return LET.fromstring(raw_bytes, parser=parser).getroottree()


def verify_saml_response(raw_bytes: bytes, trusted_cert_pem: str | None = None) -> VerificationReport:
    """Independently verify every XML-DSig <Signature> found in a captured SAMLResponse.

    This checks *cryptographic validity of the signature* only -- it does NOT check
    Audience, Destination, NotOnOrAfter, etc. Those are separate checks in desk/verify/
    (Phase 1). Keeping signature verification isolated means a signature-verified-but-
    semantically-wrong assertion is still distinguishable from a signature that plain
    doesn't verify.

    trusted_cert_pem, when supplied, pins verification to a specific certificate fetched
    out-of-band from the IdP's metadata endpoint (see harness/capture/keycloak_admin.py).
    This is deliberate and is the architecturally correct default: an assertion's embedded
    <X509Certificate> is part of the untrusted message and proves nothing about identity
    on its own (SAML-CERT-02's whole reason to exist is catching exactly the case where
    the embedded cert differs from the one the IdP's metadata actually advertises). It
    also sidesteps a real interop wrinkle hit while building this: Keycloak's dev-mode
    self-signed realm cert is X509v1 with no extensions, and signxml's default embedded-
    cert trust path requires v3 semantics (basicConstraints/keyUsage) to reason about
    chain trust, so it rejects a v1 leaf cert outright even when the signature is valid.
    Pinning to a specific known cert bypasses that chain-trust question entirely, which is
    also just what a real IdP integration should be doing anyway.
    """
    _defused_parse_check(raw_bytes)
    tree = _lxml_tree(raw_bytes)
    root = tree.getroot()

    report = VerificationReport()

    # Response-level signature (Keycloak signs both the Response and each Assertion).
    response_sig = root.find("ds:Signature", NS)
    if response_sig is not None:
        report.checks.append(_verify_element(root, "Response", root.get("ID"), trusted_cert_pem))

    for assertion in root.findall("saml:Assertion", NS):
        assertion_sig = assertion.find("ds:Signature", NS)
        if assertion_sig is not None:
            report.checks.append(_verify_element(assertion, "Assertion", assertion.get("ID"), trusted_cert_pem))

    return report


def _pem_wrap(cert_body: str) -> str:
    cert_body = cert_body.strip()
    if "BEGIN CERTIFICATE" in cert_body:
        return cert_body
    return "-----BEGIN CERTIFICATE-----\n" + cert_body + "\n-----END CERTIFICATE-----\n"


def _verify_element(element, kind: str, element_id: str | None, trusted_cert_pem: str | None) -> SignatureCheckResult:
    verify_kwargs = {"expect_references": 1}
    if trusted_cert_pem is not None:
        verify_kwargs["x509_cert"] = _pem_wrap(trusted_cert_pem)
    try:
        XMLVerifier().verify(element, **verify_kwargs)
        # VerifyResult (signxml 5.x) exposes signed_data/signed_xml/signature_xml/
        # signature_key -- no parsed cert object. When we pinned a trusted cert, we
        # already hold it, so report its subject directly rather than re-deriving it.
        subject = None
        if trusted_cert_pem is not None:
            cert = x509.load_pem_x509_certificate(_pem_wrap(trusted_cert_pem).encode())
            subject = cert.subject.rfc4514_string()
        reason = "signature valid, digest matches"
        reason += ", verified against pinned trusted cert" if trusted_cert_pem else ", trusted embedded cert (no pin supplied)"
        return SignatureCheckResult(
            element=kind,
            element_id=element_id,
            verified=True,
            reason=reason,
            signer_cert_subject=subject,
        )
    except InvalidSignature as exc:
        return SignatureCheckResult(
            element=kind, element_id=element_id, verified=False, reason=f"invalid signature: {exc}"
        )
    except Exception as exc:  # noqa: BLE001 -- any parse/crypto failure is a verification failure, not a crash
        return SignatureCheckResult(
            element=kind, element_id=element_id, verified=False, reason=f"verification error: {exc}"
        )


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "harness/capture/captured/saml_response.xml"
    cert_path = sys.argv[2] if len(sys.argv) > 2 else "harness/capture/idp-cert.txt"
    with open(path, "rb") as f:
        data = f.read()
    try:
        with open(cert_path) as f:
            trusted_cert = f.read()
    except FileNotFoundError:
        trusted_cert = None
    report = verify_saml_response(data, trusted_cert_pem=trusted_cert)
    for check in report.checks:
        status = "VERIFIED" if check.verified else "FAILED"
        print(f"[{status}] {check.element} (id={check.element_id}): {check.reason}")
        if check.signer_cert_subject:
            print(f"           signer: {check.signer_cert_subject}")
    print()
    print("all_verified:", report.all_verified())
