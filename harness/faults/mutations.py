"""Reusable byte- and structure-level transforms shared by the ARTIFACT_MUTATION faults.

Every function here is a pure transform: real bytes in, deterministically mutated bytes
out. None of them depends on wall-clock time or randomness, so re-running
harness/generate.py always reproduces byte-identical mutated artifacts from the same
input -- which is what lets corpus/MANIFEST.json pin a sha256 per artifact and mean it.
"""

from __future__ import annotations

import base64
import copy
import re
import urllib.parse


def flip_signature_value(xml_bytes: bytes, occurrence: int = -1) -> bytes:
    """Corrupt a ds:SignatureValue's base64 payload by flipping one character.

    occurrence selects which <...:SignatureValue> element to hit when more than one is
    present (Keycloak's captures sign both the Response and the Assertion) -- -1 (the
    default) targets the last one, which in every real capture so far is the Assertion's,
    the element actually carrying the authentication claim. Flipping a character inside
    base64 rather than appending garbage keeps the element's own well-formedness intact,
    so the fault is specifically "signature does not verify," not "XML doesn't parse."
    """
    text = xml_bytes.decode("utf-8")
    matches = list(re.finditer(r"(<[\w:]*SignatureValue[^>]*>)([^<]+)(</[\w:]*SignatureValue>)", text))
    if not matches:
        raise ValueError("no SignatureValue element found to corrupt")
    m = matches[occurrence]
    payload = m.group(2)
    # Flip a character in the middle of the payload rather than at either end, so the
    # mutation can't be dismissed as a truncation/padding artifact.
    mid = len(payload) // 2
    original_char = payload[mid]
    replacement = "A" if original_char != "A" else "B"
    corrupted = payload[:mid] + replacement + payload[mid + 1 :]
    new_text = text[: m.start()] + m.group(1) + corrupted + m.group(3) + text[m.end() :]
    return new_text.encode("utf-8")


def strip_element_text(xml_bytes: bytes, tag_local_name: str, occurrence: int = 0) -> bytes:
    """Blank the text content of the occurrence-th element with this local tag name,
    leaving the element itself in place (so parsing still succeeds and the check under
    test can report FAILED for an empty value rather than NOT_VERIFIED for a structural
    parse failure it was never meant to catch)."""
    text = xml_bytes.decode("utf-8")
    pattern = re.compile(rf"(<[\w:]*{tag_local_name}\b[^>]*>)([^<]*)(</[\w:]*{tag_local_name}>)")
    matches = list(pattern.finditer(text))
    if occurrence >= len(matches):
        raise ValueError(f"only {len(matches)} {tag_local_name} element(s) found, requested index {occurrence}")
    m = matches[occurrence]
    new_text = text[: m.start()] + m.group(1) + m.group(3) + text[m.end() :]
    return new_text.encode("utf-8")


def rewrite_attribute(xml_bytes: bytes, tag_local_name: str, attr_name: str, new_value: str, occurrence: int = 0) -> bytes:
    """Rewrite one attribute value on the occurrence-th element with this local tag name."""
    text = xml_bytes.decode("utf-8")
    pattern = re.compile(rf'(<[\w:]*{tag_local_name}\b[^>]*\b{attr_name}=")([^"]*)("[^>]*>)')
    matches = list(pattern.finditer(text))
    if occurrence >= len(matches):
        raise ValueError(f"only {len(matches)} {tag_local_name}[{attr_name}] found, requested index {occurrence}")
    m = matches[occurrence]
    new_text = text[: m.start()] + m.group(1) + new_value + m.group(3) + text[m.end() :]
    return new_text.encode("utf-8")


def add_attribute(xml_bytes: bytes, tag_local_name: str, attr_name: str, attr_value: str, occurrence: int = 0) -> bytes:
    """Add a brand-new attribute to the occurrence-th element with this local tag name,
    for the case where the attribute doesn't already exist on that element (rewrite_attribute
    requires it to already be present; this is the insert counterpart)."""
    text = xml_bytes.decode("utf-8")
    pattern = re.compile(rf"<([\w:]*{tag_local_name}\b[^>]*?)(/?)>")
    matches = list(pattern.finditer(text))
    if occurrence >= len(matches):
        raise ValueError(f"only {len(matches)} {tag_local_name} element(s) found, requested index {occurrence}")
    m = matches[occurrence]
    insertion = f' {attr_name}="{attr_value}"'
    new_text = text[: m.end(1)] + insertion + text[m.end(1) :]
    return new_text.encode("utf-8")


