"""Phase 1 exit criteria (plan §27): one positive and one negative fixture per check,
plus a property test that no check ever returns VERIFIED when its required evidence is
absent.

Positive cases run against the real, unmutated Phase 0 good_saml_response.xml fixture
wherever its real field values naturally exercise a check's VERIFIED branch (most of
them do, once the VerificationContext is fully populated with matching expected values
and an evaluation_time pinned inside the assertion's real validity window). Two checks
need something more: SAML-ATTR-01's positive branch requires attribute Names that are
NOT duplicated, and the real fixture's Names ARE duplicated on purpose (see
docs/PHASE0_NOTES.md); SAML-CERT-01's negative (expired-certificate) branch has no real
fixture at all, because nothing here has ever captured a response signed by an actually-
expired cert. Both are called out explicitly at the point they're built, so it's never
ambiguous which fixtures are "real, not authored" (Phase 0's standard) and which are
synthetic unit-test-only mutations built to exercise one specific branch.
"""

from __future__ import annotations

import datetime
import os

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from desk.verify.assurance import Assurance
from desk.verify.checks import ALL_CHECKS
from desk.verify.context import VerificationContext
from desk.verify.verifier import run_all_checks

FIXTURES = os.path.join(os.path.dirname(__file__), "phase0_fixtures")


