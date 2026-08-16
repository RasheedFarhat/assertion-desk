"""What the SP already knows independently of anything in the SAMLResponse.

Every field here is trusted, out-of-band configuration -- the SP's own settings, or
evidence supplied separately by the customer (their clock, their expected InResponseTo).
Checks compare the parsed response against this context; they never trust the response
to tell them what it should say about itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class VerificationContext:
    sp_entity_id: str
    acs_url: str
    idp_entity_id: str
    trusted_cert_pem: str | None = None  # None means "no pinned cert supplied" -- SAML-CERT-01/02 report not_verified, not verified

    # Evidence the customer may or may not have supplied. Absence is common and must be
    # handled honestly (not_verified), not treated as a stand-in for "assume it's fine."
    in_response_to_expected: str | None = None
    sp_clock: datetime | None = None
    clock_skew_tolerance_seconds: int = 180  # 3 minutes, the conventional SAML default

    # A fixed point in time to evaluate NotBefore/NotOnOrAfter/IssueInstant against, for
    # reproducible tests and replay. Defaults to "now" at call time when left unset.
    evaluation_time: datetime | None = None

    def now(self) -> datetime:
        return self.evaluation_time if self.evaluation_time is not None else datetime.now(timezone.utc)