def insert_encrypted_data_into_assertion(xml_bytes: bytes) -> bytes:
    """Insert a structurally valid xenc:EncryptedData element as a child of the real
    <saml:Assertion>, simulating an assertion carrying an EncryptedAttribute/EncryptedID
    alongside its otherwise-plaintext content, rather than replacing the whole assertion.

    desk/verify/parsed.py detects encryption via a *descendant* search inside
    saml:Assertion (`.//xenc:EncryptedData`) and says explicitly it does not model a
    top-level saml:EncryptedAssertion wrapper -- Keycloak's default client never produces
    one and the real capture doesn't have one. Wrapping the whole assertion (an earlier
    draft of this function did that) would make the parser see zero saml:Assertion
    elements at all, which is a different, less honest fault than "this assertion has an
    encrypted piece in it." Inserting in place keeps NameID, Subject, Conditions, etc.
    intact and parseable, so SAML-ENC-01 fires the way it's actually meant to.

    This does not attempt real XML-Encryption -- there is no decryption path anywhere in
    this system for a real ciphertext to exercise. The opaque CipherValue is exactly that:
    opaque, non-decryptable filler standing in for content this verifier is honest about
    not being able to read.
    """
    text = xml_bytes.decode("utf-8")
    match = re.search(r"<saml:Assertion\b[^>]*>", text)
    if match is None:
        raise ValueError("no saml:Assertion open tag found to insert into")
    opaque_payload = base64.b64encode(b"NOT_REAL_CIPHERTEXT_structural_test_fixture_only").decode()
    encrypted_data = (
        '<xenc:EncryptedData xmlns:xenc="http://www.w3.org/2001/04/xmlenc#" '
        'Type="http://www.w3.org/2001/04/xmlenc#Content">'
        "<xenc:CipherData><xenc:CipherValue>" + opaque_payload + "</xenc:CipherValue></xenc:CipherData>"
        "</xenc:EncryptedData>"
    )
    insert_at = match.end()
    return (text[:insert_at] + encrypted_data + text[insert_at:]).encode("utf-8")


def truncate(raw_bytes: bytes, keep_fraction: float = 0.6) -> bytes:
    """Chop the artifact off mid-stream, simulating a network truncation. keep_fraction
    is deliberately > 0.5 so the cut lands inside real content, not near the start."""
    cut = int(len(raw_bytes) * keep_fraction)
    return raw_bytes[:cut]


def double_base64_encode(raw_bytes: bytes) -> bytes:
    """Base64-encode already-decoded XML a second time, simulating an SP-side bug where
    the SAMLResponse form field was decoded once by a proxy and once by the app, so the
    bytes that reach parsing are base64 *text*, not XML."""
    return base64.b64encode(raw_bytes)


def insert_xml_comment(xml_bytes: bytes, comment_text: str) -> bytes:
    """Insert an XML comment (a real, legal SAML shape) right after the root element's
    opening tag -- the natural place an injection payload hides in a document a
    downstream reader might read verbatim, per the adversarial stratum's design."""
    text = xml_bytes.decode("utf-8")
    end_of_open_tag = text.index(">") + 1
    comment = f"<!-- {comment_text} -->"
    return (text[:end_of_open_tag] + comment + text[end_of_open_tag:]).encode("utf-8")


def _find_acs_post_entry(har: dict) -> dict:
    """Locate the one HAR entry that POSTs the SAMLResponse to the SP's ACS endpoint --
    the only entry the two HAR-level faults below need to touch. Raises if the real
    capture's shape ever changes, rather than silently mutating the wrong entry."""
    entries = har["log"]["entries"]
    matches = [e for e in entries if e["request"]["method"] == "POST" and "/saml/acs" in e["request"]["url"]]
    if len(matches) != 1:
        raise ValueError(f"expected exactly 1 ACS POST entry, found {len(matches)}")
    return matches[0]


def strip_relaystate_param(har: dict) -> dict:
    """Remove the RelayState form field from the real ACS POST entry, simulating an IdP
    or a relaying proxy that drops it in transit. Returns a deep-enough copy that the
    input HAR dict is never mutated in place -- callers always get a new object back."""
    har = copy.deepcopy(har)
    entry = _find_acs_post_entry(har)
    params = entry["request"]["postData"]["params"]
    before = len(params)
    entry["request"]["postData"]["params"] = [p for p in params if p.get("name") != "RelayState"]
    after = len(entry["request"]["postData"]["params"])
    if before == after:
        raise ValueError("no RelayState param found on the ACS POST entry to strip")
    return har


def rebind_acs_post_as_redirect_get(har: dict) -> dict:
    """Rewrite the real ACS POST entry to look like an HTTP-Redirect-bound delivery
    (SAMLResponse carried as a GET query parameter) instead of the real HTTP-POST binding
    Keycloak's default client actually used. This does NOT perform real HTTP-Redirect
    DEFLATE compression (SAML core 3.4.4.1) -- doing that faithfully would require
    reproducing the exact raw-deflate-then-base64 encoding a real IdP would apply on the
    Redirect path, which this harness has no independent way to verify against, so
    attempting it would risk asserting a binding-encoding fault this project cannot
    actually validate. What this models, honestly, is the method/binding mismatch alone:
    the SAMLResponse value moves from the POST body to the URL query string and the
    method changes to GET, which is the part no check currently reads (see
    harness/faults/wrong_binding.py's no_check_coverage_reason)."""
    har = copy.deepcopy(har)
    entry = _find_acs_post_entry(har)
    params = {p["name"]: p["value"] for p in entry["request"]["postData"]["params"]}
    query = urllib.parse.urlencode(params)
    base_url = entry["request"]["url"]
    entry["request"]["method"] = "GET"
    entry["request"]["url"] = f"{base_url}?{query}"
    entry["request"]["queryString"] = [{"name": k, "value": v} for k, v in params.items()]
    entry["request"].pop("postData", None)
    return har
