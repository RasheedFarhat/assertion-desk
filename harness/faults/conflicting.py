"""CONFLICTING_CASES -- the "two things disagree" stratum (plan §23), kept out of
ALL_FAULTS for the same reason harness/faults/ambiguous.py's cases are: it is a different
concept from the 20 named faults, not a 21st entry in that list.

The plan's own example of a conflicting case is IdP metadata carrying two signing
certificates, neither matching the assertion's thumbprint. That case is not built here,
and not because it wasn't considered. desk/verify/context.py's VerificationContext has
exactly one trusted_cert_pem field -- it does not model a set of candidate certs. Faking
"two certs, neither matching" would mean inventing a context shape the real verifier
doesn't have and then testing against the invention instead of the system, which is
exactly the kind of manufactured evidence this project's own truthfulness standard exists
to rule out. Honest choice: name the gap in docs/PHASE3_NOTES.md rather than build around
it.

What the corpus gets instead is a conflict that is real and needed no invention: the
actual Phase 0 capture's AttributeStatement carries six Role attributes, and inspection
(harness/capture/captured/saml_response.xml) shows the Name value repeats -- a real IdP
attribute-mapping quirk, not something this project injected. SAML-ATTR-01
(desk/verify/checks/attributes.py) already treats a duplicate Attribute Name as
REVIEW_REQUIRED on exactly this artifact with zero transform applied, which is why this
case's category is BASELINE rather than CONTEXT_MISMATCH -- see harness/faults/base.py's
docstring for why that distinction matters.
"""

from __future__ import annotations

from harness.faults.base import FaultCategory, FaultSpec

DUPLICATE_ROLE_ATTRIBUTES = FaultSpec(
    fault_id="duplicate_role_attributes",
    category=FaultCategory.BASELINE,
    description=(
        "The real, unmodified Phase 0 capture's AttributeStatement carries a repeated "
        "Attribute Name (Role) with differing values -- two sources of truth for the "
        "same claim disagreeing, with no fault of any kind injected to produce it. "
        "Correct behavior is review_required, not silently picking one value or the "
        "other and moving on."
    ),
    target_check_ids=["SAML-ATTR-01"],
    expected_states={"SAML-ATTR-01": "review_required"},
    expected_root_cause="SAML-ATTR-01",
    expected_disposition="review_required",
    difficulty="conflicting",
)

CONFLICTING_CASES = [DUPLICATE_ROLE_ATTRIBUTES]

__all__ = ["CONFLICTING_CASES"]
