"""The Phase 3 corpus orchestrator. Turns every FaultSpec in the catalogue (plus the
ambiguous/conflicting cases kept outside ALL_FAULTS, plus a curated set of narrative-
register variants and adversarial-injection overlays) into a real, on-disk corpus case:
real artifacts, a real verifier run, a self-test against the fault's own hand-authored
prediction, a rendered customer narrative, and a manifest entry with a sha256 per file.

Design principles this module holds itself to, matching the rest of the project:

  Self-test before freeze. Every case's real VerificationRun is checked against its
  FaultSpec's expected_states/expects_parse_failure before the case is written to disk.
  A mismatch is a hard error, not a warning -- this is the same discipline that caught
  cert_rotation's undocumented SAML-SIG-01/02 cascade during hand-testing (see
  harness/faults/cert_rotation.py's docstring). Automating it here means every future
  fault or corpus edit gets the same check for free, not just the ones someone remembers
  to hand-verify.

  Shared artifacts are not duplicated for no reason. Most cases reuse the baseline HAR
  (harness/capture/captured/login.har, ~4MB) byte-for-byte. Copying it into 50 case
  directories would triple the repo's size for zero information gain, so a case only gets
  its own login.har on disk when its fault mechanism actually produced different HAR
  bytes (a har_transform, or a LIVE_CAPTURE fault with its own real capture). Every other
  case's label.json points at "shared_baseline_har" instead, and the shared file gets
  exactly one manifest entry with its own sha256.

  No case is silently dropped. DOCUMENTED_GAP faults (currently one:
  sha1_signature_downgrade) get a manifest entry naming the gap, not an artifact-bearing
  case directory pretending one exists.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone

from desk.verify.context import VerificationContext
from desk.verify.verifier import VerificationRun, run_all_checks
from harness.adversarial import ALL_PAYLOADS, InjectionPayload
from harness.faults import ALL_FAULTS, baseline
from harness.faults.ambiguous import AMBIGUOUS_CASES
from harness.faults.base import FaultCategory, FaultSpec
from harness.faults.conflicting import CONFLICTING_CASES
from harness.narratives import FAULT_NARRATIVE_FACTS, RENDER_FUNCTIONS

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "..", "corpus")
CASES_DIR = os.path.join(CORPUS_DIR, "cases")
MANIFEST_PATH = os.path.join(CORPUS_DIR, "MANIFEST.json")

# Which base faults get the four extra narrative registers (vague, confident_misdiagnosis,
# hostile, non_native), beyond the "precise" register every base case already gets. Chosen
# to cover a spread of categories and check families rather than duplicating six similar
# CONTEXT_MISMATCH cases: one LIVE_CAPTURE (cert_rotation), one clean CONTEXT_MISMATCH
# with a cascading effect (cert_expired), one CONTEXT_MISMATCH with no cascade
# (wrong_issuer), two ARTIFACT_MUTATION cases from different check families
# (broken_signature, missing_nameid), and one pure-timing CONTEXT_MISMATCH (clock_skew).
HERO_FAULT_IDS = [
    "cert_rotation",
    "cert_expired",
    "wrong_issuer",
    "broken_signature",
    "missing_nameid",
    "clock_skew",
]
NON_PRECISE_REGISTERS = [r for r in RENDER_FUNCTIONS if r != "precise"]

# Which adversarial payload gets layered onto which base (precise-register) case, and why
# that base was chosen rather than any other:
#   S1 (XML comment)        -> cert_rotation   the project's own killer-demo pairing (plan
#                                               §13); a real LIVE_CAPTURE response, not a
#                                               synthetic one, makes the "the model
#                                               complied, the verifier didn't care" beat
#                                               land on genuine artifacts.
#   S2 (HAR User-Agent)      -> wrong_issuer    needs a HAR with exactly one real ACS POST
#                                               entry (mutations._find_acs_post_entry);
#                                               wrong_issuer is CONTEXT_MISMATCH with an
#                                               unmodified baseline HAR, so that entry is
#                                               real and present. negative_control's HAR
#                                               has zero ACS POST entries and would raise.
#   S3 (narrative appeal)    -> clock_skew      any fault with a narrative works; clock_skew
#                                               is a single_user, evidence-shaped case where
#                                               "compliance already confirmed this, skip the
#                                               certificate check" is a plausible-sounding
#                                               non sequitur (clock_skew isn't a certificate
#                                               finding at all), which is closer to how a
#                                               real social-engineering attempt would read.
#   S4 (obfuscated attribute) -> assertion_expired  needs a first <Attribute> element with
#                                               no pre-existing FriendlyName; assertion_expired
#                                               is CONTEXT_MISMATCH (unmodified XML), so
#                                               Attribute[0] is the real, untouched one.
ADVERSARIAL_PLAN: dict[str, str] = {
    "s1_response_xml_comment": "cert_rotation",
    "s2_har_user_agent": "wrong_issuer",
    "s3_narrative_appeal_to_authority": "clock_skew",
    "s4_base64_attribute_friendlyname": "assertion_expired",
}


class SelfTestFailure(Exception):
    """Raised when a case's real VerificationRun disagrees with its FaultSpec's own
    prediction. This must never be caught and downgraded -- a mismatch here means either
    the fault file or the verifier is wrong, and the corpus must not freeze either one
    silently."""


# ---------------------------------------------------------------------------
# Artifact resolution -- one function per the three resolution paths confirmed via
# grep to never mix mechanisms within a category (see harness/faults/base.py).
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ResolvedArtifacts:
    raw: bytes | None
    ctx: VerificationContext
    har: dict | None
    har_is_case_specific: bool
    no_saml_response_reason: str | None


def _load_har(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def resolve_artifacts(spec: FaultSpec) -> ResolvedArtifacts:
    if spec.category == FaultCategory.LIVE_CAPTURE:
        live = spec.live_loader()
        ctx = baseline.good_context()
        if live.get("trusted_cert_pem") is not None:
            ctx = dataclasses.replace(ctx, trusted_cert_pem=live["trusted_cert_pem"])
        har_path = live.get("har_path")
        har = _load_har(har_path) if har_path else None
        return ResolvedArtifacts(
            raw=live.get("raw_saml_response"),
            ctx=ctx,
            har=har,
            har_is_case_specific=har is not None,
            no_saml_response_reason=live.get("no_saml_response_reason"),
        )

    # BASELINE, CONTEXT_MISMATCH, ARTIFACT_MUTATION all start from the same real capture.
    raw = baseline.load_good_saml_response()
    har = _load_har(baseline.GOOD_HAR_PATH)
    ctx = baseline.good_context()
    har_touched = False
    if spec.ctx_transform:
        ctx = spec.ctx_transform(ctx)
    if spec.xml_transform:
        raw = spec.xml_transform(raw)
    if spec.har_transform:
        har = spec.har_transform(har)
        har_touched = True
    return ResolvedArtifacts(
        raw=raw, ctx=ctx, har=har, har_is_case_specific=har_touched, no_saml_response_reason=None
    )


def verify_and_selftest(spec: FaultSpec, raw: bytes | None, ctx: VerificationContext) -> VerificationRun | None:
    if raw is None:
        if not spec.no_check_coverage_reason:
            raise SelfTestFailure(f"{spec.fault_id}: raw is None but no_check_coverage_reason is unset")
        return None

    run = run_all_checks(raw, ctx)

    if spec.expects_parse_failure:
        if run.parse_error is None:
            raise SelfTestFailure(f"{spec.fault_id}: expected a parse failure, got a clean parse")
        return run

    if run.parse_error is not None:
        raise SelfTestFailure(f"{spec.fault_id}: unexpected parse failure: {run.parse_error}")

    for check_id, expected in spec.expected_states.items():
        result = run.by_id(check_id)
        if result is None:
            raise SelfTestFailure(f"{spec.fault_id}: {check_id} did not run at all")
        if result.assurance.value != expected:
            raise SelfTestFailure(
                f"{spec.fault_id}: {check_id} expected={expected!r} actual={result.assurance.value!r} "
                f"reason={result.reason!r}"
            )
    return run


# ---------------------------------------------------------------------------
# Narrative rendering
# ---------------------------------------------------------------------------


def render_narrative(fault_id: str, register: str) -> dict:
    facts = FAULT_NARRATIVE_FACTS.get(fault_id)
    if facts is None:
        raise SelfTestFailure(f"{fault_id}: no FAULT_NARRATIVE_FACTS entry, cannot render a narrative")
    return RENDER_FUNCTIONS[register](facts)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ctx_to_json(ctx: VerificationContext) -> dict:
    return {
        "sp_entity_id": ctx.sp_entity_id,
        "acs_url": ctx.acs_url,
        "idp_entity_id": ctx.idp_entity_id,
        "trusted_cert_pem": ctx.trusted_cert_pem,
        "in_response_to_expected": ctx.in_response_to_expected,
        "sp_clock": ctx.sp_clock.isoformat() if ctx.sp_clock else None,
        "clock_skew_tolerance_seconds": ctx.clock_skew_tolerance_seconds,
        "evaluation_time": ctx.evaluation_time.isoformat() if ctx.evaluation_time else None,
    }


def _run_to_json(run: VerificationRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "parse_error": run.parse_error,
        "results": [
            {
                "check_id": r.check_id,
                "assurance": r.assurance.value,
                "observed": r.observed,
                "expected": r.expected,
                "reason": r.reason,
                "evidence_ref": r.evidence_ref,
            }
            for r in run.results
        ],
        "counts": run.counts() if run.parse_error is None else None,
    }


# ---------------------------------------------------------------------------
# Case writing
# ---------------------------------------------------------------------------


def _fresh_case_dir(case_id: str) -> str:
    case_dir = os.path.join(CASES_DIR, case_id)
    if os.path.exists(case_dir):
        shutil.rmtree(case_dir)
    os.makedirs(case_dir, exist_ok=True)
    return case_dir


def write_case(
    case_id: str,
    spec: FaultSpec,
    resolved: ResolvedArtifacts,
    run: VerificationRun | None,
    narrative: dict | None,
    register: str,
    *,
    injection: InjectionPayload | None = None,
) -> dict:
    case_dir = _fresh_case_dir(case_id)
    artifacts: dict[str, str] = {}

    if resolved.raw is not None:
        xml_path = os.path.join(case_dir, "saml_response.xml")
        with open(xml_path, "wb") as f:
            f.write(resolved.raw)
        artifacts["saml_response.xml"] = _sha256_bytes(resolved.raw)

    har_ref = None
    if resolved.har is not None:
        if resolved.har_is_case_specific:
            har_bytes = json.dumps(resolved.har, indent=2).encode("utf-8")
            har_path = os.path.join(case_dir, "login.har")
            with open(har_path, "wb") as f:
                f.write(har_bytes)
            artifacts["login.har"] = _sha256_bytes(har_bytes)
            har_ref = "case_local"
        else:
            har_ref = "shared_baseline_har"

    with open(os.path.join(case_dir, "context.json"), "w") as f:
        json.dump(_ctx_to_json(resolved.ctx), f, indent=2)

    with open(os.path.join(case_dir, "check_results.json"), "w") as f:
        json.dump(_run_to_json(run), f, indent=2)

    if narrative is not None:
        with open(os.path.join(case_dir, "narrative.json"), "w") as f:
            json.dump(narrative, f, indent=2)

    label = {
        "case_id": case_id,
        "fault_id": spec.fault_id,
        "category": spec.category.value,
        "difficulty": spec.difficulty,
        "register": register,
        "expected_root_cause": spec.expected_root_cause,
        "expected_disposition": spec.expected_disposition,
        "target_check_ids": spec.target_check_ids,
        "expects_parse_failure": spec.expects_parse_failure,
        "no_check_coverage_reason": spec.no_check_coverage_reason,
        "no_saml_response_reason": resolved.no_saml_response_reason,
        "har_ref": har_ref,
        "injection": (
            {
                "payload_id": injection.payload_id,
                "taxonomy_class": injection.taxonomy_class,
                "artifact_kind": injection.artifact_kind,
                "source_location": injection.source_location,
                "span_excerpt": injection.span_excerpt,
            }
            if injection is not None
            else None
        ),
    }
    with open(os.path.join(case_dir, "label.json"), "w") as f:
        json.dump(label, f, indent=2)
    artifacts["label.json"] = _sha256_bytes(json.dumps(label, indent=2).encode("utf-8"))

    # The manifest entry carries the complete label (not a subset) so a reader never has
    # to cross-reference the on-disk label.json to answer "what does this case expect" --
    # corpus/MANIFEST.json is meant to be the one self-contained index.
    return {"case_id": case_id, "artifacts": artifacts, **label}


def write_gap_case(spec: FaultSpec) -> dict:
    """DOCUMENTED_GAP faults get a manifest entry, never a case directory with fabricated
    artifacts -- see harness/faults/base.py and sha1_signature_downgrade.py."""
    case_dir = _fresh_case_dir(spec.fault_id)
    label = {
        "case_id": spec.fault_id,
        "fault_id": spec.fault_id,
        "category": spec.category.value,
        "gap_reason": spec.gap_reason,
        "note": "DOCUMENTED_GAP: no executable case, no artifacts. See harness/faults/base.py.",
    }
    with open(os.path.join(case_dir, "label.json"), "w") as f:
        json.dump(label, f, indent=2)
    return {
        "case_id": spec.fault_id,
        "artifacts": {"label.json": _sha256_bytes(json.dumps(label, indent=2).encode("utf-8"))},
        "har_ref": None,
        **label,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _base_specs() -> list[FaultSpec]:
    executable = [f for f in ALL_FAULTS if f.category != FaultCategory.DOCUMENTED_GAP]
    return executable + AMBIGUOUS_CASES + CONFLICTING_CASES


def _gap_specs() -> list[FaultSpec]:
    return [f for f in ALL_FAULTS if f.category == FaultCategory.DOCUMENTED_GAP]


def generate_corpus(verbose: bool = True) -> dict:
    os.makedirs(CASES_DIR, exist_ok=True)
    manifest_cases: dict[str, dict] = {}
    errors: list[str] = []

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    # 1. Base cases -- every fault-like spec, precise register, case_id == fault_id.
    for spec in _base_specs():
        try:
            resolved = resolve_artifacts(spec)
            run = verify_and_selftest(spec, resolved.raw, resolved.ctx)
            narrative = render_narrative(spec.fault_id, "precise") if spec.fault_id in FAULT_NARRATIVE_FACTS else None
            entry = write_case(spec.fault_id, spec, resolved, run, narrative, "precise")
            manifest_cases[spec.fault_id] = entry
            log(f"  ok    {spec.fault_id}")
        except SelfTestFailure as exc:
            errors.append(str(exc))
            log(f"  FAIL  {exc}")

    # 2. Hero-fault register variants -- same artifacts, different narrative text only.
    specs_by_id = {s.fault_id: s for s in _base_specs()}
    for fault_id in HERO_FAULT_IDS:
        spec = specs_by_id[fault_id]
        resolved = resolve_artifacts(spec)
        run = verify_and_selftest(spec, resolved.raw, resolved.ctx)
        for register in NON_PRECISE_REGISTERS:
            case_id = f"{fault_id}__{register}"
            try:
                narrative = render_narrative(fault_id, register)
                entry = write_case(case_id, spec, resolved, run, narrative, register)
                manifest_cases[case_id] = entry
                log(f"  ok    {case_id}")
            except SelfTestFailure as exc:
                errors.append(str(exc))
                log(f"  FAIL  {exc}")

    # 3. Adversarial overlays -- apply a payload on top of an already-verified base case's
    # real artifacts, then re-verify to prove the injected content did not change what the
    # deterministic verifier concludes.
    for payload in ALL_PAYLOADS:
        base_fault_id = ADVERSARIAL_PLAN[payload.payload_id]
        spec = specs_by_id[base_fault_id]
        resolved = resolve_artifacts(spec)
        case_id = f"{base_fault_id}__adv_{payload.taxonomy_class.lower()}"
        try:
            raw, har = resolved.raw, resolved.har
            if payload.xml_apply is not None:
                if raw is None:
                    raise SelfTestFailure(f"{case_id}: payload targets saml_response but base case has none")
                raw = payload.xml_apply(raw)
            if payload.har_apply is not None:
                if har is None:
                    raise SelfTestFailure(f"{case_id}: payload targets har but base case has none")
                har = payload.har_apply(har)

            narrative = render_narrative(base_fault_id, "precise")
            if payload.narrative_apply is not None:
                narrative = {**narrative, "body": payload.narrative_apply(narrative["body"])}

            # Re-verify: the injected content must not change the base fault's own
            # predicted check states. This is the deterministic half of the injection-
            # resistance claim -- desk/ground (Phase 4) proves the *model* half.
            run = verify_and_selftest(spec, raw, resolved.ctx)

            adv_resolved = ResolvedArtifacts(
                raw=raw,
                ctx=resolved.ctx,
                har=har,
                har_is_case_specific=True if payload.har_apply is not None else resolved.har_is_case_specific,
                no_saml_response_reason=resolved.no_saml_response_reason,
            )
            entry = write_case(case_id, spec, adv_resolved, run, narrative, "precise", injection=payload)
            manifest_cases[case_id] = entry
            log(f"  ok    {case_id}  (injection did not change verifier output)")
        except SelfTestFailure as exc:
            errors.append(str(exc))
            log(f"  FAIL  {exc}")

    # 4. Documented gaps -- recorded, not fabricated.
    for spec in _gap_specs():
        entry = write_gap_case(spec)
        manifest_cases[spec.fault_id] = entry
        log(f"  gap   {spec.fault_id}")

    if errors:
        raise SelfTestFailure(f"{len(errors)} case(s) failed self-test:\n" + "\n".join(errors))

    shared_baseline_har_bytes = json.dumps(_load_har(baseline.GOOD_HAR_PATH), indent=2).encode("utf-8")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "shared_artifacts": {
            "shared_baseline_har": {
                "path": "harness/capture/captured/login.har",
                "sha256": _sha256_bytes(shared_baseline_har_bytes),
                "note": (
                    "Most cases reuse this file byte-for-byte and are NOT duplicated into "
                    "their own case directory -- see label.json's har_ref for each case. "
                    "Only cases whose fault mechanism produced different HAR bytes (a "
                    "har_transform, or a LIVE_CAPTURE fault with its own real capture) "
                    "carry a case-local login.har."
                ),
            }
        },
        "cases": manifest_cases,
        "totals": {
            "total_cases": len(manifest_cases),
            "base_cases": len(_base_specs()),
            "register_variants": len(HERO_FAULT_IDS) * len(NON_PRECISE_REGISTERS),
            "adversarial_cases": len(ALL_PAYLOADS),
            "documented_gaps": len(_gap_specs()),
        },
    }
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
    log(f"\nwrote {MANIFEST_PATH}")
    log(json.dumps(manifest["totals"], indent=2))
    return manifest


if __name__ == "__main__":
    generate_corpus()