def _read(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def _read_text(name: str) -> str:
    with open(os.path.join(FIXTURES, name)) as f:
        return f.read()


GOOD_BYTES = _read("good_saml_response.xml")
GOOD_CERT = _read_text("good_trusted_cert.txt")
FAULTED_BYTES = _read("faulted_saml_response.xml")
STALE_CERT = _read_text("faulted_stale_trusted_cert.txt")

# Real field values pulled from the real good fixture (see the module docstring's
# rationale). Hardcoded here rather than re-parsed, so a bug in the parser can't
# silently make this test agree with itself.
GOOD_IDP_ENTITY_ID = "http://127.0.0.1:8080/realms/assertion-desk"
GOOD_SP_ENTITY_ID = "http://127.0.0.1:9091/saml/metadata"
GOOD_ACS_URL = "http://127.0.0.1:9091/saml/acs"
GOOD_IN_RESPONSE_TO = "ONELOGIN_60bc2aa71441e402fe683c36855cfeb9842d7e1c"
GOOD_ISSUE_INSTANT = datetime.datetime(2026, 8, 16, 6, 52, 5, 696000, tzinfo=datetime.timezone.utc)
GOOD_EVAL_TIME = datetime.datetime(2026, 8, 16, 6, 52, 30, tzinfo=datetime.timezone.utc)  # inside Conditions AND SCD windows


def full_good_context(**overrides) -> VerificationContext:
    """Every piece of independent evidence a real SP would actually have, all matching
    the real good fixture, so every check that *can* go VERIFIED, does."""
    kwargs = dict(
        sp_entity_id=GOOD_SP_ENTITY_ID,
        acs_url=GOOD_ACS_URL,
        idp_entity_id=GOOD_IDP_ENTITY_ID,
        trusted_cert_pem=GOOD_CERT,
        in_response_to_expected=GOOD_IN_RESPONSE_TO,
        sp_clock=GOOD_ISSUE_INSTANT,
        evaluation_time=GOOD_EVAL_TIME,
    )
    kwargs.update(overrides)
    return VerificationContext(**kwargs)


def run(raw_bytes: bytes, ctx: VerificationContext):
    return run_all_checks(raw_bytes, ctx)


# ---------------------------------------------------------------------------
# Positive cases: real fixture, fully populated context -> every check that has a
# VERIFIED branch reaches it.
# ---------------------------------------------------------------------------

POSITIVE_VERIFIED_CHECK_IDS = [
    "SAML-SIG-01", "SAML-SIG-02", "SAML-CERT-01", "SAML-CERT-02",
    "SAML-ISS-01", "SAML-ISS-02", "SAML-AUD-01", "SAML-DEST-01", "SAML-RECIP-01",
    "SAML-INRESP-01", "SAML-INRESP-02", "SAML-SKEW-01", "SAML-COND-01", "SAML-COND-02",
    "SAML-NAMEID-01", "SAML-NAMEID-02", "SAML-SCM-01", "SAML-STATUS-01", "SAML-ENC-01",
]


@pytest.mark.parametrize("check_id", POSITIVE_VERIFIED_CHECK_IDS)
def test_positive_case_is_verified(check_id):
    run_result = run(GOOD_BYTES, full_good_context())
    result = run_result.by_id(check_id)
    assert result is not None, f"{check_id} did not run"
    assert result.assurance == Assurance.VERIFIED, (check_id, result.assurance, result.reason)


def test_attr_01_positive_needs_deduplicated_attribute_names():
    """The real fixture's Attribute Names ARE duplicated on purpose (the documented
    Keycloak quirk) -- so its own SAML-ATTR-01 result is REVIEW_REQUIRED, not VERIFIED,
    and that's covered by test_attr_01_negative_real_fixture_has_duplicates below. To
    exercise the VERIFIED branch at all, this mutates the six duplicate Name="Role"
    attributes to unique names. This is a synthetic unit-test fixture, not a Phase-0-style
    "real, not authored" artifact -- it exists to prove the check's VERIFIED branch is
    reachable, nothing more."""
    mutated = GOOD_BYTES
    for i in range(6):
        mutated = mutated.replace(b'Name="Role"', f'Name="Role{i}"'.encode(), 1)
    assert b'Name="Role"' not in mutated  # sanity: all six were actually replaced

    run_result = run(mutated, full_good_context())
    result = run_result.by_id("SAML-ATTR-01")
    assert result.assurance == Assurance.VERIFIED, result.reason


# ---------------------------------------------------------------------------
# Negative cases: one deliberately-wrong fixture or context per check.
# ---------------------------------------------------------------------------

def test_sig_01_and_sig_02_fail_on_faulted_artifact():
    run_result = run(FAULTED_BYTES, full_good_context(trusted_cert_pem=STALE_CERT))
    assert run_result.by_id("SAML-SIG-01").assurance == Assurance.FAILED
    assert run_result.by_id("SAML-SIG-02").assurance == Assurance.FAILED


def test_cert_02_fails_on_faulted_artifact_stale_cert():
    run_result = run(FAULTED_BYTES, full_good_context(trusted_cert_pem=STALE_CERT))
    result = run_result.by_id("SAML-CERT-02")
    assert result.assurance == Assurance.FAILED
    assert "thumbprint" in result.reason


def _generate_expired_cert_pem() -> str:
    """A self-signed cert whose validity window already closed, built at test time.
    Exists solely to exercise SAML-CERT-01's FAILED branch -- no real capture in this
    project has ever been signed by an actually-expired certificate, so there is no real
    artifact to use instead. Synthetic and labeled as such, per the module docstring."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "expired-test-cert")])
    not_before = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    not_after = datetime.datetime(2020, 6, 1, tzinfo=datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def test_cert_01_fails_on_expired_certificate():
    expired_pem = _generate_expired_cert_pem()
    run_result = run(GOOD_BYTES, full_good_context(trusted_cert_pem=expired_pem))
    result = run_result.by_id("SAML-CERT-01")
    assert result.assurance == Assurance.FAILED
    assert "expired" in result.reason


def test_iss_01_and_iss_02_fail_on_wrong_idp_entity_id():
    run_result = run(GOOD_BYTES, full_good_context(idp_entity_id="http://evil.example/realms/other"))
    assert run_result.by_id("SAML-ISS-01").assurance == Assurance.FAILED
    assert run_result.by_id("SAML-ISS-02").assurance == Assurance.FAILED


def test_aud_01_fails_on_wrong_sp_entity_id():
    run_result = run(GOOD_BYTES, full_good_context(sp_entity_id="http://other-app.example/saml/metadata"))
    result = run_result.by_id("SAML-AUD-01")
    assert result.assurance == Assurance.FAILED


def test_dest_01_fails_on_wrong_acs_url():
    run_result = run(GOOD_BYTES, full_good_context(acs_url="http://other-app.example/saml/acs"))
    assert run_result.by_id("SAML-DEST-01").assurance == Assurance.FAILED


def test_recip_01_fails_on_wrong_acs_url():
    # Destination and Recipient happen to carry the same URL in the real capture, so
    # the same wrong-acs_url context fails both checks -- correctly, since they're
    # independently computed from different XML elements, not from each other.
    run_result = run(GOOD_BYTES, full_good_context(acs_url="http://other-app.example/saml/acs"))
    assert run_result.by_id("SAML-RECIP-01").assurance == Assurance.FAILED


def test_inresp_01_and_02_fail_on_wrong_expected_value():
    run_result = run(GOOD_BYTES, full_good_context(in_response_to_expected="ONELOGIN_wrong_value"))
    assert run_result.by_id("SAML-INRESP-01").assurance == Assurance.FAILED
    assert run_result.by_id("SAML-INRESP-02").assurance == Assurance.FAILED


def test_skew_01_fails_when_sp_clock_is_far_off():
    far_off = GOOD_ISSUE_INSTANT + datetime.timedelta(hours=1)
    run_result = run(GOOD_BYTES, full_good_context(sp_clock=far_off))
    result = run_result.by_id("SAML-SKEW-01")
    assert result.assurance == Assurance.FAILED


def test_cond_01_fails_when_evaluated_after_expiry():
    after_expiry = datetime.datetime(2026, 8, 16, 8, 0, 0, tzinfo=datetime.timezone.utc)
    run_result = run(GOOD_BYTES, full_good_context(evaluation_time=after_expiry))
    result = run_result.by_id("SAML-COND-01")
    assert result.assurance == Assurance.FAILED
    assert "expired" in result.reason


def test_cond_02_fails_when_evaluated_after_scd_expiry():
    after_expiry = datetime.datetime(2026, 8, 16, 8, 0, 0, tzinfo=datetime.timezone.utc)
    run_result = run(GOOD_BYTES, full_good_context(evaluation_time=after_expiry))
    result = run_result.by_id("SAML-COND-02")
    assert result.assurance == Assurance.FAILED


def test_nameid_01_fails_when_nameid_is_emptied():
    mutated = GOOD_BYTES.replace(b">alice@example.test<", b"><", 1)
    run_result = run(mutated, full_good_context())
    result = run_result.by_id("SAML-NAMEID-01")
    assert result.assurance == Assurance.FAILED


def test_nameid_02_is_review_required_for_a_nonstandard_format():
    mutated = GOOD_BYTES.replace(
        b'Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"',
        b'Format="urn:mycompany:custom-nameid-format"',
        1,
    )
    run_result = run(mutated, full_good_context())
    result = run_result.by_id("SAML-NAMEID-02")
    assert result.assurance == Assurance.REVIEW_REQUIRED


def test_scm_01_fails_on_wrong_method():
    mutated = GOOD_BYTES.replace(
        b'Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"',
        b'Method="urn:oasis:names:tc:SAML:2.0:cm:holder-of-key"',
        1,
    )
    run_result = run(mutated, full_good_context())
    result = run_result.by_id("SAML-SCM-01")
    assert result.assurance == Assurance.FAILED


def test_status_01_fails_on_non_success_status():
    mutated = GOOD_BYTES.replace(
        b'Value="urn:oasis:names:tc:SAML:2.0:status:Success"',
        b'Value="urn:oasis:names:tc:SAML:2.0:status:AuthnFailed"',
        1,
    )
    run_result = run(mutated, full_good_context())
    result = run_result.by_id("SAML-STATUS-01")
    assert result.assurance == Assurance.FAILED


def test_attr_01_negative_real_fixture_has_duplicates():
    """No mutation: the real captured fixture genuinely has this shape (see
    docs/PHASE0_NOTES.md)."""
    run_result = run(GOOD_BYTES, full_good_context())
    result = run_result.by_id("SAML-ATTR-01")
    assert result.assurance == Assurance.REVIEW_REQUIRED
    assert "Role" in result.observed


def test_enc_01_is_not_applicable_for_an_encrypted_assertion():
    mutated = GOOD_BYTES.replace(
        b"</saml:Assertion>",
        b'<xenc:EncryptedData xmlns:xenc="http://www.w3.org/2001/04/xmlenc#"/></saml:Assertion>',
        1,
    )
    run_result = run(mutated, full_good_context())
    result = run_result.by_id("SAML-ENC-01")
    assert result.assurance == Assurance.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Property test: absence of required evidence never yields VERIFIED, for every check.
# ---------------------------------------------------------------------------

# Checks whose VERIFIED branch requires a specific piece of *optional* SP-supplied
# evidence (a pinned cert, an expected InResponseTo, an SP clock) -- as opposed to the
# SP's own always-known identity config (entity IDs, ACS URL), which isn't "evidence
# that can be missing" in the same sense and is supplied in every context in this file.
EVIDENCE_DEPENDENT_CHECK_IDS = [
    "SAML-SIG-01", "SAML-SIG-02", "SAML-CERT-01", "SAML-CERT-02",
    "SAML-INRESP-01", "SAML-INRESP-02", "SAML-SKEW-01",
]

# Checks that require a parsed Assertion to say anything at all. Response-level checks
# (Issuer, Destination, Status, the response's own Signature, the pinned cert's own
# validity window) are deliberately answerable even when a response carries no
# assertion -- that's real information a support engineer wants ("the response itself
# looks right, but there's no assertion in it at all"), not a gap.
ASSERTION_SCOPED_CHECK_IDS = [
    "SAML-SIG-02", "SAML-CERT-02", "SAML-ISS-02", "SAML-AUD-01", "SAML-RECIP-01",
    "SAML-INRESP-02", "SAML-COND-01", "SAML-COND-02", "SAML-NAMEID-01", "SAML-NAMEID-02",
    "SAML-SCM-01", "SAML-ATTR-01", "SAML-ENC-01",
]


@pytest.mark.parametrize("check_id", EVIDENCE_DEPENDENT_CHECK_IDS)
def test_evidence_dependent_check_never_verifies_without_its_evidence(check_id):
    """The core Phase 1 property (plan §27): a check whose required artifact is absent
    must never return VERIFIED. bare_ctx supplies the SP's own identity config (always
    known) but omits every optional piece of evidence -- no pinned cert, no expected
    InResponseTo, no SP clock."""
    bare_ctx = VerificationContext(
        sp_entity_id=GOOD_SP_ENTITY_ID,
        acs_url=GOOD_ACS_URL,
        idp_entity_id=GOOD_IDP_ENTITY_ID,
        # trusted_cert_pem, in_response_to_expected, sp_clock all default to None
    )
    run_result = run(GOOD_BYTES, bare_ctx)
    result = run_result.by_id(check_id)
    assert result.assurance == Assurance.NOT_VERIFIED, (check_id, result.assurance, result.reason)


@pytest.mark.parametrize("check_id", ASSERTION_SCOPED_CHECK_IDS)
def test_assertion_scoped_check_never_verifies_on_an_empty_response(check_id):
    """A response with no assertions at all (the Response element survives, everything
    inside it is gone) -- every assertion-scoped check must report NOT_VERIFIED, never
    fabricate a VERIFIED from nothing, even with a fully-populated context otherwise."""
    empty_response = (
        b'<?xml version="1.0"?>'
        b'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        b'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_empty" '
        b'IssueInstant="2026-08-16T06:52:05Z" Destination="' + GOOD_ACS_URL.encode() + b'">'
        b'<saml:Issuer>' + GOOD_IDP_ENTITY_ID.encode() + b'</saml:Issuer>'
        b'<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
        b'</samlp:Response>'
    )
    run_result = run(empty_response, full_good_context())
    result = run_result.by_id(check_id)
    assert result.assurance == Assurance.NOT_VERIFIED, (check_id, result.assurance, result.reason)


def test_all_checks_produce_exactly_one_result_each():
    """Sanity check on the orchestrator itself: every registered check runs exactly
    once and none silently vanish or duplicate."""
    run_result = run(GOOD_BYTES, full_good_context())
    assert len(run_result.results) == len(ALL_CHECKS)
    ids = [r.check_id for r in run_result.results]
    assert len(ids) == len(set(ids)), f"duplicate check_id in results: {ids}"
