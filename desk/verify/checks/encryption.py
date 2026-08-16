"""SAML-ENC-01: whether the assertion is encrypted, and an honest admission of what this
system can and cannot do about it. Keycloak's default SAML client (and every Phase 0
capture) ships plaintext, signed assertions -- this system does not implement decryption,
so an encrypted assertion is not a failure to hide, it's a capability boundary to report."""

from __future__ import annotations

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import ParsedSamlResponse


def check_not_encrypted(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-ENC-01", assurance=Assurance.NOT_VERIFIED, observed=None,
            expected="a plaintext (unencrypted) Assertion", reason="response contains no parsed Assertion",
        )
    if parsed.assertions[0].is_encrypted:
        return CheckResult(
            check_id="SAML-ENC-01", assurance=Assurance.NOT_APPLICABLE, observed="assertion contains EncryptedData",
            expected="a plaintext (unencrypted) Assertion",
            reason="assertion is encrypted; this verifier does not implement SAML assertion "
            "decryption, so its remaining checks cannot inspect the encrypted content",
        )
    return CheckResult(
        check_id="SAML-ENC-01", assurance=Assurance.VERIFIED, observed="plaintext assertion",
        expected="a plaintext (unencrypted) Assertion", reason="assertion is not encrypted; downstream checks can inspect it directly",
    )
