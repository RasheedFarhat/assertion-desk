"""Structural sanity checks on harness/adversarial.py's ALL_PAYLOADS and its pairing
with harness/generate.py's ADVERSARIAL_PLAN. These are the guards the 2026-08-23 fix
added after two real bugs were found above n=4: a payload_id collision that silently
overwrote a case in manifest_cases, and a missing ADVERSARIAL_PLAN entry that raised a
bare KeyError instead of a captured SelfTestFailure. ALL_PAYLOADS already fails fast at
import time on a duplicate id (mirroring harness/faults/__init__.py's ALL_FAULTS guard);
this file makes that guarantee, and the other structural invariants generate.py depends
on, explicit and independently testable rather than only observable as an ImportError.
"""

from __future__ import annotations

from harness.generate import ADVERSARIAL_PLAN
from harness.faults import ALL_FAULTS
from harness.adversarial import ALL_PAYLOADS


def test_no_duplicate_payload_ids():
    ids = [p.payload_id for p in ALL_PAYLOADS]
    assert len(ids) == len(set(ids)), f"duplicate payload_id(s): {[i for i in ids if ids.count(i) > 1]}"


def test_every_payload_is_registered_in_adversarial_plan():
    missing = [p.payload_id for p in ALL_PAYLOADS if p.payload_id not in ADVERSARIAL_PLAN]
    assert missing == [], f"payload(s) with no ADVERSARIAL_PLAN base-fault entry: {missing}"


def test_adversarial_plan_has_no_orphan_entries():
    """The reverse direction: every ADVERSARIAL_PLAN key should name a real payload,
    otherwise a renamed or removed payload_id leaves a dead entry silently."""
    payload_ids = {p.payload_id for p in ALL_PAYLOADS}
    orphans = [pid for pid in ADVERSARIAL_PLAN if pid not in payload_ids]
    assert orphans == [], f"ADVERSARIAL_PLAN entries with no matching payload: {orphans}"


def test_every_adversarial_plan_base_fault_exists():
    fault_ids = {f.fault_id for f in ALL_FAULTS}
    missing = [(pid, base) for pid, base in ADVERSARIAL_PLAN.items() if base not in fault_ids]
    assert missing == [], f"ADVERSARIAL_PLAN base fault(s) not found in ALL_FAULTS: {missing}"


def test_exactly_one_apply_fn_set_per_payload():
    apply_fields = {
        "saml_response": "xml_apply",
        "har": "har_apply",
        "narrative": "narrative_apply",
    }
    for payload in ALL_PAYLOADS:
        expected_field = apply_fields[payload.artifact_kind]
        for field_name in apply_fields.values():
            value = getattr(payload, field_name)
            if field_name == expected_field:
                assert value is not None, f"{payload.payload_id}: expected {field_name} to be set"
            else:
                assert value is None, (
                    f"{payload.payload_id}: {field_name} should be None for artifact_kind="
                    f"{payload.artifact_kind!r}, got {value!r}"
                )


def test_reachability_fields_are_declared_for_every_payload():
    """reaches_prompt/landing_site/evades_detector are the fields eval/metrics.py now
    reads instead of the old case-id-suffix hack -- assert they are always a real bool
    and a non-empty string, not left at a dataclass default that would silently read as
    falsy everywhere."""
    # Not asserted: evades_detector implies reaches_prompt. s4_base64_attribute_
    # friendlyname is deliberately both obfuscated AND structurally unreachable (its
    # own landing_site explains why: the obfuscation attempt was real, it just turned
    # out to land somewhere no job reads either) -- the two flags are independent
    # claims, not a hierarchy.
    for payload in ALL_PAYLOADS:
        assert isinstance(payload.reaches_prompt, bool), payload.payload_id
        assert isinstance(payload.evades_detector, bool), payload.payload_id
        assert payload.landing_site, payload.payload_id
