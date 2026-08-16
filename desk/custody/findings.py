"""The CustodyFinding record and its enums (plan section 19's data model).

CustodyFinding is deliberately shaped so a cleartext secret value cannot enter it --
there is no field capable of holding one (no ``value``, ``raw``, or ``secret`` field
anywhere below). ``placeholder_token`` holds a stable, non-reversible correlation
identifier instead (desk/custody/placeholders.py). This is a schema-level guarantee,
not a runtime one: it means "the type of data this module produces cannot carry a
secret," independent of whether a database ever exists to store it in (Phase 5 adds
persistence; the guarantee already holds without it).

PLAINTEXT_CREDENTIAL is an addition beyond the plan's original sketch (idp_session_
cookie/bearer_token/oauth_refresh_token/api_key/private_key/nameid_pii/email_pii/
group_membership). It was added after reading the real captured HAR
(tests/verify/phase0_fixtures/real_login.har, entry 12), which contains a literal
``password=alice_dev_only`` in a login POST body -- a customer's HAR of their own
login attempt will very often contain exactly this, and a custody module with no
category for the single most common secret in an SSO debugging HAR would be a real,
embarrassing gap. Named and justified here rather than silently forced into api_key
or dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FindingClass(str, Enum):
    IDP_SESSION_COOKIE = "idp_session_cookie"
    BEARER_TOKEN = "bearer_token"
    OAUTH_REFRESH_TOKEN = "oauth_refresh_token"
    PLAINTEXT_CREDENTIAL = "plaintext_credential"  # extension beyond plan section 19; see module docstring
    API_KEY = "api_key"
    PRIVATE_KEY = "private_key"
    NAMEID_PII = "nameid_pii"
    EMAIL_PII = "email_pii"
    GROUP_MEMBERSHIP = "group_membership"


class Liveness(str, Enum):
    LIVE = "live"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


class Action(str, Enum):
    REPLACED = "replaced"
    DROPPED = "dropped"
    # A third value beyond the plan's original replaced/dropped pair, needed for one
    # real case: a SAML NameID or group-membership Attribute value is PII, but it is
    # also evidence desk/verify structurally needs (SAML-NAMEID-01/02 check its
    # presence and format; redacting it inside signed XML would break the exact
    # verification this project's core mechanism depends on). RECORDED_ONLY means the
    # finding is logged for the data-minimization audit trail, but the value is left
    # untouched in the artifact copy the verifier operates on. It is still kept out of
    # the model prompt, enforced separately at desk/reason's boundary (Job C receives
    # check results, never raw artifacts) rather than by mutating this artifact.
    RECORDED_ONLY = "recorded_only"


@dataclass(frozen=True)
class CustodyFinding:
    finding_class: FindingClass
    location: str  # e.g. "har.entries[12].request.postData.form[password]"
    placeholder_token: str
    liveness: Liveness
    action: Action
    detector: str
    detector_version: str
