"""Stable placeholder tokens for redacted values.

A placeholder is ``{{PREFIX:hash8}}`` where ``hash8`` is the first 8 hex characters of
the SHA-256 of the exact raw secret value. "Stable" means the same secret value always
maps to the same placeholder within one artifact, so a human (or the model) reading a
de-fanged HAR can still see "the same cookie shows up in 3 requests" without ever
seeing what it actually is.

This hash is a correlation identifier, not a security control, and that distinction is
worth being explicit about: 8 hex characters derived from a high-entropy secret cannot
be meaningfully strengthened into protection by using more of the digest, because the
only way to "invert" it is to already hold a candidate value and check whether it
matches -- which confirms a guess, it does not discover the secret. Its only job is
letting the same credential be recognized twice without ever being shown once.
"""

from __future__ import annotations

import hashlib

from desk.custody.findings import FindingClass

_PREFIX = {
    FindingClass.IDP_SESSION_COOKIE: "COOKIE",
    FindingClass.BEARER_TOKEN: "JWT",
    FindingClass.OAUTH_REFRESH_TOKEN: "REFRESH",
    FindingClass.PLAINTEXT_CREDENTIAL: "PASSWORD",
    FindingClass.API_KEY: "APIKEY",
    FindingClass.PRIVATE_KEY: "PRIVATEKEY",
    FindingClass.NAMEID_PII: "NAMEID",
    FindingClass.EMAIL_PII: "EMAIL",
    FindingClass.GROUP_MEMBERSHIP: "GROUP",
}


def placeholder_for(raw_value: str, finding_class: FindingClass) -> str:
    digest = hashlib.sha256(raw_value.encode("utf-8", errors="surrogateescape")).hexdigest()[:8]
    prefix = _PREFIX[finding_class]
    return f"{{{{{prefix}:{digest}}}}}"


# Reverse of _PREFIX, public: lets a caller that only has a placeholder string (e.g.
# desk/custody/scan.py's cross-artifact correlation sweep, which redacts an already-
# confirmed value into a new location without re-deriving its classification) recover
# which FindingClass produced it.
PREFIX_TO_FINDING_CLASS = {prefix: finding_class for finding_class, prefix in _PREFIX.items()}


def finding_class_for_placeholder(placeholder: str) -> FindingClass:
    prefix = placeholder.strip("{}").split(":", 1)[0]
    return PREFIX_TO_FINDING_CLASS[prefix]
