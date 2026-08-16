"""Phase 2 exit criteria (plan section 27): a leakage suite verified by an independent
scanner rather than by the detector itself; a malformed-input suite proving fail-closed
behavior; and a negative test asserting no cleartext secret can reach a database column.

The leakage tests in this file deliberately do NOT import anything from
desk.custody.scan or desk.custody.detectors.* to extract their "known secret" values.
They walk the raw fixture bytes with plain dict/JSON/regex logic that has no shared code
path with the thing being tested. If scan.py and this file agreed because they shared a
bug, that would be worthless -- the point is that they don't share anything.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from desk.custody.findings import Action, CustodyFinding, FindingClass, Liveness
from desk.custody.scan import CustodyFailure, CustodyResult, run_custody

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "verify", "phase0_fixtures")


def _read(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def _read_text(name: str) -> str:
    return _read(name).decode("utf-8")


# --------------------------------------------------------------------------- #
# Independent leakage suite
# --------------------------------------------------------------------------- #


def _known_secrets_in_real_har() -> list[str]:
    """Extracts real secret values directly from the ORIGINAL HAR fixture using plain
    JSON traversal -- known cookie names, the literal password field, and the
    session_code flow-artifact param -- without calling any desk.custody code. This is
    the "independent scanner" the plan's Phase 2 exit criterion requires.
    """
    har = json.loads(_read_text("real_login.har"))
    known_cookie_names = {
        "KC_RESTART",
        "KEYCLOAK_IDENTITY",
        "KEYCLOAK_SESSION",
        "AUTH_SESSION_ID",
        "KC_AUTH_SESSION_HASH",
    }
    secrets: set[str] = set()

    for entry in har["log"]["entries"]:
        request = entry.get("request", {}) or {}
        response = entry.get("response", {}) or {}

        for c in (request.get("cookies") or []) + (response.get("cookies") or []):
            if c.get("name") in known_cookie_names and c.get("value"):
                secrets.add(c["value"])

        for qs in request.get("queryString") or []:
            if qs.get("name") == "session_code" and qs.get("value"):
                secrets.add(qs["value"])

        url = request.get("url", "")
        m = re.search(r"[?&]session_code=([^&]+)", url)
        if m:
            secrets.add(m.group(1))

        post_data = request.get("postData") or {}
        for p in post_data.get("params") or []:
            if p.get("name") == "password" and p.get("value"):
                secrets.add(p["value"])
        text = post_data.get("text", "")
        m = re.search(r"(?:^|&)password=([^&]+)", text)
        if m:
            secrets.add(m.group(1))

    # Sanity: if this comes back empty, the extraction logic itself is broken and the
    # leakage test below would pass vacuously. Fail loudly instead.
    assert secrets, "independent extraction found zero known secrets in real_login.har -- extraction logic is broken"
    return sorted(secrets, key=len, reverse=True)


def test_har_leakage_independent_scanner():
    """The plan's literal Phase 2 exit criterion: zero of the independently-extracted
    known secret values survive into the de-fanged HAR bytes."""
    raw = _read("real_login.har")
    known_secrets = _known_secrets_in_real_har()

    result = run_custody("har", raw)
    defanged_text = result.defanged_bytes.decode("utf-8")

    leaked = [s for s in known_secrets if s in defanged_text]
    assert leaked == [], f"{len(leaked)}/{len(known_secrets)} known secrets leaked into defanged HAR: {leaked}"


def test_har_leakage_scan_actually_found_something():
    """Guards against a vacuous pass: confirm the scan produced a nontrivial number of
    findings on the real fixture, not zero (which would make the leakage test above
    meaningless -- nothing redacted, nothing to leak)."""
    result = run_custody("har", _read("real_login.har"))
    assert len(result.findings) >= 15


def test_xml_nameid_and_group_recorded_but_not_redacted():
    """Grounds the RECORDED_ONLY design decision in the real fixture: NameID and Role
    attribute values are logged as findings but deliberately left in the returned bytes,
    because desk/verify needs them and they never reach a model prompt through any path
    in the architecture (plan section 16)."""
    raw = _read("good_saml_response.xml")
    result = run_custody("saml_response", raw)

    assert result.defanged_bytes == raw, "XML bytes must be byte-identical when no PEM key is present"

    nameid_findings = [f for f in result.findings if f.finding_class == FindingClass.NAMEID_PII]
    group_findings = [f for f in result.findings if f.finding_class == FindingClass.GROUP_MEMBERSHIP]
    assert len(nameid_findings) == 1
    assert nameid_findings[0].action == Action.RECORDED_ONLY
    assert len(group_findings) >= 1
    assert all(f.action == Action.RECORDED_ONLY for f in group_findings)

    # The real fixture's actual NameID value, confirmed by direct inspection.
    assert b"alice@example.test" in raw


def test_xml_faulted_fixture_also_scans_cleanly():
    raw = _read("faulted_saml_response.xml")
    result = run_custody("saml_response", raw)
    assert result.defanged_bytes == raw
    assert len(result.findings) >= 1


def test_xml_embedded_private_key_is_redacted():
    """Synthetic case (no real fixture contains a PEM key): unlike NameID/group, a
    private key embedded in XML has no verifier dependency and must be stripped."""
    pem = (
        b"-----BEGIN RSA PRIVATE KEY-----\n"
        b"MIIBOgIBAAJBAK5x5f8u4h2z9k3s8j2f7d9a1b2c3d4e5f6a7b8c9d0e1f2a3b4c\n"
        b"-----END RSA PRIVATE KEY-----\n"
    )
    xml = b"<root><Note>" + pem + b"</Note></root>"
    result = run_custody("idp_metadata", xml)

    assert pem not in result.defanged_bytes
    key_findings = [f for f in result.findings if f.finding_class == FindingClass.PRIVATE_KEY]
    assert len(key_findings) == 1
    assert key_findings[0].action == Action.REPLACED


def test_narrative_bare_password_mention_is_a_known_gap():
    """Documents a real, known limitation rather than hiding it: _scan_free_text has no
    field-name context, so a password stated in prose ("my password is X") with no
    recognizable pattern (not JWT/PEM/email/AWS-key shaped) is NOT detected. Only
    password values that arrive in a named field (form param, JSON key) are caught. This
    test pins that behavior so a future change to it is a deliberate decision, not a
    silent regression either direction."""
    narrative = "my password is alice_dev_only_2 and nothing else is wrong"
    result = run_custody("narrative", narrative.encode("utf-8"))
    defanged = result.defanged_bytes.decode("utf-8")
    assert "alice_dev_only_2" in defanged  # confirms the gap exists, so LIMITATIONS.md can name it


def test_narrative_jwt_and_email_are_caught():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.abcdefghij1234567890signature"
    narrative = f"Here is the token: {jwt} and contact me at alice@example.test if needed."
    result = run_custody("narrative", narrative.encode("utf-8"))
    defanged = result.defanged_bytes.decode("utf-8")
    assert jwt not in defanged
    assert "alice@example.test" not in defanged


# --------------------------------------------------------------------------- #
# Malformed-input / fail-closed suite
# --------------------------------------------------------------------------- #


MALFORMED_CASES = [
    pytest.param(
        "har",
        b'{"log": {"entries": "not-a-list"}}',
        id="har-entries-wrong-type",
    ),
    pytest.param("har", b"{not valid json", id="har-not-json"),
    pytest.param("har", b'{"log": {}}', id="har-missing-entries"),
    pytest.param("har", b"\xff\xfe\x00\xff not utf8", id="har-not-utf8"),
    pytest.param(
        "saml_response",
        b"<!DOCTYPE foo [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]><root>&xxe;</root>",
        id="xml-xxe",
    ),
    pytest.param("saml_response", b"this is not xml at all <<<", id="xml-garbage"),
    pytest.param("saml_response", b"<unterminated><root>", id="xml-unterminated"),
    pytest.param("idp_metadata", b"<unterminated><root>", id="xml-metadata-unterminated"),
    pytest.param("narrative", b"\xff\xfe\x00\xff not utf8", id="text-not-utf8"),
    pytest.param("screenshot_text", b"\xff\xfe\x00\xff not utf8", id="screenshot-not-utf8"),
    pytest.param("bogus_kind_nobody_registered", b"anything", id="unknown-kind"),
]


@pytest.mark.parametrize("kind,raw", MALFORMED_CASES)
def test_malformed_input_fails_closed(kind, raw):
    """Every malformed case must raise CustodyFailure -- never return a clean/empty
    CustodyResult, and never let an unhandled exception escape uncontrolled."""
    with pytest.raises(CustodyFailure):
        run_custody(kind, raw)


def test_fail_closed_never_returns_silently_on_internal_error(monkeypatch):
    """Simulates a detector throwing partway through a scan (not a malformed-input case
    -- a genuinely well-formed HAR whose internal handling breaks) and confirms
    run_custody still raises CustodyFailure rather than returning a partial/empty
    result. This is the "internal error" half of fail-closed, distinct from the
    "malformed input" half tested above."""
    import desk.custody.scan as scan_mod

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated detector crash")

    monkeypatch.setattr(scan_mod, "_scan_har_entry", _boom)

    well_formed_har = json.dumps({"log": {"entries": [{"request": {}, "response": {}}]}}).encode("utf-8")
    with pytest.raises(CustodyFailure):
        run_custody("har", well_formed_har)


def test_empty_but_well_formed_har_does_not_crash():
    """A HAR with zero entries is well-formed, not malformed -- it should succeed with
    zero findings, not raise. Distinguishes "nothing to find" from "fail closed"."""
    empty_har = json.dumps({"log": {"entries": []}}).encode("utf-8")
    result = run_custody("har", empty_har)
    assert result.findings == []
    assert result.any_live_credential is False


# --------------------------------------------------------------------------- #
# Structural negative test: no cleartext secret can reach a "database column"
# --------------------------------------------------------------------------- #


def test_custody_finding_schema_has_no_raw_value_field():
    """Schema-level guarantee from findings.py's own docstring: CustodyFinding has no
    field capable of holding a raw secret. Checked structurally against the dataclass's
    actual field names, so a future field addition (e.g. a well-intentioned "raw" field
    for debugging) fails this test immediately rather than silently reintroducing the
    exact hole the design exists to close."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(CustodyFinding)}
    banned_substrings = ("raw", "secret", "value", "cleartext", "plaintext_value")
    for name in field_names:
        lname = name.lower()
        for banned in banned_substrings:
            assert banned not in lname, f"CustodyFinding.{name} looks like it could hold a raw secret"


