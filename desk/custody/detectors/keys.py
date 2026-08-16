"""Private-key and API-key pattern detection."""

from __future__ import annotations

import re

PEM_KEY_RE = re.compile(
    rb"-----BEGIN ((?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY)-----"
    rb".*?-----END \1-----",
    re.DOTALL,
)

# AWS access key IDs are structurally distinctive enough to detect by pattern alone.
# No real value of this shape exists anywhere in this project's own local Keycloak/SP
# corpus; the pattern is here for the general case, not because it fired on a fixture.
AWS_ACCESS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}")

API_KEY_FIELD_NAMES = {"api_key", "apikey", "x-api-key", "client_secret", "secret"}


def is_api_key_field(field_name: str) -> bool:
    return field_name.lower() in API_KEY_FIELD_NAMES
