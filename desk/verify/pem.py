"""One tiny shared helper: Keycloak's metadata and admin API hand back bare base64 DER,
not full PEM. Both xmldsig.py (signature verification) and checks/cert.py (validity
window, thumbprint) need to turn that into something `cryptography` can load, so it lives
here once instead of twice."""

from __future__ import annotations


def wrap_pem(cert_body: str) -> str:
    cert_body = cert_body.strip()
    if "BEGIN CERTIFICATE" in cert_body:
        return cert_body
    return "-----BEGIN CERTIFICATE-----\n" + cert_body + "\n-----END CERTIFICATE-----\n"
