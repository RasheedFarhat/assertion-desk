"""cert_expired -- CONTEXT_MISMATCH. The real captured SAMLResponse and its real trusted
certificate are both used unmodified. The fault is entirely in the SP's own evaluation
time: pinned past the real cert's validity window (not_after 2036-08-16T06:50:38Z, read
directly off harness/capture/idp-cert.txt via cryptography.x509). This models an SP that
never rotated its pinned copy of the IdP's certificate and kept trusting it long after it
expired -- a real, common failure mode, and one that needs no byte mutation to produce
honestly.

Honest side effect, not a bug: desk/verify/context.py's ctx.now() is the single clock that
both SAML-CERT-01 (cert validity window) and SAML-COND-01/02 (assertion Conditions /
SubjectConfirmationData windows) read from. The real captured assertion's own window is
only a few minutes wide around its 2026-08-16 IssueInstant, so any evaluation_time far
enough in the future to exceed the cert's decade-long window necessarily also exceeds the
assertion's minute-long one. There's no way to isolate "the cert is expired" from "this
old assertion looks expired too" using one fixed real capture -- and that's actually
physically honest: nobody presents a decade-stale assertion for live verification, so a
clean cert-only-expired case would itself be an artificial scenario. sp_clock is left at
the baseline value (not advanced) so SAML-SKEW-01, which reads sp_clock independently of
evaluation_time, is unaffected and still verifies clean.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from desk.verify.context import VerificationContext
from harness.faults import baseline
from harness.faults.base import FaultCategory, FaultSpec

# Past the real cert's not_after (2036-08-16T06:50:38Z) by a comfortable margin, so the
# fault isn't sensitive to a one-second boundary judgment call.
EXPIRED_EVAL_TIME = datetime(2037, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _apply(ctx: VerificationContext) -> VerificationContext:
    # sp_clock intentionally NOT touched -- see module docstring.
    return dataclasses.replace(ctx, evaluation_time=EXPIRED_EVAL_TIME)


FAULT = FaultSpec(
    fault_id="cert_expired",
    category=FaultCategory.CONTEXT_MISMATCH,
    description=(
        "SP evaluates the response long after the trusted IdP certificate's own validity "
        "window closed -- the pinned copy was never rotated. Real cert, real response, "
        "only the SP's evaluation clock differs from baseline. Necessarily also expires "
        "the real assertion's own short Conditions/SubjectConfirmationData window (see "
        "module docstring) -- reported honestly rather than hidden."
    ),
    target_check_ids=["SAML-CERT-01", "SAML-COND-01", "SAML-COND-02"],
    expected_states={"SAML-CERT-01": "failed", "SAML-COND-01": "failed", "SAML-COND-02": "failed"},
    expected_root_cause="SAML-CERT-01",
    expected_disposition="review_required",
    difficulty="normal",
    ctx_transform=_apply,
)
