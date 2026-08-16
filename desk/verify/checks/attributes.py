"""SAML-ATTR-01: structural sanity of the AttributeStatement, not its business content.

This exists because of a real interop hazard hit in Phase 0: Keycloak's default SAML
client emits one <Attribute Name="Role"> element per realm role instead of a single
Attribute with multiple AttributeValue children, and python3-saml's get_attributes()
raises OneLogin_Saml2_ValidationError on the duplicated Name (harness/capture/sp_app.py
works around it with a try/except; see docs/PHASE0_NOTES.md). desk/verify/parsed.py
itself never raises on this shape -- it just collects every Attribute Name, duplicates
included -- but a duplicate Name is still a real downstream interop hazard for whatever
consumes AttributeStatement next, so it is worth its own check rather than being silently
absorbed."""

from __future__ import annotations

from collections import Counter

from desk.verify.assurance import Assurance, CheckResult
from desk.verify.context import VerificationContext
from desk.verify.parsed import ParsedSamlResponse


def check_attributes_parseable(parsed: ParsedSamlResponse, ctx: VerificationContext) -> CheckResult:
    if not parsed.assertions:
        return CheckResult(
            check_id="SAML-ATTR-01", assurance=Assurance.NOT_VERIFIED, observed=None,
            expected="no duplicate Attribute Name values", reason="response contains no parsed Assertion",
        )
    names = parsed.assertions[0].attribute_names
    if not names:
        return CheckResult(
            check_id="SAML-ATTR-01", assurance=Assurance.NOT_APPLICABLE, observed=None,
            expected=None, reason="assertion has no AttributeStatement (optional per spec)",
        )
    counts = Counter(names)
    duplicates = sorted(n for n, c in counts.items() if c > 1)
    if duplicates:
        return CheckResult(
            check_id="SAML-ATTR-01", assurance=Assurance.REVIEW_REQUIRED,
            observed=f"duplicated Attribute Name(s): {', '.join(duplicates)}",
            expected="no duplicate Attribute Name values",
            reason="one or more Attribute Name values repeat across separate elements; some SAML "
            "libraries (e.g. python3-saml) reject this shape outright even though it parses here",
        )
    return CheckResult(
        check_id="SAML-ATTR-01", assurance=Assurance.VERIFIED, observed=", ".join(sorted(counts)),
        expected="no duplicate Attribute Name values", reason="AttributeStatement has no duplicated Attribute Name values",
    )
