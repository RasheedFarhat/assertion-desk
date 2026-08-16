"""Parse a raw SAMLResponse into a structured, read-only view, once, for all checks to share.

Field shapes here are taken directly from a real Keycloak-produced response
(tests/verify/phase0_fixtures/good_saml_response.xml), not from the spec in the
abstract -- e.g. the inner <Assertion> uses the default (unprefixed) namespace while
the outer <Response> uses the saml: prefix; both resolve to the same namespace URI and
lxml's URI-keyed namespace dict handles that transparently, but it is worth noting
because a naive prefix-string search would silently miss the assertion's children.

Parsing is defused first (desk/verify/xmldsig.py's pattern): reject hostile XML shapes
before any check ever sees the document.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import defusedxml.ElementTree as DET
from lxml import etree as LET

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}


class MalformedSamlResponse(Exception):
    """Raised when the input isn't a parseable, minimally-shaped SAMLResponse at all.

    This is distinct from any individual check failing -- it means desk/intake's parse
    stage should route the case to intake_failed with a named reason, before verify/
    ever runs. Checks never see a document that couldn't be parsed."""


@dataclass
class ParsedAssertion:
    element_id: str | None
    issue_instant: str | None
    issuer: str | None
    nameid: str | None
    nameid_format: str | None
    subject_confirmation_method: str | None
    scd_in_response_to: str | None
    scd_not_on_or_after: str | None
    scd_recipient: str | None
    conditions_not_before: str | None
    conditions_not_on_or_after: str | None
    audiences: list[str] = field(default_factory=list)
    is_signed: bool = False
    is_encrypted: bool = False
    attribute_names: list[str] = field(default_factory=list)  # may contain duplicates -- that's data, not a bug


@dataclass
class ParsedSamlResponse:
    raw_bytes: bytes
    root: LET._Element
    response_id: str | None
    destination: str | None
    in_response_to: str | None
    issue_instant: str | None
    issuer: str | None
    status_code: str | None
    is_response_signed: bool
    assertions: list[ParsedAssertion]


def _text(el) -> str | None:
    return el.text.strip() if el is not None and el.text else None


def parse_saml_response(raw_bytes: bytes) -> ParsedSamlResponse:
    try:
        DET.fromstring(raw_bytes)  # defused pre-check; result discarded, see desk/verify/xmldsig.py
    except Exception as exc:
        raise MalformedSamlResponse(f"failed defused XML pre-parse: {exc}") from exc

    try:
        parser = LET.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        root = LET.fromstring(raw_bytes, parser=parser)
    except Exception as exc:
        raise MalformedSamlResponse(f"failed lxml parse: {exc}") from exc

    if root.tag != f"{{{NS['samlp']}}}Response":
        raise MalformedSamlResponse(f"root element is {root.tag!r}, expected samlp:Response")

    status_el = root.find("samlp:Status/samlp:StatusCode", NS)
    status_code = status_el.get("Value") if status_el is not None else None

    assertions = []
    for a_el in root.findall("saml:Assertion", NS):
        nameid_el = a_el.find("saml:Subject/saml:NameID", NS)
        scd_el = a_el.find("saml:Subject/saml:SubjectConfirmation/saml:SubjectConfirmationData", NS)
        sc_el = a_el.find("saml:Subject/saml:SubjectConfirmation", NS)
        cond_el = a_el.find("saml:Conditions", NS)
        audiences = [
            _text(aud) for aud in a_el.findall("saml:Conditions/saml:AudienceRestriction/saml:Audience", NS)
        ]
        attr_names = [
            attr.get("Name")
            for attr in a_el.findall("saml:AttributeStatement/saml:Attribute", NS)
        ]

        # EncryptedAssertion is a sibling shape entirely (saml:EncryptedID / xenc:EncryptedData);
        # not handled by this parser yet. Detected structurally so SAML-ENC-01 can report
        # not_applicable / not_verified honestly rather than pretending it isn't there.
        is_encrypted = a_el.find(".//{http://www.w3.org/2001/04/xmlenc#}EncryptedData") is not None

        assertions.append(
            ParsedAssertion(
                element_id=a_el.get("ID"),
                issue_instant=a_el.get("IssueInstant"),
                issuer=_text(a_el.find("saml:Issuer", NS)),
                nameid=_text(nameid_el),
                nameid_format=nameid_el.get("Format") if nameid_el is not None else None,
                subject_confirmation_method=sc_el.get("Method") if sc_el is not None else None,
                scd_in_response_to=scd_el.get("InResponseTo") if scd_el is not None else None,
                scd_not_on_or_after=scd_el.get("NotOnOrAfter") if scd_el is not None else None,
                scd_recipient=scd_el.get("Recipient") if scd_el is not None else None,
                conditions_not_before=cond_el.get("NotBefore") if cond_el is not None else None,
                conditions_not_on_or_after=cond_el.get("NotOnOrAfter") if cond_el is not None else None,
                audiences=[a for a in audiences if a is not None],
                is_signed=a_el.find("ds:Signature", NS) is not None,
                is_encrypted=is_encrypted,
                attribute_names=[n for n in attr_names if n is not None],
            )
        )

    # An EncryptedAssertion wrapping the whole thing (rather than a signed-plaintext
    # Assertion with encrypted attributes inside it) would appear as zero saml:Assertion
    # matches above and a samlp:EncryptedAssertion sibling instead. Not modeled by
    # Keycloak's default SAML client and not seen in the real captured artifact, so this
    # parser doesn't claim to handle it -- a response with neither shape simply produces
    # an empty assertions list, and every per-assertion check downstream reports
    # not_verified rather than silently skipping.

    return ParsedSamlResponse(
        raw_bytes=raw_bytes,
        root=root,
        response_id=root.get("ID"),
        destination=root.get("Destination"),
        in_response_to=root.get("InResponseTo"),
        issue_instant=root.get("IssueInstant"),
        issuer=_text(root.find("saml:Issuer", NS)),
        status_code=status_code,
        is_response_signed=root.find("ds:Signature", NS) is not None,
        assertions=assertions,
    )
