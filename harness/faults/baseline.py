"""The one known-good VerificationContext, matching the real Keycloak/SP pair Phase 0
provisioned (harness/capture/keycloak_admin.py's constants) and the real trusted
certificate captured alongside it. Every CONTEXT_MISMATCH fault starts from a copy of
this and overrides exactly the field the fault is about -- so a reader diffing any fault
file against this one sees precisely what changed and nothing else.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from desk.verify.context import VerificationContext

_CAPTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "capture")

SP_ENTITY_ID = "http://127.0.0.1:9091/saml/metadata"
SP_ACS_URL = "http://127.0.0.1:9091/saml/acs"
IDP_ENTITY_ID = "http://127.0.0.1:8080/realms/assertion-desk"

# The real login this whole fault set is built against (Phase 0, still on disk).
GOOD_SAML_RESPONSE_PATH = os.path.join(_CAPTURE_DIR, "captured", "saml_response.xml")
GOOD_HAR_PATH = os.path.join(_CAPTURE_DIR, "captured", "login.har")
TRUSTED_CERT_PATH = os.path.join(_CAPTURE_DIR, "idp-cert.txt")

# The real captured response's own IssueInstant is 2026-08-16T06:54:53.492Z, its
# Conditions window is [06:54:51.491Z, 06:59:51.491Z), and its tighter
# SubjectConfirmationData NotOnOrAfter is 06:55:51.491Z (see docs/PHASE3_NOTES.md for the
# full timestamp inventory). GOOD_EVALUATION_TIME has to land inside all three at once for
# the "nothing is wrong" baseline to actually verify clean, so it's pinned close to
# IssueInstant rather than a round number. Pinning at all (instead of defaulting to
# wall-clock "now") is what makes replay deterministic -- a case built today and
# re-verified next year must produce the identical assurance states.
GOOD_EVALUATION_TIME = datetime(2026, 8, 16, 6, 55, 0, tzinfo=timezone.utc)


def load_trusted_cert() -> str:
    with open(TRUSTED_CERT_PATH) as f:
        return f.read()


def load_good_saml_response() -> bytes:
    with open(GOOD_SAML_RESPONSE_PATH, "rb") as f:
        return f.read()


def good_context() -> VerificationContext:
    """A fresh VerificationContext per call -- callers mutate their own copy via
    dataclasses.replace(), never this function's return value in place."""
    return VerificationContext(
        sp_entity_id=SP_ENTITY_ID,
        acs_url=SP_ACS_URL,
        idp_entity_id=IDP_ENTITY_ID,
        trusted_cert_pem=load_trusted_cert(),
        evaluation_time=GOOD_EVALUATION_TIME,
        # The real capture's own InResponseTo is present but this SP implementation
        # (harness/capture/sp_app.py) doesn't persist its own outbound request IDs to
        # compare against later, so no case can honestly claim in_response_to_expected
        # unless the fault is specifically about supplying or mismatching it.
        in_response_to_expected=None,
        sp_clock=GOOD_EVALUATION_TIME,
    )