def test_no_known_secret_appears_in_any_finding_field():
    """Behavioral companion to the structural test above: for a real run against the HAR
    fixture, walk every field of every CustodyFinding as a string and confirm none of
    the independently-extracted known secret values appear anywhere in any of them --
    not location, not placeholder_token, not detector name. This is what "no cleartext
    secret reaches any database column" means before a database exists (Phase 5):
    CustodyFinding *is* the row that will become a database row."""
    import dataclasses

    known_secrets = _known_secrets_in_real_har()
    result = run_custody("har", _read("real_login.har"))

    for finding in result.findings:
        for field in dataclasses.fields(finding):
            field_value = getattr(finding, field.name)
            field_str = str(field_value)
            for secret in known_secrets:
                assert secret not in field_str, (
                    f"known secret leaked into CustodyFinding.{field.name}: "
                    f"{finding.detector} @ {finding.location}"
                )


def test_placeholder_tokens_are_not_reversible_by_length():
    """A weak but real structural check: placeholder tokens are short correlation hashes,
    never the raw value itself, regardless of how long the original secret was."""
    result = run_custody("har", _read("real_login.har"))
    for finding in result.findings:
        assert finding.placeholder_token.startswith("{{")
        assert finding.placeholder_token.endswith("}}")
        assert len(finding.placeholder_token) < 40  # a stable short hash, not an echoed value


