"""The custody orchestrator: ties every detector module together into working
scan_har() / scan_xml() / scan_text() functions, plus the run_custody() dispatcher
that desk/intake calls.

Fail-closed is the one rule that overrides every other design choice here (plan
section 15/20 T1). Any unexpected internal error -- a detector throwing, an artifact
not matching the shape a "kind" implies -- raises CustodyFailure rather than ever
returning an empty/clean findings list. A case that fails custody halts; nothing
proceeds unredacted. See findings.py's module docstring for the schema-level half of
this guarantee (CustodyFinding has no field that can hold a raw secret) and
docs/PHASE2_NOTES.md for the full writeup once it exists.

Scope boundary, restated because it drives every choice below: the bytes this module
returns exist for what leaves the deterministic-verifier boundary -- model prompts,
logs, persisted storage. desk/verify always reads the artifact's ORIGINAL bytes, never
this module's output. That's why scan_xml() below records NameID and group-membership
findings but does not redact them out of the returned text: signature verification
over redacted XML is impossible, and NameID is verifier-required evidence, not a leak
vector while it stays inside the deterministic Python process. See findings.py's
Action.RECORDED_ONLY for how that's represented.

Cross-artifact correlation: a real captured HAR (tests/verify/phase0_fixtures/
real_login.har) surfaced a real gap during testing -- Keycloak's login flow repeats the
same opaque session_code token across a redirect's response body (embedded in an HTML
form's action URL), a later request's structured queryString[] array, and that same
request's URL string. Detecting it in the URL/queryString is a named-field match, but
its appearance inside free-form response HTML has no field name to key off and isn't
JWT/PEM/email/AWS-key shaped, so no standalone pattern rule catches it. Rather than
inventing a speculative "looks like an opaque token" heuristic (which would false-
positive constantly), _scan_har keeps a transient, function-scoped known_values map
(raw value -> placeholder) populated every time a value is redacted anywhere in the
HAR, then makes one final sweep substituting any of those *exact, already-confirmed*
values wherever else they appear -- including inside response bodies. This is not new
pattern detection; it is consistent redaction of a secret the scan has already proven
is one. known_values is never returned, logged, or attached to a CustodyFinding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode

import defusedxml.ElementTree as DET
from lxml import etree as LET

from desk.custody.detectors import cookies as cookies_mod
from desk.custody.detectors import credentials as credentials_mod
from desk.custody.detectors import keys as keys_mod
from desk.custody.detectors import pii as pii_mod
from desk.custody.detectors import tokens as tokens_mod
from desk.custody.findings import Action, CustodyFinding, FindingClass, Liveness
from desk.custody.placeholders import finding_class_for_placeholder, placeholder_for

SAML_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
GROUP_ATTRIBUTE_TAG = f"{{{SAML_NS}}}Attribute"
NAMEID_TAG = f"{{{SAML_NS}}}NameID"

# What a case's kind implies about which scanner runs. narrative/screenshot_text are
# free prose; har is a Chrome/Firefox HAR export; saml_response and idp_metadata (and
# sp_metadata) are XML. Kept here rather than in desk/intake so the dispatch table and
# the functions it dispatches to can't drift apart.
_XML_KINDS = {"saml_response", "idp_metadata", "sp_metadata"}
_TEXT_KINDS = {"narrative", "screenshot_text"}

# A value must be at least this long before the cross-artifact sweep (see module
# docstring) will substitute it into free text. Without a floor, a short common
# substring (a 4-character session_code fragment, say) could coincidentally match
# unrelated page text and redact something that was never a secret.
_MIN_SWEEP_LENGTH = 12


class CustodyFailure(Exception):
    """Raised instead of ever returning a clean/empty result on internal error.
    Callers must treat this as "the case cannot proceed," never as "no findings."
    """


@dataclass(frozen=True)
class CustodyResult:
    defanged_bytes: bytes
    findings: list[CustodyFinding]

    @property
    def any_live_credential(self) -> bool:
        return any(f.liveness == Liveness.LIVE for f in self.findings)


def run_custody(kind: str, raw_bytes: bytes, *, now: datetime | None = None) -> CustodyResult:
    """The single entry point desk/intake calls. Dispatches on artifact kind and wraps
    every path in fail-closed exception handling."""
    now = now or datetime.now(timezone.utc)
    try:
        if kind == "har":
            return _scan_har(raw_bytes, now)
        if kind in _XML_KINDS:
            return _scan_xml(raw_bytes, now)
        if kind in _TEXT_KINDS:
            return _scan_text(raw_bytes, now)
    except CustodyFailure:
        raise
    except Exception as exc:  # noqa: BLE001 -- deliberate: any internal error fails closed
        raise CustodyFailure(f"custody scan raised an unexpected error for kind={kind!r}: {exc}") from exc
    raise CustodyFailure(f"unknown artifact kind: {kind!r}")


# --------------------------------------------------------------------------- #
# HAR scanning
# --------------------------------------------------------------------------- #


def _scan_har(raw_bytes: bytes, now: datetime) -> CustodyResult:
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CustodyFailure(f"HAR is not valid UTF-8: {exc}") from exc
    try:
        har = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CustodyFailure(f"HAR did not parse as JSON: {exc}") from exc

    entries = har.get("log", {}).get("entries") if isinstance(har, dict) else None
    if not isinstance(entries, list):
        raise CustodyFailure("HAR is missing the required log.entries[] shape")

    findings: list[CustodyFinding] = []
    known_values: dict[str, str] = {}  # raw value -> placeholder; transient, never returned
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        _scan_har_entry(entry, idx, findings, now, known_values)

    _sweep_known_values(har, known_values, "har", findings)

    defanged_bytes = json.dumps(har, indent=2).encode("utf-8")
    return CustodyResult(defanged_bytes=defanged_bytes, findings=findings)


def _sweep_known_values(obj, known_values: dict[str, str], path: str, findings: list[CustodyFinding]) -> None:
    """Final pass: substitute any already-confirmed secret value wherever else it
    appears as a string or a substring of a string, anywhere in the HAR tree. See the
    module docstring for why this exists (the Keycloak session_code case)."""
    if not known_values:
        return
    candidates = [v for v in known_values if len(v) >= _MIN_SWEEP_LENGTH]
    if not candidates:
        return
    # Longest first, so a value that happens to be a prefix/substring of another known
    # value doesn't get partially masked before the longer, more specific one runs.
    candidates.sort(key=len, reverse=True)
    _sweep_node(obj, candidates, known_values, path, findings)


def _sweep_node(obj, candidates: list[str], known_values: dict[str, str], path: str, findings: list[CustodyFinding]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                new_v = _sweep_string(v, candidates, known_values, f"{path}.{k}", findings)
                if new_v is not None:
                    obj[k] = new_v
            else:
                _sweep_node(v, candidates, known_values, f"{path}.{k}", findings)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                new_v = _sweep_string(v, candidates, known_values, f"{path}[{i}]", findings)
                if new_v is not None:
                    obj[i] = new_v
            else:
                _sweep_node(v, candidates, known_values, f"{path}[{i}]", findings)


def _sweep_string(value: str, candidates: list[str], known_values: dict[str, str], location: str, findings: list[CustodyFinding]) -> str | None:
    new_value = value
    changed = False
    for raw in candidates:
        if raw in new_value:
            placeholder = known_values[raw]
            new_value = new_value.replace(raw, placeholder)
            changed = True
            findings.append(
                CustodyFinding(
                    finding_class_for_placeholder(placeholder),
                    location,
                    placeholder,
                    Liveness.UNKNOWN,
                    Action.REPLACED,
                    "scan.cross_artifact_correlation",
                    "1",
                )
            )
    return new_value if changed else None


def _scan_har_entry(entry: dict, idx: int, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str]) -> None:
    loc = f"har.entries[{idx}]"
    request = entry.get("request", {}) or {}
    response = entry.get("response", {}) or {}

    _scan_cookie_array(request.get("cookies", []) or [], f"{loc}.request.cookies", findings, now, known_values)
    _scan_cookie_array(response.get("cookies", []) or [], f"{loc}.response.cookies", findings, now, known_values)
    _scan_header_array(request.get("headers", []) or [], f"{loc}.request.headers", findings, now, known_values)
    _scan_header_array(response.get("headers", []) or [], f"{loc}.response.headers", findings, now, known_values)
    _scan_url_query(request, f"{loc}.request.url", findings, now, known_values)
    _scan_query_string_array(request.get("queryString", []) or [], f"{loc}.request.queryString", findings, now, known_values)

    post_data = request.get("postData")
    if isinstance(post_data, dict):
        if post_data.get("text"):
            new_text = _scan_body_text(post_data["text"], post_data.get("mimeType", ""), f"{loc}.request.postData.text", findings, now, known_values)
            if new_text is not None:
                post_data["text"] = new_text
        _scan_post_params_array(post_data.get("params", []) or [], f"{loc}.request.postData.params", findings, now, known_values)

    content = response.get("content")
    if isinstance(content, dict) and content.get("text"):
        new_text = _scan_body_text(content["text"], content.get("mimeType", ""), f"{loc}.response.content.text", findings, now, known_values)
        if new_text is not None:
            content["text"] = new_text


def _scan_cookie_array(cookie_list: list, loc_prefix: str, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str]) -> None:
    for c in cookie_list:
        if not isinstance(c, dict):
            continue
        name = c.get("name", "")
        value = c.get("value", "")
        if not name or not value:
            continue
        liveness = _har_cookie_liveness(c, now)
        finding = _classify_cookie(name, value, f"{loc_prefix}[{name}]", liveness)
        if finding:
            findings.append(finding)
            known_values[value] = finding.placeholder_token
            c["value"] = finding.placeholder_token


def _har_cookie_liveness(cookie_obj: dict, now: datetime) -> Liveness:
    # HAR's Cookie object may carry an optional ISO-8601 "expires" field.
    expires = cookie_obj.get("expires")
    if not expires:
        return Liveness.UNKNOWN
    try:
        exp_dt = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return Liveness.UNKNOWN
    return Liveness.LIVE if now < exp_dt else Liveness.EXPIRED


def _classify_cookie(name: str, value: str, location: str, liveness: Liveness) -> CustodyFinding | None:
    if cookies_mod.is_known_session_cookie(name):
        detector = "cookies.known_name"
    elif cookies_mod.looks_like_session_cookie(name, value):
        detector = "cookies.entropy_fallback"
    else:
        return None
    placeholder = placeholder_for(value, FindingClass.IDP_SESSION_COOKIE)
    return CustodyFinding(FindingClass.IDP_SESSION_COOKIE, location, placeholder, liveness, Action.REPLACED, detector, "1")


def _scan_header_array(headers: list, loc_prefix: str, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str]) -> None:
    for h in headers:
        if not isinstance(h, dict):
            continue
        name = h.get("name", "")
        value = h.get("value", "")
        if not name or not value:
            continue
        lname = name.lower()
        if lname == "authorization":
            new_value, pairs = _classify_authorization_header(value, f"{loc_prefix}[Authorization]", now)
        elif lname == "cookie":
            new_value, pairs = _classify_cookie_header(value, f"{loc_prefix}[Cookie]")
        elif lname == "set-cookie":
            new_value, pairs = _classify_set_cookie_header(value, f"{loc_prefix}[Set-Cookie]")
        else:
            continue
        if pairs:
            for finding, raw_value in pairs:
                findings.append(finding)
                known_values[raw_value] = finding.placeholder_token
            h["value"] = new_value


def _classify_authorization_header(value: str, location: str, now: datetime) -> tuple[str, list[tuple[CustodyFinding, str]]]:
    prefix = "Bearer "
    token = value[len(prefix):] if value.startswith(prefix) else value
    if not token:
        return value, []
    if tokens_mod.looks_like_jwt(token):
        liveness = tokens_mod.jwt_liveness(token, now)
        placeholder = placeholder_for(token, FindingClass.BEARER_TOKEN)
        finding = CustodyFinding(FindingClass.BEARER_TOKEN, location, placeholder, liveness, Action.REPLACED, "tokens.jwt_structural", "1")
    else:
        placeholder = placeholder_for(token, FindingClass.API_KEY)
        finding = CustodyFinding(FindingClass.API_KEY, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "tokens.opaque_bearer", "1")
    new_value = value.replace(token, finding.placeholder_token)
    return new_value, [(finding, token)]


def _classify_cookie_header(value: str, location: str) -> tuple[str, list[tuple[CustodyFinding, str]]]:
    """Returns (new_header_value, [(finding, raw_value), ...]) -- raw_value kept
    alongside each finding here (not on the finding itself) so the caller can populate
    known_values without CustodyFinding ever needing a raw-value field."""
    pairs: list[tuple[CustodyFinding, str]] = []
    new_parts = []
    for part in value.split(";"):
        if "=" not in part:
            new_parts.append(part)
            continue
        name, _, val = part.strip().partition("=")
        f = _classify_cookie(name, val, f"{location}[{name}]", Liveness.UNKNOWN)
        if f:
            pairs.append((f, val))
            new_parts.append(f"{name}={f.placeholder_token}")
        else:
            new_parts.append(part.strip())
    return "; ".join(new_parts), pairs


def _classify_set_cookie_header(value: str, location: str) -> tuple[str, list[tuple[CustodyFinding, str]]]:
    first_segment, _, rest = value.partition(";")
    name, _, val = first_segment.partition("=")
    name = name.strip()
    val = val.strip()
    if not name or not val:
        # A cookie being cleared (e.g. the real fixture's "KC_RESTART=;...;Max-Age=0")
        # has no value to redact -- correctly not flagged, not a bug.
        return value, []
    liveness = Liveness.EXPIRED if cookies_mod.set_cookie_is_being_cleared(rest) else Liveness.UNKNOWN
    f = _classify_cookie(name, val, f"{location}[{name}]", liveness)
    if f is None:
        return value, []
    new_value = value.replace(val, f.placeholder_token, 1)
    return new_value, [(f, val)]


def _scan_url_query(request: dict, location: str, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str]) -> None:
    url = request.get("url", "")
    if "?" not in url:
        return
    base, _, query = url.partition("?")
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs:
        return
    new_pairs = []
    changed = False
    for k, v in pairs:
        # SAMLRequest/SAMLResponse are deliberately never touched here -- they are the
        # analysis target, not an incidental secret (see module docstring on scope).
        if v and credentials_mod.is_flow_artifact_param(k):
            placeholder = placeholder_for(v, FindingClass.API_KEY)
            findings.append(
                CustodyFinding(FindingClass.API_KEY, f"{location}[{k}]", placeholder, Liveness.UNKNOWN, Action.REPLACED, "credentials.flow_artifact_param", "1")
            )
            known_values[v] = placeholder
            new_pairs.append((k, placeholder))
            changed = True
        else:
            new_pairs.append((k, v))
    if changed:
        request["url"] = base + "?" + urlencode(new_pairs)


def _scan_query_string_array(query_string: list, location: str, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str]) -> None:
    """HAR carries request.queryString[] as a structured array parallel to (and
    independently redundant with) the URL's own query string. Real Keycloak captures
    populate both; both must be redacted or the structured array leaks the raw value
    even after the URL string is clean."""
    for qs in query_string:
        if not isinstance(qs, dict):
            continue
        k = qs.get("name", "")
        v = qs.get("value", "")
        if v and credentials_mod.is_flow_artifact_param(k):
            placeholder = placeholder_for(v, FindingClass.API_KEY)
            findings.append(
                CustodyFinding(FindingClass.API_KEY, f"{location}[{k}]", placeholder, Liveness.UNKNOWN, Action.REPLACED, "credentials.flow_artifact_param", "1")
            )
            known_values[v] = placeholder
            qs["value"] = placeholder


def _scan_post_params_array(params: list, location: str, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str]) -> None:
    """HAR carries postData.params[] as a structured array parallel to (and
    independently redundant with) postData.text for form-urlencoded bodies. Both must
    be redacted for the same reason as queryString[] above."""
    for p in params:
        if not isinstance(p, dict):
            continue
        k = p.get("name", "")
        v = p.get("value", "")
        if not v:
            continue
        replacement = _classify_named_field(k, v, f"{location}[{k}]", findings, now, known_values)
        if replacement is not None:
            p["value"] = replacement


# --------------------------------------------------------------------------- #
# Body scanning (form-urlencoded / JSON / free text), shared by HAR bodies and
# desk/custody's standalone scan_text() path.
# --------------------------------------------------------------------------- #


def _scan_body_text(text: str, mime: str, location: str, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str]) -> str | None:
    if "json" in mime:
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return _scan_free_text(text, location, findings, now, known_values)
        changed = _scan_json_value(obj, location, findings, now, known_values)
        return json.dumps(obj) if changed else None

    if "form-urlencoded" in mime or (not mime and "=" in text and "&" in text):
        pairs = parse_qsl(text, keep_blank_values=True)
        if not pairs:
            return _scan_free_text(text, location, findings, now, known_values)
        new_pairs = []
        changed = False
        for k, v in pairs:
            replacement = _classify_named_field(k, v, f"{location}[{k}]", findings, now, known_values)
            if replacement is not None:
                new_pairs.append((k, replacement))
                changed = True
            else:
                new_pairs.append((k, v))
        return urlencode(new_pairs) if changed else None

    return _scan_free_text(text, location, findings, now, known_values)


def _scan_json_value(obj, base_location: str, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str], path: str = "") -> bool:
    changed = False
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            loc = f"{base_location}{path}.{k}"
            if isinstance(v, str):
                replacement = _classify_named_field(k, v, loc, findings, now, known_values)
                if replacement is not None:
                    obj[k] = replacement
                    changed = True
            elif isinstance(v, (dict, list)):
                if _scan_json_value(v, base_location, findings, now, known_values, path=f"{path}.{k}"):
                    changed = True
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            loc = f"{base_location}{path}[{i}]"
            if isinstance(v, str):
                replacement = _classify_generic_string(v, loc, findings, now, known_values)
                if replacement is not None:
                    obj[i] = replacement
                    changed = True
            elif isinstance(v, (dict, list)):
                if _scan_json_value(v, base_location, findings, now, known_values, path=f"{path}[{i}]"):
                    changed = True
    return changed


def _classify_named_field(key: str, value: str, location: str, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str]) -> str | None:
    """Classification that gets to use the field/param NAME as a signal (form fields,
    JSON object keys) -- stronger evidence than pattern-matching alone."""
    if not value:
        return None
    lkey = key.lower()
    if credentials_mod.is_password_field(key):
        placeholder = placeholder_for(value, FindingClass.PLAINTEXT_CREDENTIAL)
        findings.append(CustodyFinding(FindingClass.PLAINTEXT_CREDENTIAL, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "credentials.password_field", "1"))
        known_values[value] = placeholder
        return placeholder
    if lkey == "refresh_token":
        placeholder = placeholder_for(value, FindingClass.OAUTH_REFRESH_TOKEN)
        findings.append(CustodyFinding(FindingClass.OAUTH_REFRESH_TOKEN, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "tokens.refresh_token_field", "1"))
        known_values[value] = placeholder
        return placeholder
    if lkey in {"access_token", "id_token"} and tokens_mod.looks_like_jwt(value):
        liveness = tokens_mod.jwt_liveness(value, now)
        placeholder = placeholder_for(value, FindingClass.BEARER_TOKEN)
        findings.append(CustodyFinding(FindingClass.BEARER_TOKEN, location, placeholder, liveness, Action.REPLACED, "tokens.jwt_structural", "1"))
        known_values[value] = placeholder
        return placeholder
    if keys_mod.is_api_key_field(key):
        placeholder = placeholder_for(value, FindingClass.API_KEY)
        findings.append(CustodyFinding(FindingClass.API_KEY, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "keys.named_field", "1"))
        known_values[value] = placeholder
        return placeholder
    if credentials_mod.is_flow_artifact_param(key):
        placeholder = placeholder_for(value, FindingClass.API_KEY)
        findings.append(CustodyFinding(FindingClass.API_KEY, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "credentials.flow_artifact_param", "1"))
        known_values[value] = placeholder
        return placeholder
    # Fall through to pattern-only classification (email, JWT-shaped, PEM, AWS key) so
    # a field with an unrecognized name but a recognizable value is still caught.
    return _classify_generic_string(value, location, findings, now, known_values)


def _classify_generic_string(value: str, location: str, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str]) -> str | None:
    """Pattern-only classification, for values with no field-name context (list items,
    free text)."""
    if pii_mod.EMAIL_RE.fullmatch(value):
        placeholder = placeholder_for(value, FindingClass.EMAIL_PII)
        findings.append(CustodyFinding(FindingClass.EMAIL_PII, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "pii.email_regex", "1"))
        known_values[value] = placeholder
        return placeholder
    if keys_mod.PEM_KEY_RE.search(value.encode("utf-8", errors="surrogateescape")):
        placeholder = placeholder_for(value, FindingClass.PRIVATE_KEY)
        findings.append(CustodyFinding(FindingClass.PRIVATE_KEY, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "keys.pem_pattern", "1"))
        known_values[value] = placeholder
        return placeholder
    if keys_mod.AWS_ACCESS_KEY_RE.fullmatch(value):
        placeholder = placeholder_for(value, FindingClass.API_KEY)
        findings.append(CustodyFinding(FindingClass.API_KEY, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "keys.aws_access_key_pattern", "1"))
        known_values[value] = placeholder
        return placeholder
    if tokens_mod.looks_like_jwt(value):
        liveness = tokens_mod.jwt_liveness(value, now)
        placeholder = placeholder_for(value, FindingClass.BEARER_TOKEN)
        findings.append(CustodyFinding(FindingClass.BEARER_TOKEN, location, placeholder, liveness, Action.REPLACED, "tokens.jwt_structural", "1"))
        known_values[value] = placeholder
        return placeholder
    return None


def _scan_free_text(text: str, location: str, findings: list[CustodyFinding], now: datetime, known_values: dict[str, str]) -> str | None:
    """Scans unlabeled prose/bodies for embedded secret patterns (PEM blocks, JWT-shaped
    substrings, AWS keys, emails). Substitution is by exact value across the whole
    string deliberately -- it means every occurrence of the same secret gets the same
    stable placeholder, which is the intended behavior, and a coincidental collision
    with an unrelated but byte-identical string is cryptographically negligible for
    values with this much entropy."""
    new_text = text
    changed = False

    for m in keys_mod.PEM_KEY_RE.finditer(new_text.encode("utf-8", errors="surrogateescape")):
        raw = m.group(0).decode("utf-8", errors="surrogateescape")
        placeholder = placeholder_for(raw, FindingClass.PRIVATE_KEY)
        findings.append(CustodyFinding(FindingClass.PRIVATE_KEY, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "keys.pem_pattern", "1"))
        known_values[raw] = placeholder
        new_text = new_text.replace(raw, placeholder)
        changed = True

    for m in tokens_mod.JWT_CANDIDATE_RE.finditer(new_text):
        cand = m.group(0)
        if not tokens_mod.looks_like_jwt(cand):
            continue
        liveness = tokens_mod.jwt_liveness(cand, now)
        placeholder = placeholder_for(cand, FindingClass.BEARER_TOKEN)
        findings.append(CustodyFinding(FindingClass.BEARER_TOKEN, location, placeholder, liveness, Action.REPLACED, "tokens.jwt_structural", "1"))
        known_values[cand] = placeholder
        new_text = new_text.replace(cand, placeholder)
        changed = True

    for m in keys_mod.AWS_ACCESS_KEY_RE.finditer(new_text):
        cand = m.group(0)
        placeholder = placeholder_for(cand, FindingClass.API_KEY)
        findings.append(CustodyFinding(FindingClass.API_KEY, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "keys.aws_access_key_pattern", "1"))
        known_values[cand] = placeholder
        new_text = new_text.replace(cand, placeholder)
        changed = True

    for m in pii_mod.EMAIL_RE.finditer(new_text):
        cand = m.group(0)
        placeholder = placeholder_for(cand, FindingClass.EMAIL_PII)
        findings.append(CustodyFinding(FindingClass.EMAIL_PII, location, placeholder, Liveness.UNKNOWN, Action.REPLACED, "pii.email_regex", "1"))
        known_values[cand] = placeholder
        new_text = new_text.replace(cand, placeholder)
        changed = True

    return new_text if changed else None


# --------------------------------------------------------------------------- #
# XML scanning (SAMLResponse / IdP / SP metadata)
# --------------------------------------------------------------------------- #


def _scan_xml(raw_bytes: bytes, now: datetime) -> CustodyResult:
    # Same hardened defused-then-lxml pattern as desk/verify/parsed.py, reused
    # verbatim rather than reinvented. Unlike parsed.py, this does not require a
    # samlp:Response root -- idp_metadata/sp_metadata are a different root element and
    # custody needs to scan all three kinds.
    try:
        DET.fromstring(raw_bytes)  # defused pre-check; result discarded
    except Exception as exc:
        raise CustodyFailure(f"XML failed defused pre-parse: {exc}") from exc
    try:
        parser = LET.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        root = LET.fromstring(raw_bytes, parser=parser)
    except Exception as exc:
        raise CustodyFailure(f"XML failed lxml parse: {exc}") from exc

    findings: list[CustodyFinding] = []

    # NameID is recorded but never redacted out of the returned bytes -- see this
    # module's docstring and findings.py's Action.RECORDED_ONLY for why. It is
    # verifier-required evidence, not a leak vector while it stays inside this process.
    for nameid_el in root.iter(NAMEID_TAG):
        value = (nameid_el.text or "").strip()
        if not value:
            continue
        placeholder = placeholder_for(value, FindingClass.NAMEID_PII)
        findings.append(
            CustodyFinding(FindingClass.NAMEID_PII, "xml//saml:NameID", placeholder, Liveness.UNKNOWN, Action.RECORDED_ONLY, "pii.nameid", "1")
        )

    # Group/role membership carried as saml:Attribute values with a known name
    # (Phase 0's documented Keycloak <Attribute Name="Role"> quirk). Same
    # record-only treatment: this is the assertion's actual authorization content, and
    # the verifier's SAML-ATTR-01 check reads it, so it is never stripped from the
    # returned bytes -- only logged for the data-minimization audit trail.
    for attr_el in root.iter(GROUP_ATTRIBUTE_TAG):
        name = attr_el.get("Name", "")
        if name not in pii_mod.KNOWN_GROUP_ATTRIBUTE_NAMES:
            continue
        for val_el in attr_el:
            value = (val_el.text or "").strip()
            if not value:
                continue
            placeholder = placeholder_for(value, FindingClass.GROUP_MEMBERSHIP)
            findings.append(
                CustodyFinding(
                    FindingClass.GROUP_MEMBERSHIP,
                    f"xml//saml:Attribute[@Name='{name}']",
                    placeholder,
                    Liveness.UNKNOWN,
                    Action.RECORDED_ONLY,
                    "pii.group_attribute",
                    "1",
                )
            )

    # A private key embedded in signed XML would be a genuinely serious, unexpected
    # finding -- Keycloak's real output never does this, but it is checked for
    # structurally rather than assumed impossible. Unlike NameID/group above, this
    # really is a stray secret with no verifier dependency, so it IS redacted.
    xml_text = raw_bytes.decode("utf-8", errors="surrogateescape")
    for m in keys_mod.PEM_KEY_RE.finditer(raw_bytes):
        raw = m.group(0).decode("utf-8", errors="surrogateescape")
        placeholder = placeholder_for(raw, FindingClass.PRIVATE_KEY)
        findings.append(CustodyFinding(FindingClass.PRIVATE_KEY, "xml (PEM pattern)", placeholder, Liveness.UNKNOWN, Action.REPLACED, "keys.pem_pattern", "1"))
        xml_text = xml_text.replace(raw, placeholder)

    return CustodyResult(defanged_bytes=xml_text.encode("utf-8", errors="surrogateescape"), findings=findings)


# --------------------------------------------------------------------------- #
# Free-text artifacts (customer narrative, OCR'd screenshot text)
# --------------------------------------------------------------------------- #


def _scan_text(raw_bytes: bytes, now: datetime) -> CustodyResult:
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CustodyFailure(f"text artifact is not valid UTF-8: {exc}") from exc
    findings: list[CustodyFinding] = []
    known_values: dict[str, str] = {}
    new_text = _scan_free_text(text, "text", findings, now, known_values)
    defanged_bytes = (new_text if new_text is not None else text).encode("utf-8")
    return CustodyResult(defanged_bytes=defanged_bytes, findings=findings)
