"""JSON Schema definitions for the three reasoning jobs, plus a small hand-rolled
validator to check a parsed response against one.

Deliberately standard JSON Schema (lowercase types, `type`/`properties`/`required`/
`enum`/`items`), not Gemini's uppercase OpenAPI-flavored `Schema` object, because one
schema dict has to serve three consumers: Gemini's `response_json_schema` field (a
documented alternative to `response_schema` that accepts real JSON Schema -- confirmed
by inspecting the installed google-genai 2.18.1 SDK's GenerateContentConfig fields),
Ollama's `format` field (which has always accepted standard JSON Schema), and this
module's own `validate_against_schema`, used a second time as an independent
post-hoc check regardless of which provider produced the output. No `jsonschema`
dependency: the subset of JSON Schema these three jobs actually need (type, enum,
required, properties, items, additionalProperties) is small enough that hand-rolling
it keeps the dependency list honest about what this project actually uses.

Field names deliberately match desk/verify/gaps.py's REQUESTED_ARTIFACTS enum (Job B)
and harness/narratives/facts.py's NarrativeFacts TypedDict (Job A) exactly, not the
plan's illustrative sketch -- plan section 16 imagined a `claimed_idp` field for Job A,
but no such field exists in the actual frozen ground truth
(FAULT_NARRATIVE_FACTS/NarrativeFacts), and grading a field with no ground truth to
grade against would be theater. Job A's schema below extracts exactly the six
NarrativeFacts fields and nothing else.
"""

from __future__ import annotations

from typing import Any

from desk.verify.assurance import Assurance
from desk.verify.gaps import REQUESTED_ARTIFACTS

SCHEMA_VERSION = "v1"

_ASSURANCE_VALUES = sorted(a.value for a in Assurance)

# --------------------------------------------------------------------------------- #
# Job A -- intake comprehension: free customer prose -> the six NarrativeFacts fields,
# each paired with a confidence score. "unknown" is a first-class enum value for scope
# and reporter_role, not a null -- a customer report either names a scope or it doesn't,
# and "the model looked and found nothing" is a different, worth-recording state from
# "this field wasn't asked about."
# --------------------------------------------------------------------------------- #

JOB_A_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scope": {
            "type": "string",
            "enum": ["all_users", "subset", "single_user", "new_users_only", "unknown"],
        },
        "scope_confidence": {"type": "number"},
        "onset": {"type": ["string", "null"]},
        "onset_confidence": {"type": "number"},
        "recent_change": {"type": ["string", "null"]},
        "recent_change_confidence": {"type": "number"},
        "already_tried": {"type": "array", "items": {"type": "string"}},
        "reporter_role": {"type": ["string", "null"]},
        "reporter_role_confidence": {"type": "number"},
        "wrong_belief": {"type": ["string", "null"]},
        "wrong_belief_confidence": {"type": "number"},
    },
    "required": [
        "scope",
        "scope_confidence",
        "onset",
        "onset_confidence",
        "recent_change",
        "recent_change_confidence",
        "already_tried",
        "reporter_role",
        "reporter_role_confidence",
        "wrong_belief",
        "wrong_belief_confidence",
    ],
    "additionalProperties": False,
}

# --------------------------------------------------------------------------------- #
# Job B -- missing-evidence request. requested_artifacts is constrained to the exact
# same closed enum desk/verify/gaps.py computes gaps against, so the model structurally
# cannot ask for something the system doesn't have a defined artifact kind for.
# --------------------------------------------------------------------------------- #

JOB_B_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "requested_artifacts": {
            "type": "array",
            "items": {"type": "string", "enum": sorted(REQUESTED_ARTIFACTS)},
            "minItems": 1,
        },
    },
    "required": ["subject", "body", "requested_artifacts"],
    "additionalProperties": False,
}

# --------------------------------------------------------------------------------- #
# Job C -- explanation synthesis. claims[] is mandatory and non-empty: an explanation
# with zero claims would be prose with nothing for desk/ground to check, which is
# itself a grounding failure (see desk/ground/validator.py's empty_claims violation).
# asserted_state is drawn from the same six-state taxonomy the verifier itself uses,
# rather than a hand-typed duplicate list that could silently drift from it.
# --------------------------------------------------------------------------------- #

JOB_C_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "root_cause": {"type": ["string", "null"]},
        "fix_steps": {"type": "array", "items": {"type": "string"}},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "check_id": {"type": "string"},
                    "asserted_state": {"type": "string", "enum": _ASSURANCE_VALUES},
                },
                "required": ["text", "check_id", "asserted_state"],
                "additionalProperties": False,
            },
            "minItems": 1,
        },
    },
    "required": ["summary", "root_cause", "fix_steps", "claims"],
    "additionalProperties": False,
}


def validate_against_schema(data: Any, schema: dict[str, Any]) -> list[str]:
    """Returns a list of violation strings; empty means valid. Deliberately returns
    every violation found rather than stopping at the first, so a caller can see the
    whole shape of a bad response at once (matches this repo's existing pattern in
    tests/harness/test_corpus.py of collecting all mismatches before asserting)."""
    violations: list[str] = []
    _check(data, schema, path="$", violations=violations)
    return violations


def _type_matches(value: Any, type_spec: Any) -> bool:
    types = type_spec if isinstance(type_spec, list) else [type_spec]
    for t in types:
        if t == "null" and value is None:
            return True
        if t == "string" and isinstance(value, str):
            return True
        if t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if t == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if t == "boolean" and isinstance(value, bool):
            return True
        if t == "array" and isinstance(value, list):
            return True
        if t == "object" and isinstance(value, dict):
            return True
    return False


def _check(value: Any, schema: dict[str, Any], *, path: str, violations: list[str]) -> None:
    type_spec = schema.get("type")
    if type_spec is not None and not _type_matches(value, type_spec):
        violations.append(f"{path}: expected type {type_spec!r}, got {type(value).__name__} ({value!r})")
        return  # further structural checks would be meaningless against the wrong type

    enum = schema.get("enum")
    if enum is not None and value not in enum:
        violations.append(f"{path}: value {value!r} not in enum {enum!r}")

    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                violations.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties") or {}
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    violations.append(f"{path}: unexpected property {key!r} (additionalProperties: false)")
        for key, sub_schema in properties.items():
            if key in value:
                _check(value[key], sub_schema, path=f"{path}.{key}", violations=violations)

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            violations.append(f"{path}: expected at least {min_items} item(s), got {len(value)}")
        items_schema = schema.get("items")
        if items_schema is not None:
            for i, item in enumerate(value):
                _check(item, items_schema, path=f"{path}[{i}]", violations=violations)
