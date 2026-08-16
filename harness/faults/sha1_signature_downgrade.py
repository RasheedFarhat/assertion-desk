"""sha1_signature_downgrade -- DOCUMENTED_GAP. A real, well-documented SAML failure class
(the assertion is signed using RSA-SHA1 or a SignatureMethod weaker than the deployment
should accept) that this catalogue does not build an executable case for, because doing
so honestly would require a check this verifier does not have.

desk/verify/checks/signature.py (SAML-SIG-01/02) reports whether a signature
cryptographically verifies against the pinned certificate -- it says nothing about which
digest or signature algorithm URI was used to produce it. There is no
SAML-SIG-ALGORITHM-01 check in the current catalogue, and forging a case that *should*
flag "signed, but with a weak algorithm" would only prove the verifier doesn't notice --
which is true, and belongs in docs/LIMITATIONS.md, not in the corpus dressed up as a
detected case.

Building this properly would mean: (1) adding a check that inspects
ds:SignatureMethod/@Algorithm against an allowed-algorithm list, (2) a mutation that
re-signs the real captured assertion with a SHA-1 digest (not just relabels the existing
SHA-256 signature's algorithm URI, which would make the signature fail to verify for the
wrong reason and produce a misleading SIG-02 FAILED instead of the intended algorithm
finding). Recorded here so the gap is visible in the fault count rather than silently
absent from it.
"""

from __future__ import annotations

from harness.faults.base import FaultCategory, FaultSpec

FAULT = FaultSpec(
    fault_id="sha1_signature_downgrade",
    category=FaultCategory.DOCUMENTED_GAP,
    description=(
        "Assertion signed with a weak digest/signature algorithm (e.g. RSA-SHA1). No "
        "check in desk/verify/checks/ inspects ds:SignatureMethod/@Algorithm -- "
        "SAML-SIG-01/02 only report whether the signature cryptographically verifies, "
        "not what algorithm produced it."
    ),
    gap_reason=(
        "No SAML-SIG-ALGORITHM-01 check exists in the catalogue. Building an executable "
        "case for this fault without first adding that check would either be undetectable "
        "by design (proving nothing) or would require re-signing the real captured "
        "assertion with a genuine SHA-1 signature, which needs Keycloak's realm signing "
        "algorithm reconfigured (LIVE_CAPTURE) rather than a context override or a simple "
        "byte mutation -- deferred as future generator capacity, not attempted here."
    ),
)
