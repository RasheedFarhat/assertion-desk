"""AMBIGUOUS_CASES -- the "needed artifact is missing" stratum (plan §23), kept
deliberately separate from ALL_FAULTS in harness/faults/__init__.py rather than folded
into it. The 20 faults in ALL_FAULTS are exactly the plan's own named fault list (§23);
these two are a different concept layered on the same good, real, unmutated
SAMLResponse -- the artifact is fine, but the SP-side evidence needed to judge it was
never supplied. Correct system behavior on either is a precise, minimal evidence request
(Job B, Phase 4), never a guess dressed up as a diagnosis.

Both are CONTEXT_MISMATCH in mechanism (a VerificationContext override, no byte
mutation) and both rely on the same verified, source-read fact: desk/verify/checks/cert.py,
signature.py, and timing.py all treat a None evidence field as NOT_VERIFIED, never as a
silent pass -- this is the Phase 1 "absence never yields verified" property test, exercised
here as real corpus cases rather than only as a unit-test assertion.
"""

from __future__ import annotations

import dataclasses

from harness.faults import baseline
from harness.faults.base import FaultCategory, FaultSpec


def _withhold_cert(ctx):
    return dataclasses.replace(ctx, trusted_cert_pem=None)


def _withhold_clock(ctx):
    return dataclasses.replace(ctx, sp_clock=None)


WITHHELD_CERT = FaultSpec(
    fault_id="withheld_cert",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "No pinned IdP trusted certificate was supplied for this case. The SAMLResponse "
        "itself is the real, unmodified, correctly-signed capture -- the gap is purely "
        "that nothing exists yet to verify its signature or its signing cert against."
    ),
    target_check_ids=["SAML-SIG-01", "SAML-SIG-02", "SAML-CERT-01", "SAML-CERT-02"],
    expected_states={
        "SAML-SIG-01": "not_verified",
        "SAML-SIG-02": "not_verified",
        "SAML-CERT-01": "not_verified",
        "SAML-CERT-02": "not_verified",
    },
    expected_root_cause=None,
    expected_disposition="awaiting_evidence",
    difficulty="ambiguous",
    ctx_transform=_withhold_cert,
)

WITHHELD_CLOCK = FaultSpec(
    fault_id="withheld_clock",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "No SP clock evidence was supplied for this case, so clock-skew cannot be judged "
        "-- a message's own claimed IssueInstant proves nothing about the SP's clock by "
        "itself (desk/verify/checks/timing.py's own stated reasoning)."
    ),
    target_check_ids=["SAML-SKEW-01"],
    expected_states={"SAML-SKEW-01": "not_verified"},
    expected_root_cause=None,
    expected_disposition="awaiting_evidence",
    difficulty="ambiguous",
    ctx_transform=_withhold_clock,
)

AMBIGUOUS_CASES = [WITHHELD_CERT, WITHHELD_CLOCK]

__all__ = ["AMBIGUOUS_CASES"]
