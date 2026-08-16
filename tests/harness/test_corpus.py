"""Phase 3 corpus tests: manifest verification (every artifact's sha256 on disk matches
corpus/MANIFEST.json) and label sanity (every fault's target_check_ids is drawn from the
real canonical check_id set, derived by actually running run_all_checks against the good
baseline rather than hand-transcribed -- so a check_id typo in a FaultSpec fails loudly
instead of silently never matching anything).

Deliberately does NOT re-run harness/generate.py's own self-test (verify_and_selftest
already ran, and failed loudly, at generation time -- see harness/generate.py's
docstring). These tests check what shipped, not what was predicted.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from desk.verify.checks import ALL_CHECKS
from desk.verify.verifier import run_all_checks
from harness.faults import ALL_FAULTS, baseline
from harness.faults.ambiguous import AMBIGUOUS_CASES
from harness.faults.conflicting import CONFLICTING_CASES

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
CORPUS_DIR = os.path.join(REPO_ROOT, "corpus")
MANIFEST_PATH = os.path.join(CORPUS_DIR, "MANIFEST.json")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not os.path.exists(MANIFEST_PATH):
        pytest.skip("corpus/MANIFEST.json not generated -- run `python3 -m harness.generate` first")
    with open(MANIFEST_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def canonical_check_ids() -> set[str]:
    """The real check_id set, derived by actually running the verifier against the good
    baseline -- not hand-transcribed from desk/verify/checks/ source, so a rename in the
    verifier is caught here too."""
    run = run_all_checks(baseline.load_good_saml_response(), baseline.good_context())
    assert run.parse_error is None, "the good baseline itself failed to parse -- fix baseline before trusting this set"
    ids = {r.check_id for r in run.results}
    assert len(ids) == len(ALL_CHECKS), (
        f"expected {len(ALL_CHECKS)} distinct check_ids from ALL_CHECKS, got {len(ids)} -- "
        "a check_id collision would silently merge two checks' results"
    )
    return ids


def test_manifest_totals_are_internally_consistent(manifest):
    totals = manifest["totals"]
    assert totals["total_cases"] == len(manifest["cases"])
    assert totals["total_cases"] == (
        totals["base_cases"] + totals["register_variants"] + totals["adversarial_cases"] + totals["documented_gaps"]
    )


def test_every_manifest_artifact_sha256_matches_disk(manifest):
    mismatches = []
    for case_id, entry in manifest["cases"].items():
        case_dir = os.path.join(CORPUS_DIR, "cases", case_id)
        for filename, expected_sha in entry["artifacts"].items():
            path = os.path.join(case_dir, filename)
            if not os.path.exists(path):
                mismatches.append(f"{case_id}/{filename}: file missing on disk")
                continue
            with open(path, "rb") as f:
                actual_sha = _sha256_bytes(f.read())
            if actual_sha != expected_sha:
                mismatches.append(f"{case_id}/{filename}: manifest={expected_sha} disk={actual_sha}")
    assert not mismatches, "\n".join(mismatches)


def test_shared_baseline_har_sha256_matches_disk(manifest):
    shared = manifest["shared_artifacts"]["shared_baseline_har"]
    path = os.path.join(REPO_ROOT, shared["path"])
    with open(path, "rb") as f:
        actual = _sha256_bytes(json.dumps(json.load(open(path)), indent=2).encode("utf-8"))
    assert actual == shared["sha256"]


def test_no_case_silently_missing_from_manifest(manifest):
    executable = [f.fault_id for f in ALL_FAULTS if f.category.value != "documented_gap"]
    expected_base_ids = set(executable) | {f.fault_id for f in AMBIGUOUS_CASES} | {f.fault_id for f in CONFLICTING_CASES}
    gap_ids = {f.fault_id for f in ALL_FAULTS if f.category.value == "documented_gap"}

    manifest_case_ids = set(manifest["cases"])
    missing_base = expected_base_ids - manifest_case_ids
    missing_gap = gap_ids - manifest_case_ids
    assert not missing_base, f"base fault(s) with no manifest entry at all: {missing_base}"
    assert not missing_gap, f"documented-gap fault(s) with no manifest entry at all: {missing_gap}"


def test_every_target_check_id_is_a_real_check(manifest, canonical_check_ids):
    """Label sanity: every fault ID maps to a detectable check -- meaning every check_id a
    FaultSpec claims it targets actually exists in the verifier's real output, not a
    typo'd string that would silently never match anything in by_id()."""
    bad = []
    for case_id, entry in manifest["cases"].items():
        for check_id in entry.get("target_check_ids") or []:
            if check_id not in canonical_check_ids:
                bad.append(f"{case_id}: target_check_id {check_id!r} is not a real check_id")
    assert not bad, "\n".join(bad)


def test_every_executable_case_names_at_least_one_outcome(manifest):
    """Every case that isn't a documented gap must name what it expects: at least one
    target_check_id, or expects_parse_failure, or no_check_coverage_reason. This mirrors
    FaultSpec.__post_init__'s own invariant, checked here against what actually shipped
    to disk rather than trusting the in-memory object survived unmodified to the manifest."""
    bad = []
    for case_id, entry in manifest["cases"].items():
        if entry["category"] == "documented_gap":
            continue
        has_targets = bool(entry.get("target_check_ids"))
        has_parse_failure = bool(entry.get("expects_parse_failure"))
        has_no_coverage = bool(entry.get("no_check_coverage_reason"))
        if not (has_targets or has_parse_failure or has_no_coverage):
            bad.append(case_id)
    assert not bad, f"case(s) with no named outcome at all: {bad}"


def test_documented_gaps_have_no_fabricated_artifacts(manifest):
    for case_id, entry in manifest["cases"].items():
        if entry["category"] != "documented_gap":
            continue
        assert set(entry["artifacts"]) == {"label.json"}, (
            f"{case_id}: a documented gap must carry only label.json, found {set(entry['artifacts'])}"
        )


def test_har_ref_is_consistent_with_case_local_artifact(manifest):
    for case_id, entry in manifest["cases"].items():
        har_present_on_disk = "login.har" in entry["artifacts"]
        if entry["har_ref"] == "case_local":
            assert har_present_on_disk, f"{case_id}: har_ref=case_local but no login.har artifact recorded"
        elif entry["har_ref"] == "shared_baseline_har":
            assert not har_present_on_disk, f"{case_id}: har_ref=shared_baseline_har but a case-local login.har exists too"
        else:
            assert entry["har_ref"] is None, f"{case_id}: unexpected har_ref value {entry['har_ref']!r}"


def test_injection_cases_are_labeled_and_traceable_to_a_real_payload(manifest):
    from harness.adversarial import ALL_PAYLOADS

    payload_ids = {p.payload_id for p in ALL_PAYLOADS}
    adversarial_cases = [e for e in manifest["cases"].values() if e.get("injection") is not None]
    assert len(adversarial_cases) == manifest["totals"]["adversarial_cases"]
    for entry in adversarial_cases:
        assert entry["injection"]["payload_id"] in payload_ids
