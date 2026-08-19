"""Provision a realm, a SAML client, and a test user in Keycloak via the Admin REST API.

Deliberately not a realm-import JSON. A script against the Admin REST API is more
debuggable step by step, and it is the same shape the fault injectors in harness/faults/
will reuse later (e.g. rotating the realm's signing key means one more REST call, not a
hand-edited JSON blob).

Usage:
    .venv/bin/python3 harness/capture/keycloak_admin.py setup
    .venv/bin/python3 harness/capture/keycloak_admin.py teardown
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET  # trusted, local Keycloak-generated metadata only

import requests

KC_BASE = "http://127.0.0.1:8080"
ADMIN_USER = "admin"
ADMIN_PASSWORD = "admin_dev_only"

REALM = "assertion-desk"
SP_ENTITY_ID = "http://127.0.0.1:9091/saml/metadata"
SP_ACS_URL = "http://127.0.0.1:9091/saml/acs"
CLIENT_ID = SP_ENTITY_ID  # Keycloak SAML clients are keyed by entity ID

TEST_USER = "alice"
TEST_PASSWORD = "alice_dev_only"
TEST_EMAIL = "alice@example.test"


def get_admin_token() -> str:
    resp = requests.post(
        f"{KC_BASE}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": ADMIN_USER,
            "password": ADMIN_PASSWORD,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def realm_exists(token: str) -> bool:
    resp = requests.get(f"{KC_BASE}/admin/realms/{REALM}", headers=h(token), timeout=10)
    return resp.status_code == 200


def create_realm(token: str) -> None:
    if realm_exists(token):
        print(f"realm {REALM!r} already exists, skipping create")
        return
    body = {
        "realm": REALM,
        "enabled": True,
        "sslRequired": "none",  # local dev IdP over plain HTTP, never a real deployment
    }
    resp = requests.post(f"{KC_BASE}/admin/realms", headers=h(token), json=body, timeout=10)
    resp.raise_for_status()
    print(f"created realm {REALM!r}")


def create_saml_client(token: str) -> str:
    resp = requests.get(
        f"{KC_BASE}/admin/realms/{REALM}/clients",
        headers=h(token),
        params={"clientId": CLIENT_ID},
        timeout=10,
    )
    resp.raise_for_status()
    existing = resp.json()
    if existing:
        print(f"SAML client {CLIENT_ID!r} already exists, skipping create")
        return existing[0]["id"]

    body = {
        "clientId": CLIENT_ID,
        "protocol": "saml",
        "enabled": True,
        "redirectUris": [SP_ACS_URL],
        "attributes": {
            "saml.assertion.signature": "true",
            "saml.server.signature": "true",
            "saml.client.signature": "false",
            "saml_assertion_consumer_url_post": SP_ACS_URL,
            "saml_single_logout_service_url_post": "",
            "saml_name_id_format": "email",
            "saml.authnstatement": "true",
        },
    }
    resp = requests.post(f"{KC_BASE}/admin/realms/{REALM}/clients", headers=h(token), json=body, timeout=10)
    resp.raise_for_status()
    location = resp.headers["Location"]
    client_uuid = location.rstrip("/").split("/")[-1]
    print(f"created SAML client {CLIENT_ID!r} (uuid {client_uuid})")
    return client_uuid


def create_test_user(token: str) -> None:
    resp = requests.get(
        f"{KC_BASE}/admin/realms/{REALM}/users",
        headers=h(token),
        params={"username": TEST_USER, "exact": "true"},
        timeout=10,
    )
    resp.raise_for_status()
    if resp.json():
        print(f"user {TEST_USER!r} already exists, skipping create")
        return

    body = {
        "username": TEST_USER,
        "email": TEST_EMAIL,
        "firstName": "Alice",
        "lastName": "Example",
        "enabled": True,
        "emailVerified": True,
        "requiredActions": [],  # avoid Keycloak's default "Update Account Information" interstitial
        "credentials": [{"type": "password", "value": TEST_PASSWORD, "temporary": False}],
    }
    resp = requests.post(f"{KC_BASE}/admin/realms/{REALM}/users", headers=h(token), json=body, timeout=10)
    resp.raise_for_status()
    print(f"created user {TEST_USER!r}")


def fetch_idp_metadata() -> str:
    """Fetch the realm's SAML IdP descriptor XML (real Keycloak output, not authored)."""
    resp = requests.get(
        f"{KC_BASE}/realms/{REALM}/protocol/saml/descriptor",
        timeout=10,
    )
    resp.raise_for_status()
    return resp.text


def summarize_metadata(xml_text: str) -> None:
    ns = {"md": "urn:oasis:names:tc:SAML:2.0:metadata", "ds": "http://www.w3.org/2000/09/xmldsig#"}
    root = ET.fromstring(xml_text)
    cert_el = root.find(".//ds:X509Certificate", ns)
    entity_id = root.get("entityID")
    print(f"IdP entityID: {entity_id}")
    print(f"IdP signing cert present: {cert_el is not None}")


def setup() -> None:
    token = get_admin_token()
    create_realm(token)
    create_saml_client(token)
    create_test_user(token)
    metadata = fetch_idp_metadata()
    with open("harness/capture/idp-metadata.xml", "w") as f:
        f.write(metadata)
    summarize_metadata(metadata)
    print("wrote harness/capture/idp-metadata.xml")
    print()
    print("Realm setup complete:")
    print(f"  realm:        {REALM}")
    print(f"  SP entity id: {SP_ENTITY_ID}")
    print(f"  SP ACS url:   {SP_ACS_URL}")
    # Credential value intentionally not echoed here, even though TEST_PASSWORD is a
    # fixed, disposable, non-secret literal for a local-only Keycloak realm (see the
    # module constants above): printing a credential to stdout is a bad pattern to
    # have in this codebase regardless of whether this particular value matters.
    print(f"  test user:    {TEST_USER} (password: see TEST_PASSWORD in this file)")
    print(f"  SSO URL:      {KC_BASE}/realms/{REALM}/protocol/saml")


def teardown() -> None:
    token = get_admin_token()
    if realm_exists(token):
        resp = requests.delete(f"{KC_BASE}/admin/realms/{REALM}", headers=h(token), timeout=10)
        resp.raise_for_status()
        print(f"deleted realm {REALM!r}")
    else:
        print(f"realm {REALM!r} does not exist, nothing to do")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "setup"
    if action == "setup":
        setup()
    elif action == "teardown":
        teardown()
    else:
        print(f"unknown action {action!r}, expected setup|teardown")
        sys.exit(1)
