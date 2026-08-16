"""Twenty fault injectors, each a FaultSpec (see base.py), spanning four honest
mechanisms -- LIVE_CAPTURE, CONTEXT_MISMATCH, ARTIFACT_MUTATION, DOCUMENTED_GAP -- and
covering every real check family in desk/verify/checks/ at least once, plus the malformed
and no-coverage strata the check catalogue was never meant to handle.

Mirrors desk/verify/checks/__init__.py's ALL_CHECKS pattern deliberately: one flat list,
imported explicitly (no dynamic module scanning), so a reader can see the whole catalogue
in one file and so tests/harness/test_corpus.py's label-sanity check has one place to walk.
"""

from __future__ import annotations

from harness.faults.acs_url_trailing_slash import FAULT as ACS_URL_TRAILING_SLASH
from harness.faults.assertion_expired import FAULT as ASSERTION_EXPIRED
from harness.faults.broken_signature import FAULT as BROKEN_SIGNATURE
from harness.faults.cert_expired import FAULT as CERT_EXPIRED
from harness.faults.cert_rotation import FAULT as CERT_ROTATION
from harness.faults.clock_skew import FAULT as CLOCK_SKEW
from harness.faults.destination_mismatch import FAULT as DESTINATION_MISMATCH
from harness.faults.double_encoded_response import FAULT as DOUBLE_ENCODED_RESPONSE
from harness.faults.encrypted_assertion import FAULT as ENCRYPTED_ASSERTION
from harness.faults.http_https_mismatch import FAULT as HTTP_HTTPS_MISMATCH
from harness.faults.inresponseto_mismatch import FAULT as INRESPONSETO_MISMATCH
from harness.faults.missing_nameid import FAULT as MISSING_NAMEID
from harness.faults.negative_control import FAULT as NEGATIVE_CONTROL
from harness.faults.sha1_signature_downgrade import FAULT as SHA1_SIGNATURE_DOWNGRADE
from harness.faults.stripped_relaystate import FAULT as STRIPPED_RELAYSTATE
from harness.faults.truncated_response import FAULT as TRUNCATED_RESPONSE
from harness.faults.unsupported_nameid_format import FAULT as UNSUPPORTED_NAMEID_FORMAT
from harness.faults.wrong_audience import FAULT as WRONG_AUDIENCE
from harness.faults.wrong_binding import FAULT as WRONG_BINDING
from harness.faults.wrong_issuer import FAULT as WRONG_ISSUER

ALL_FAULTS = [
    CERT_ROTATION,
    CERT_EXPIRED,
    WRONG_AUDIENCE,
    ACS_URL_TRAILING_SLASH,
    HTTP_HTTPS_MISMATCH,
    DESTINATION_MISMATCH,
    WRONG_ISSUER,
    CLOCK_SKEW,
    ASSERTION_EXPIRED,
    INRESPONSETO_MISMATCH,
    SHA1_SIGNATURE_DOWNGRADE,
    BROKEN_SIGNATURE,
    MISSING_NAMEID,
    UNSUPPORTED_NAMEID_FORMAT,
    ENCRYPTED_ASSERTION,
    TRUNCATED_RESPONSE,
    DOUBLE_ENCODED_RESPONSE,
    STRIPPED_RELAYSTATE,
    WRONG_BINDING,
    NEGATIVE_CONTROL,
]

# fail fast, at import time, if two faults ever collide on fault_id -- the corpus
# generator keys case directories by fault_id, so a collision would silently overwrite
# one case's artifacts with another's.
_ids = [f.fault_id for f in ALL_FAULTS]
if len(_ids) != len(set(_ids)):
    dupes = {i for i in _ids if _ids.count(i) > 1}
    raise ValueError(f"duplicate fault_id(s) in ALL_FAULTS: {dupes}")

__all__ = ["ALL_FAULTS"]
