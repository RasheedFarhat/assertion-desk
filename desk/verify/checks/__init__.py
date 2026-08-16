"""Twenty deterministic checks against a parsed SAMLResponse, grouped by family.

Every check function has the same shape: (parsed, ctx, ...) -> CheckResult, and every
one is honest about absence -- a check whose required evidence is missing returns
NOT_VERIFIED, never a guessed VERIFIED. See desk/verify/assurance.py for the taxonomy
and its construction-time invariant.

v1 supports exactly one <Assertion> per <Response>, which is what Keycloak's default
SAML client produces and what every captured artifact (Phase 0) shows. Multiple
assertions per response is out of scope; checks that need assertion data report
NOT_VERIFIED with a named reason when parsed.assertions is empty, rather than silently
picking one of several.
"""

from __future__ import annotations

from desk.verify.checks.attributes import check_attributes_parseable
from desk.verify.checks.audience import check_audience
from desk.verify.checks.cert import check_cert_thumbprint, check_cert_validity_window
from desk.verify.checks.destination import check_destination, check_recipient
from desk.verify.checks.encryption import check_not_encrypted
from desk.verify.checks.inresponseto import check_response_in_response_to, check_scd_in_response_to
from desk.verify.checks.issuer import check_assertion_issuer, check_response_issuer
from desk.verify.checks.signature import check_assertion_signature, check_response_signature
from desk.verify.checks.status import check_status_success
from desk.verify.checks.subject import check_nameid_format, check_nameid_present, check_subject_confirmation_method
from desk.verify.checks.timing import check_conditions_window, check_scd_not_expired, check_response_clock_skew

ALL_CHECKS = [
    check_response_signature,
    check_assertion_signature,
    check_cert_validity_window,
    check_cert_thumbprint,
    check_response_issuer,
    check_assertion_issuer,
    check_audience,
    check_destination,
    check_recipient,
    check_response_in_response_to,
    check_scd_in_response_to,
    check_response_clock_skew,
    check_conditions_window,
    check_scd_not_expired,
    check_nameid_present,
    check_nameid_format,
    check_subject_confirmation_method,
    check_status_success,
    check_attributes_parseable,
    check_not_encrypted,
]

__all__ = ["ALL_CHECKS"]
