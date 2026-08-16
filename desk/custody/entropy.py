"""Shannon entropy, used only as a low-confidence fallback signal for spotting opaque,
unlabeled secrets (an unrecognized IdP's session cookie, a stray API key) that don't
match a known name or a structural pattern like a JWT. This is deliberately the
least-trusted detector in the module: high entropy alone produces false positives on
things like request IDs and cache-busting query params, so it is only ever combined
with a second weak signal (a cookie name that isn't a known UI preference, a header
context that suggests a credential) rather than used standalone.
"""

from __future__ import annotations

import math
from collections import Counter


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    length = len(s)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())