# --------------------------------------------------------------------------- #
# Cross-artifact correlation sweep (the HTML-embedded session_code case)
# --------------------------------------------------------------------------- #


def test_cross_artifact_sweep_catches_html_embedded_token():
    """The real bug this segment found and fixed: Keycloak's session_code token appears
    unlabeled inside a login page's HTML form action attribute, with no field name and
    no JWT/PEM/email/AWS-key shape. Confirms the sweep catches it by checking that a
    scan.cross_artifact_correlation-attributed finding exists and that the known
    session_code value from the independent extraction does not survive anywhere,
    including inside response bodies specifically."""
    har = json.loads(_read_text("real_login.har"))
    session_codes = set()
    for entry in har["log"]["entries"]:
        for qs in (entry.get("request", {}).get("queryString") or []):
            if qs.get("name") == "session_code":
                session_codes.add(qs["value"])
    assert session_codes, "fixture no longer contains a session_code -- test assumption invalid"

    result = run_custody("har", _read("real_login.har"))
    defanged_har = json.loads(result.defanged_bytes.decode("utf-8"))

    for entry in defanged_har["log"]["entries"]:
        body = (entry.get("response", {}).get("content", {}) or {}).get("text", "") or ""
        for code in session_codes:
            assert code not in body

    sweep_findings = [f for f in result.findings if f.detector == "scan.cross_artifact_correlation"]
    assert len(sweep_findings) >= 1


# --------------------------------------------------------------------------- #
# Consolidated Phase 2 exit-criterion check across all real fixtures together
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kind,filename",
    [
        ("har", "real_login.har"),
        ("saml_response", "good_saml_response.xml"),
        ("saml_response", "faulted_saml_response.xml"),
    ],
)
def test_every_real_fixture_scans_without_raising(kind, filename):
    """Baseline sanity: every real Phase 0 fixture that has a defined artifact kind
    scans successfully end to end. (good_trusted_cert.txt / faulted_stale_trusted_cert.txt
    are desk/verify inputs with no defined custody artifact kind, so they're
    intentionally not included here.)"""
    result = run_custody(kind, _read(filename))
    assert isinstance(result, CustodyResult)
    assert isinstance(result.defanged_bytes, bytes)
