"""Email and group-membership PII detection.

KNOWN_GROUP_ATTRIBUTE_NAMES is grounded in Phase 0's documented Keycloak quirk
(docs/PHASE0_NOTES.md): the default SAML client emits one <Attribute Name="Role"> per
realm role. Other IdPs use different attribute names for group/role claims (Entra's
"groups", Okta's "groups" or a custom claim) -- not covered here, same Keycloak-only
naming caveat as detectors/cookies.py.
"""

from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

KNOWN_GROUP_ATTRIBUTE_NAMES = {"Role", "role", "Group", "group", "groups"}
