"""Plaintext credential and opaque flow-authorization-artifact detection in form/JSON
bodies and query strings. See desk/custody/findings.py's module docstring for why
plaintext_credential exists as its own finding class.

FLOW_ARTIFACT_PARAM_NAMES covers one more thing the real fixture actually contains:
Keycloak's own login-actions URL carries a ``session_code`` query parameter, an
opaque, single-use token bound to the browser's in-progress login flow. It isn't a
session cookie, a bearer JWT, or a refresh token -- the closest existing fit is
api_key ("something that grants access to a flow step if replayed"), so that's how
it's classified, with the reasoning kept here rather than left implicit.
"""

from __future__ import annotations

PASSWORD_FIELD_NAMES = {"password", "passwd", "pwd", "pass"}

FLOW_ARTIFACT_PARAM_NAMES = {"session_code", "code"}


def is_password_field(field_name: str) -> bool:
    return field_name.lower() in PASSWORD_FIELD_NAMES


def is_flow_artifact_param(field_name: str) -> bool:
    return field_name.lower() in FLOW_ARTIFACT_PARAM_NAMES
