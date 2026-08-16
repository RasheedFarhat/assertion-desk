"""Structural JWT detection (RFC 7519): three base64url segments, the first of which
decodes to a JSON object containing "alg". This deliberately does not verify the
signature -- custody isn't trying to authenticate the token, only recognize its shape
-- and does not require the payload to decode cleanly, since a truncated or already-
malformed token is still exactly the kind of thing that must never reach a model
prompt.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone

from desk.custody.findings import Liveness

# A candidate scanner for free text / unlabeled bodies: three dot-separated base64url
# runs, each long enough that a stray short string doesn't get flagged. looks_like_jwt()
# below still does the real structural check; this regex only proposes candidates.
JWT_CANDIDATE_RE = re.compile(r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def looks_like_jwt(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 3 or not all(parts):
        return False
    try:
        header = json.loads(_b64url_decode(parts[0]))
    except Exception:
        return False
    return isinstance(header, dict) and "alg" in header


def jwt_liveness(value: str, now: datetime | None = None) -> Liveness:
    now = now or datetime.now(timezone.utc)
    parts = value.split(".")
    if len(parts) != 3:
        return Liveness.UNKNOWN
    try:
        payload = json.loads(_b64url_decode(parts[1]))
    except Exception:
        return Liveness.UNKNOWN
    exp = payload.get("exp") if isinstance(payload, dict) else None
    if not isinstance(exp, (int, float)):
        return Liveness.UNKNOWN
    exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
    return Liveness.LIVE if now < exp_dt else Liveness.EXPIRED
