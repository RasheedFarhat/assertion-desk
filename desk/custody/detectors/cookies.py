"""Session-cookie detection.

KNOWN_SESSION_COOKIE_NAMES is grounded in the real Keycloak capture from Phase 0
(tests/verify/phase0_fixtures/real_login.har): KC_RESTART, KEYCLOAK_IDENTITY,
KEYCLOAK_SESSION, AUTH_SESSION_ID, and KC_AUTH_SESSION_HASH are the five cookies a real
Keycloak login actually sets. Other IdPs' session cookie names (Okta's ``sid``, Entra's
``ESTSAUTH``/``ESTSAUTHPERSISTENT``, Ping's ``PF``) are not in this allowlist -- this
project has never captured a real login against them (the same Keycloak-only naming
caveat that applies everywhere else in this repo applies here). looks_like_session_
cookie() is a lower-confidence fallback for exactly that gap, named and scoped rather
than silently assumed complete.

A cookie value is classified as idp_session_cookie regardless of whether it is itself
JWT-shaped internally (KEYCLOAK_IDENTITY's real value is a JWT). Classification follows
storage location, not internal shape, so a single credential is never double-counted
under two finding classes.
"""

from __future__ import annotations

from desk.custody.entropy import shannon_entropy

KNOWN_SESSION_COOKIE_NAMES = {
    "KC_RESTART",
    "KEYCLOAK_IDENTITY",
    "KEYCLOAK_SESSION",
    "AUTH_SESSION_ID",
    "KC_AUTH_SESSION_HASH",
}

# Cookie names that are routinely non-sensitive UI/analytics state, excluded from the
# generic fallback so it doesn't flag every consent banner as a live credential.
LIKELY_BENIGN_NAMES = {"theme", "locale", "lang", "consent", "cookie_consent"}

ENTROPY_THRESHOLD = 3.0
MIN_LENGTH = 16


def is_known_session_cookie(name: str) -> bool:
    return name in KNOWN_SESSION_COOKIE_NAMES


def looks_like_session_cookie(name: str, value: str) -> bool:
    if name.lower() in LIKELY_BENIGN_NAMES:
        return False
    if len(value) < MIN_LENGTH:
        return False
    return shannon_entropy(value) >= ENTROPY_THRESHOLD


def set_cookie_is_being_cleared(set_cookie_value: str) -> bool:
    """True for a Set-Cookie line that is tearing the cookie down (Max-Age=0 or an
    Expires in the clearly-past epoch), which is a real, cheap liveness signal --
    KC_RESTART's own Set-Cookie in the real fixture does exactly this."""
    lowered = set_cookie_value.lower()
    return "max-age=0" in lowered.replace(" ", "")
