"""Minimal SAML SP for Phase 0 artifact capture.

Deliberately thin: /saml/metadata, /saml/login (redirect to Keycloak), and /saml/acs
(receive and dump the POSTed SAMLResponse to disk, unverified). This SP does NOT verify
signatures itself -- verification is desk/verify/'s job, done independently against the
captured artifact so the check and the thing producing the artifact are not the same code.
"""

from __future__ import annotations

import json
import os

from flask import Flask, request, redirect, Response
from onelogin.saml2.auth import OneLogin_Saml2_Auth

SETTINGS_DIR = os.path.join(os.path.dirname(__file__), "sp_settings")
CAPTURE_DIR = os.path.join(os.path.dirname(__file__), "captured")
os.makedirs(CAPTURE_DIR, exist_ok=True)

app = Flask(__name__)


def init_saml_auth(req: dict) -> OneLogin_Saml2_Auth:
    return OneLogin_Saml2_Auth(req, custom_base_path=SETTINGS_DIR)


def prepare_flask_request(flask_req) -> dict:
    url_data = flask_req.url.split("?", 1)
    return {
        "https": "off",
        "http_host": flask_req.host,
        "server_port": flask_req.host.split(":")[1] if ":" in flask_req.host else "9091",
        "script_name": flask_req.path,
        "get_data": flask_req.args.copy(),
        "post_data": flask_req.form.copy(),
        "query_string": url_data[1] if len(url_data) > 1 else "",
    }


@app.route("/saml/metadata")
def metadata():
    req = prepare_flask_request(request)
    auth = init_saml_auth(req)
    settings = auth.get_settings()
    xml = settings.get_sp_metadata()
    errors = settings.validate_metadata(xml)
    if errors:
        return Response(f"metadata invalid: {errors}", status=500)
    return Response(xml, mimetype="text/xml")


@app.route("/saml/login")
def login():
    req = prepare_flask_request(request)
    auth = init_saml_auth(req)
    return redirect(auth.login())


@app.route("/saml/acs", methods=["POST"])
def acs():
    req = prepare_flask_request(request)
    auth = init_saml_auth(req)

    raw_saml_response = request.form.get("SAMLResponse", "")

    # Capture the RAW artifact before touching auth.process_response(), so that even if
    # this SP's own validation is wrong or too strict, the ground-truth artifact on disk
    # is exactly what Keycloak sent -- untouched by this process's opinion of it.
    with open(os.path.join(CAPTURE_DIR, "raw_saml_response_b64.txt"), "w") as f:
        f.write(raw_saml_response)

    import base64

    decoded = base64.b64decode(raw_saml_response)
    with open(os.path.join(CAPTURE_DIR, "saml_response.xml"), "wb") as f:
        f.write(decoded)

    auth.process_response()
    errors = auth.get_errors()

    # Keycloak's default SAML client emits repeated <Attribute Name="Role"> elements
    # (one per realm role) instead of one Attribute with multiple AttributeValues.
    # python3-saml's get_attributes() treats a duplicated Name as invalid and raises.
    # That is a real, interesting SP-side parsing edge case worth keeping as a note for
    # the harness's fault catalogue later -- not something to silently work around by
    # loosening the library. For Phase 0 artifact capture, degrade gracefully instead
    # of 500ing, since attribute extraction isn't what this SP exists to prove.
    try:
        attributes = auth.get_attributes()
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see comment above
        attributes = {"_error": str(exc)}

    result = {
        "errors": errors,
        "last_error_reason": auth.get_last_error_reason(),
        "is_authenticated": auth.is_authenticated(),
        "nameid": auth.get_nameid(),
        "attributes": attributes,
        "session_index": auth.get_session_index(),
    }
    with open(os.path.join(CAPTURE_DIR, "sp_process_result.json"), "w") as f:
        json.dump(result, f, indent=2, default=str)

    if auth.is_authenticated():
        return Response(f"login ok, nameid={auth.get_nameid()}", mimetype="text/plain")
    return Response(f"login failed: {errors} / {auth.get_last_error_reason()}", status=400)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9091, debug=False)
