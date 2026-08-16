"""wrong_binding -- ARTIFACT_MUTATION on the HAR (mutations.rebind_acs_post_as_redirect_get),
not on the SAMLResponse XML. Rewrites the real ACS delivery from HTTP-POST (what
Keycloak's default client actually used) to look like HTTP-Redirect delivery: method
becomes GET and SAMLResponse/RelayState move from the POST body into the URL query
string, simulating an SP or IdP binding misconfiguration (SP registered for Redirect,
IdP configured to only ever send POST, or vice versa).

Deliberately does NOT attempt real HTTP-Redirect DEFLATE compression (SAML core
3.4.4.1) -- see mutations.rebind_acs_post_as_redirect_get's docstring for why faking that
encoding would assert a fault this harness has no independent way to validate. What this
models honestly is the method/binding mismatch alone.

The SAMLResponse XML content is byte-identical to the good capture, so every
desk/verify/checks/ check that inspects the parsed Assertion still verifies clean --
none of them reads HTTP method or binding. The actual fault (SP configured to accept POST
only, rejecting or mishandling a GET delivery) lives in the SP's binding-acceptance logic,
which is server behavior, not something the SAMLResponse content itself can carry a
check-detectable signal about. no_check_coverage_reason names that gap explicitly.
"""

from __future__ import annotations

from harness.faults import mutations
from harness.faults.base import FaultCategory, FaultSpec


def _apply(har: dict) -> dict:
    return mutations.rebind_acs_post_as_redirect_get(har)


FAULT = FaultSpec(
    fault_id="wrong_binding",
    category=FaultCategory.ARTIFACT_MUTATION,
    description=(
        "SAMLResponse is delivered via HTTP-Redirect (GET, query string) instead of the "
        "configured HTTP-POST binding. The Assertion content is untouched and verifies "
        "clean; the fault is a binding/method mismatch no check currently inspects."
    ),
    no_check_coverage_reason=(
        "HTTP method and SAML binding type live in the HAR's request line, not in the "
        "parsed SAMLResponse XML. No check in desk/verify/checks/ reads either, so a "
        "binding mismatch produces a fully-verified check grid with the real-world "
        "symptom (login rejected or mishandled at the SP) unexplained by any check."
    ),
    expected_disposition="review_required",
    difficulty="normal",
    har_transform=_apply,
)
