"""desk/api.py -- the HTTP surface plan sections 17/22 assume exists: a case's home for
n8n's WF1 intake and WF2 approval gate, and the server-rendered case card (the model-
input-transcript panel is called out in plan section 22 as the single most persuasive
element in the whole project).

Scope, stated honestly rather than left implicit. This module's POST /cases endpoint is
a DEMO intake: it wraps one of the frozen corpus cases under corpus/cases/ (the same
cases eval/run.py drives) rather than accepting a live customer-supplied artifact
bundle. desk/intake -- HAR/XML upload parsing with size/entity limits, and custody
scanning of a whole live bundle rather than just a narrative -- does not exist yet (plan
section 26's repo layout lists desk/intake/ as planned; there is no source in it today).
Wiring a real upload path is future work. This module reuses eval.run's corpus loaders
and desk.pipeline.run_pipeline() so a demo case runs through the exact same
deterministic-verify -> reason -> ground sequence a live case eventually will, rather
than reimplementing a second, divergent path. /cases/<id>/artifacts (the WF3
evidence-chase endpoint) is out of scope for this module for the identical reason: there
is no live artifact intake yet for a chased reply to feed.

Detail cache, also stated honestly. desk/case/store.py (plan section 19) only has SQL
tables for Case, TraceEvent, and Approval -- CheckResult, ModelInvocation,
GroundingResult, InjectionSignal, and PolicyDecision have no persistence layer yet.
Building four more tables is out of scope for this module, so the full PipelineResult
and PolicyDecision behind a case live in an in-process dict, keyed by case id. This is a
real, named limitation, not a silent shortcut: it does not survive a process restart,
and a case created in one process is invisible to another. GET /cases/<id> and the case
card degrade honestly when the cache is empty (durable fields only) rather than crashing
or fabricating detail. Extending desk/case/store.py is the real fix, not a workaround
added here.

Prompt reconstruction is the case card's core trick. Nothing upstream persists a job's
full outbound prompt text -- JobResult only carries prompt_sha256. The case card rebuilds
each prompt from data already on hand, using the exact recipe desk/reason/jobs.py's
run_job_a/run_job_b/run_job_c use internally, and hashes the rebuild to compare against
the stored prompt_sha256. A match is a self-verification that the displayed transcript
is what was actually sent; a mismatch is surfaced, not hidden, because a silent mismatch
would be worse than showing no transcript at all.
"""

from __future__ import annotations

import hashlib
import html
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request

from desk.case.approval import Approval, DecisionValidationError, record_decision
from desk.case.orchestrate import advance_verifying_case
from desk.case.state import Case, CaseState, IllegalTransition, new_case, transition
from desk.case.store import CaseStore, connect
from desk.case.trace import TraceEvent, append_event, verify_chain
from desk.custody.scan import run_custody
from desk.ground.validator import GroundingResult
from desk.pipeline import PipelineResult, run_pipeline
from desk.policy.rules import PolicyDecision
from desk.reason.fixtures import FixtureCache
from desk.reason.jobs import JobResult
from desk.reason.prompts import build_job_a_prompt, build_job_b_prompt, build_job_c_prompt
from desk.verify.gaps import compute_gaps
from eval.run import CASES_DIR, build_clients, load_context, load_label, load_narrative

# --------------------------------------------------------------------------------- #
# In-process detail cache -- see module docstring
# --------------------------------------------------------------------------------- #


@dataclass
class CaseDetail:
    corpus_case: str
    narrative: dict[str, Any] | None
    result: PipelineResult
    decision: PolicyDecision


def _hash_json(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------------- #
# Demo intake -- loads one frozen corpus case into what run_pipeline() needs
# --------------------------------------------------------------------------------- #


def _known_corpus_cases() -> list[str]:
    return sorted(p.name for p in CASES_DIR.iterdir() if p.is_dir())


def _load_corpus_bundle(corpus_case: str) -> tuple[Any, dict | None, bytes | None, dict]:
    """Returns (ctx, narrative, raw_saml_response, label) -- the subset of
    eval.run.run_case()'s own loading logic this module needs. Deliberately not calling
    run_case() itself: run_case() also does stored-check-result parity assertions and
    CaseRecord serialization, which are eval-only concerns, not case-intake concerns."""
    case_dir = CASES_DIR / corpus_case
    label = load_label(case_dir)
    ctx = load_context(case_dir)
    narrative = load_narrative(case_dir)
    if label.get("no_saml_response_reason"):
        raw: bytes | None = None
    else:
        saml_path = case_dir / "saml_response.xml"
        raw = saml_path.read_bytes() if saml_path.exists() else None
    return ctx, narrative, raw, label


# --------------------------------------------------------------------------------- #
# JSON serialization helpers
# --------------------------------------------------------------------------------- #


def _case_json(case: Case) -> dict[str, Any]:
    return {
        "id": case.id,
        "correlation_id": case.correlation_id,
        "tenant_ref": case.tenant_ref,
        "state": case.state.value,
        "disposition": case.disposition,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "security_flags": list(case.security_flags),
    }


def _trace_json(event: TraceEvent) -> dict[str, Any]:
    return {
        "seq": event.seq,
        "stage": event.stage,
        "payload_sha256": event.payload_sha256,
        "prev_hash": event.prev_hash,
        "at": event.at,
        "hash": event.hash,
    }


def _approval_json(approval: Approval) -> dict[str, Any]:
    return {
        "id": approval.id,
        "approver": approval.approver,
        "decision": approval.decision,
        "responded_at": approval.responded_at,
        "override_reason": approval.override_reason,
        "channel": approval.channel,
        "latency_seconds": approval.latency_seconds,
    }


def _job_json(job: JobResult) -> dict[str, Any]:
    return {
        "tier_used": job.tier_used,
        "accepted": job.accepted,
        "prompt_sha256": job.prompt_sha256,
        "parsed": job.parsed,
        "schema_violations": job.schema_violations,
        "latency_ms": job.latency_ms,
        "input_tokens": job.input_tokens,
        "output_tokens": job.output_tokens,
        "instruction_signals": job.instruction_signals,
    }


def _grounding_json(grounding: GroundingResult) -> dict[str, Any]:
    return {
        "accepted": grounding.accepted,
        "claims_total": grounding.claims_total,
        "claims_verified": grounding.claims_verified,
        "violations": [
            {"kind": v.kind, "detail": v.detail, "claim_index": v.claim_index} for v in grounding.violations
        ],
    }


def _detail_json(detail: CaseDetail) -> dict[str, Any]:
    result = detail.result
    return {
        "corpus_case": detail.corpus_case,
        "verify_state": result.verify_state,
        "final_root_cause": result.final_root_cause,
        "checks": [
            {
                "check_id": r.check_id,
                "assurance": r.assurance.value,
                "observed": r.observed,
                "expected": r.expected,
                "reason": r.reason,
            }
            for r in (result.run.results if result.run else [])
        ],
        "jobs": {
            letter: _job_json(job)
            for letter, job in (("A", result.job_a), ("B", result.job_b), ("C", result.job_c))
            if job is not None
        },
        "grounding": _grounding_json(result.grounding) if result.grounding is not None else None,
        "policy": {
            "disposition": detail.decision.disposition,
            "policy_version": detail.decision.policy_version,
            "matched_rules": detail.decision.matched_rules,
            "security_flags": detail.decision.security_flags,
        },
    }


# --------------------------------------------------------------------------------- #
# Prompt reconstruction -- see module docstring
# --------------------------------------------------------------------------------- #


def _reconstruct_job_a_prompt(narrative: dict[str, Any]) -> str:
    subject_defanged = run_custody("narrative", narrative["subject"].encode("utf-8")).defanged_bytes.decode("utf-8")
    body_defanged = run_custody("narrative", narrative["body"].encode("utf-8")).defanged_bytes.decode("utf-8")
    return build_job_a_prompt(subject_defanged, body_defanged)


def _verified_prompt(prompt: str, stored_sha256: str) -> dict[str, Any]:
    reconstructed_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return {
        "prompt": prompt,
        "reconstructed_sha256": reconstructed_sha256,
        "stored_sha256": stored_sha256,
        "verified": reconstructed_sha256 == stored_sha256,
    }


def _reconstruct_prompts(detail: CaseDetail) -> dict[str, dict[str, Any]]:
    """Rebuilds each job's exact outbound prompt from data already on hand and
    self-verifies the rebuild against the stored prompt_sha256. Keyed by job letter;
    a job that never ran, or whose inputs are unavailable, is simply absent from the
    returned dict rather than reported as a mismatch."""
    result = detail.result
    out: dict[str, dict[str, Any]] = {}

    if result.job_a is not None and detail.narrative is not None:
        prompt = _reconstruct_job_a_prompt(detail.narrative)
        out["A"] = _verified_prompt(prompt, result.job_a.prompt_sha256)

    job_a_facts = result.job_a.parsed if result.job_a is not None else None

    if result.job_b is not None and result.run is not None:
        gaps = compute_gaps(result.run)
        prompt = build_job_b_prompt(gaps, job_a_facts)
        out["B"] = _verified_prompt(prompt, result.job_b.prompt_sha256)

    if result.job_c is not None and result.run is not None:
        check_rows = [
            {
                "check_id": r.check_id,
                "assurance": r.assurance.value,
                "observed": r.observed,
                "expected": r.expected,
                "reason": r.reason,
            }
            for r in result.run.results
        ]
        prompt = build_job_c_prompt(check_rows, job_a_facts)
        out["C"] = _verified_prompt(prompt, result.job_c.prompt_sha256)

    return out


# --------------------------------------------------------------------------------- #
# Case card -- server-rendered HTML, following Control Plane's lab/api.py pattern
# (plan section 22): HTML built in Python, no frontend framework, no template files.
# --------------------------------------------------------------------------------- #

_CARD_CSS = """<style>
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; max-width: 960px;
       margin: 2.5rem auto; padding: 0 1.25rem 3rem; color: #1a1a1a; line-height: 1.5;
       background: #fafafa; }
header.hero { margin-bottom: 0.5rem; }
h1 { margin: 0 0 0.5rem; font-size: 1.6rem; letter-spacing: -0.01em; }
.pills { margin-bottom: 0.5rem; }
.pill { display: inline-block; padding: 0.18rem 0.7rem; border-radius: 999px; font-size: 0.8rem;
        font-weight: 600; margin-right: 0.4rem; }
.pill-state { background: #eef0f2; color: #333; }
.pill-good { background: #dff3e3; color: #146c2e; }
.pill-warn { background: #fdecd2; color: #8a5300; }
.pill-bad { background: #fbe0e0; color: #9c1f1f; }
.pill-info { background: #dfeaf7; color: #1a5487; }
.pill-neutral { background: #ececec; color: #444; }
.meta { color: #5a5a5a; font-size: 0.85rem; margin-bottom: 1.25rem; }
section.panel { background: #fff; border: 1px solid #e2e2e2; border-radius: 10px;
                padding: 1.15rem 1.35rem 1.35rem; margin: 1.1rem 0;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03); }
section.panel > h2 { margin: 0 0 0.85rem; font-size: 1.05rem; border-bottom: 1px solid #eee;
                      padding-bottom: 0.45rem; }
section.panel h3 { font-size: 0.95rem; margin: 1.1rem 0 0.4rem; }
.flag { display: inline-block; background: #b02a2a; color: #fff; padding: 0.1rem 0.5rem;
        border-radius: 3px; margin-right: 0.4rem; font-size: 0.85rem; }
.note { color: #a05a00; background: #fff6e5; border: 1px solid #e8c27a; padding: 0.6rem 0.85rem;
        border-radius: 6px; }
table { border-collapse: collapse; width: 100%; margin: 0.5rem 0; }
th, td { border: 1px solid #e6e6e6; padding: 0.5rem 0.65rem; text-align: left; font-size: 0.88rem; }
th { background: #f6f7f8; font-weight: 600; }
tr.a-verified { background: #eefaf0; }
tr.a-failed { background: #fdecec; }
tr.a-review_required { background: #fff6e5; }
.tier { font-size: 0.75rem; color: #5a5a5a; font-weight: normal; }
.verify-badge { font-size: 0.75rem; padding: 0.05rem 0.4rem; border-radius: 3px; background: #0e5561; color: #fff; }
.verify-badge.bad { background: #b02a2a; }
pre { background: #f7f7f7; border: 1px solid #e6e6e6; padding: 0.7rem; overflow-x: auto;
      white-space: pre-wrap; word-break: break-word; font-size: 0.85rem; border-radius: 6px; }
.hash { font-family: monospace; }
.summary-block { font-size: 0.92rem; }
.summary-block .label { color: #5a5a5a; font-size: 0.78rem; text-transform: uppercase;
                         letter-spacing: 0.04em; margin: 0.7rem 0 0.15rem; }
ul.claims, ul.fixsteps { list-style: none; margin: 0.3rem 0 0.6rem; padding: 0; }
ul.fixsteps li { padding-left: 1.1rem; position: relative; margin-bottom: 0.25rem; font-size: 0.9rem; }
ul.fixsteps li::before { content: "\\2192"; position: absolute; left: 0; color: #5a5a5a; }
ul.claims li { padding: 0.45rem 0.65rem; border-radius: 6px; margin-bottom: 0.35rem; font-size: 0.88rem; }
ul.claims li.c-verified { background: #eefaf0; }
ul.claims li.c-failed { background: #fdecec; }
ul.claims li.c-review_required { background: #fff6e5; }
ul.claims li.c-other { background: #f2f2f2; }
ul.claims li .check-id { font-family: monospace; font-weight: 600; margin-right: 0.5rem; }
</style>"""


# Purely cosmetic: which pill color reads a disposition value as good/needs-a-human/
# serious/waiting at a glance. Falls back to a neutral pill for anything not in
# desk/policy/rules.py's DISPOSITIONS today, so a future disposition value never breaks
# rendering, it just renders unstyled rather than colored.
_DISPOSITION_PILL_CLASS = {
    "auto": "pill-good",
    "review_required": "pill-warn",
    "escalate": "pill-bad",
    "awaiting_evidence": "pill-info",
}


def _render_card(
    case: Case,
    trace: list[TraceEvent],
    chain_valid: bool,
    approvals: list[Approval],
    detail: CaseDetail | None,
) -> str:
    esc = html.escape
    disp_cls = _DISPOSITION_PILL_CLASS.get(case.disposition or "", "pill-neutral")
    parts: list[str] = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>Case {esc(case.id)}</title>",
        _CARD_CSS,
        "</head><body>",
        "<header class='hero'>",
        f"<h1>Case {esc(case.id)}</h1>",
        "<div class='pills'>",
        f"<span class='pill pill-state'>{esc(case.state.value)}</span>",
        f"<span class='pill {disp_cls}'>{esc(case.disposition or 'no disposition yet')}</span>",
        "</div>",
        f"<div class='meta'>correlation {esc(case.correlation_id)}<br>"
        f"created {esc(case.created_at)} &middot; updated {esc(case.updated_at)}</div>",
        "</header>",
    ]

    if case.security_flags:
        parts.append(
            "<div>" + "".join(f"<span class='flag'>{esc(f)}</span>" for f in case.security_flags) + "</div>"
        )

    if detail is None:
        parts.append(
            "<p class='note'>Detail cache has no entry for this case (process restarted, "
            "or the case predates this process). Showing durable fields only.</p>"
        )
    else:
        result = detail.result

        parts.append("<section class='panel'><h2>Custody</h2>")
        parts.append(
            "<p class='note'>desk/custody is not wired into case-level intake in this build "
            "(see module docstring) -- Job A's own narrative custody scan is shown in its "
            "model input transcript below.</p>"
        )
        parts.append("</section>")

        parts.append("<section class='panel'><h2>Verification</h2>")
        if result.run is None:
            parts.append(f"<p class='note'>verify_state: {esc(result.verify_state)} -- no SAMLResponse to check.</p>")
        else:
            parts.append(
                "<table class='checks'><tr><th>check</th><th>assurance</th>"
                "<th>observed</th><th>expected</th><th>reason</th></tr>"
            )
            for r in result.run.results:
                parts.append(
                    f"<tr class='a-{esc(r.assurance.value)}'><td>{esc(r.check_id)}</td>"
                    f"<td>{esc(r.assurance.value)}</td><td>{esc(r.observed or '')}</td>"
                    f"<td>{esc(r.expected or '')}</td><td>{esc(r.reason)}</td></tr>"
                )
            parts.append("</table>")
        parts.append("</section>")

        prompts = _reconstruct_prompts(detail)
        parts.append("<section class='panel'><h2>Reasoning</h2>")
        any_job = False
        for letter, job in (("A", result.job_a), ("B", result.job_b), ("C", result.job_c)):
            if job is None:
                continue
            any_job = True
            parts.append(f"<h3>Job {letter} <span class='tier'>{esc(job.tier_used)}</span></h3>")
            rp = prompts.get(letter)
            if rp is not None:
                badge = "verified" if rp["verified"] else "MISMATCH"
                badge_cls = "" if rp["verified"] else " bad"
                parts.append(
                    "<details><summary>Model input transcript "
                    f"<span class='verify-badge{badge_cls}'>{badge}</span></summary>"
                    f"<pre>{esc(rp['prompt'])}</pre></details>"
                )
            else:
                parts.append("<p class='note'>Prompt not reconstructable from cached data for this job.</p>")
            if letter == "C" and isinstance(job.parsed, dict) and "claims" in job.parsed:
                # Job C's claims are the model's own per-check assertions, checked
                # against the verifier's own results below in Grounding. Rendered as a
                # list reusing the checks table's verified/failed/review_required
                # color convention, rather than the raw JSON dump used for Jobs A/B,
                # so a reader can eyeball agreement without parsing JSON by hand.
                summary = job.parsed.get("summary")
                root_cause = job.parsed.get("root_cause")
                fix_steps = job.parsed.get("fix_steps") or []
                claims = job.parsed.get("claims") or []
                if summary:
                    parts.append(f"<div class='summary-block'><p>{esc(summary)}</p>")
                    parts.append(
                        f"<div class='label'>Root cause</div><p><code>{esc(root_cause or 'none asserted')}</code></p>"
                    )
                    if fix_steps:
                        parts.append("<div class='label'>Fix steps</div><ul class='fixsteps'>")
                        parts.extend(f"<li>{esc(s)}</li>" for s in fix_steps)
                        parts.append("</ul>")
                    parts.append("</div>")
                parts.append("<ul class='claims'>")
                for c in claims:
                    state = c.get("asserted_state", "")
                    cls = state if state in ("verified", "failed", "review_required") else "other"
                    parts.append(
                        f"<li class='c-{esc(cls)}'><span class='check-id'>{esc(c.get('check_id', ''))}</span>"
                        f"{esc(state)} &middot; {esc(c.get('text', ''))}</li>"
                    )
                parts.append("</ul>")
            else:
                parts.append(f"<pre class='output'>{esc(json.dumps(job.parsed, indent=2, sort_keys=True))}</pre>")
        if not any_job:
            parts.append("<p class='note'>No reasoning job ran for this case.</p>")
        parts.append("</section>")

        if result.grounding is not None:
            g = result.grounding
            parts.append("<section class='panel'><h2>Grounding</h2>")
            parts.append(
                f"<p><span class='pill {'pill-good' if g.accepted else 'pill-bad'}'>"
                f"{'accepted' if g.accepted else 'REJECTED'}</span> "
                f"{g.claims_verified}/{g.claims_total} claims verified</p>"
            )
            if g.violations:
                parts.append(
                    "<ul>" + "".join(f"<li>{esc(v.kind)}: {esc(v.detail)}</li>" for v in g.violations) + "</ul>"
                )
            parts.append("</section>")

        parts.append("<section class='panel'><h2>Policy</h2>")
        parts.append(
            f"<p>disposition <b>{esc(detail.decision.disposition)}</b> "
            f"(policy v{esc(detail.decision.policy_version)})<br>"
            f"matched rules: {esc(', '.join(detail.decision.matched_rules) or '-')}</p>"
        )
        parts.append("</section>")

    parts.append("<section class='panel'><h2>Approvals</h2>")
    if approvals:
        parts.append(
            "<table class='approvals'><tr><th>approver</th><th>decision</th>"
            "<th>responded</th><th>override reason</th></tr>"
        )
        for a in approvals:
            parts.append(
                f"<tr><td>{esc(a.approver)}</td><td>{esc(a.decision)}</td>"
                f"<td>{esc(a.responded_at)}</td><td>{esc(a.override_reason or '')}</td></tr>"
            )
        parts.append("</table>")
    else:
        parts.append("<p class='note'>No approvals recorded yet.</p>")
    parts.append("</section>")

    parts.append("<section class='panel'><h2>Trace</h2>")
    parts.append(f"<p>chain {'valid' if chain_valid else 'INVALID'} &middot; {len(trace)} events</p>")
    parts.append("<table class='trace'><tr><th>seq</th><th>stage</th><th>at</th><th>hash</th></tr>")
    for e in trace:
        parts.append(
            f"<tr><td>{e.seq}</td><td>{esc(e.stage)}</td><td>{esc(e.at)}</td>"
            f"<td class='hash'>{esc(e.hash[:16])}&hellip;</td></tr>"
        )
    parts.append("</table>")
    parts.append("</section>")

    parts.append("</body></html>")
    return "".join(parts)


# --------------------------------------------------------------------------------- #
# App factory
# --------------------------------------------------------------------------------- #


def create_app(store: CaseStore | None = None) -> Flask:
    app = Flask(__name__)
    app.store = store if store is not None else CaseStore(connect(":memory:"))  # type: ignore[attr-defined]
    app.detail_cache: dict[str, CaseDetail] = {}  # type: ignore[attr-defined]

    @app.get("/health")
    def health() -> Response:
        return jsonify({"status": "ok"})

    @app.post("/cases")
    def create_case() -> tuple[Response, int]:
        body = request.get_json(silent=True) or {}
        corpus_case = body.get("corpus_case")
        if not corpus_case:
            return (
                jsonify(
                    {
                        "error": "corpus_case is required -- this is a demo intake wrapping a "
                        "frozen corpus case, not a live artifact-upload endpoint (see module docstring)"
                    }
                ),
                400,
            )
        known = _known_corpus_cases()
        if corpus_case not in known:
            return jsonify({"error": f"unknown corpus_case {corpus_case!r}", "known_corpus_cases": known}), 404

        replay_only = bool(body.get("replay_only", True))
        correlation_id = body.get("correlation_id") or _new_id("corr")

        ctx, narrative, raw_saml_response, _label = _load_corpus_bundle(corpus_case)

        case = new_case(id=_new_id("case"), correlation_id=correlation_id, state=CaseState.VERIFYING)
        app.store.insert_case(case)  # type: ignore[attr-defined]

        prior: TraceEvent | None = None

        def _append(stage: str, payload: Any) -> None:
            nonlocal prior
            ev = append_event(case.id, stage, _hash_json(payload), prior=prior)
            app.store.append_trace_event(ev)  # type: ignore[attr-defined]
            prior = ev

        _append("intake", {"corpus_case": corpus_case, "narrative": narrative, "replay_only": replay_only})

        result = run_pipeline(
            raw_saml_response=raw_saml_response,
            ctx=ctx,
            narrative=narrative,
            clients=build_clients(),
            fixtures=FixtureCache(),
            replay_only=replay_only,
        )

        _append(
            "verify",
            {
                "verify_state": result.verify_state,
                "checks": [
                    {"check_id": r.check_id, "assurance": r.assurance.value}
                    for r in (result.run.results if result.run else [])
                ],
            },
        )

        reasoning_snapshot: dict[str, Any] = {}
        for letter, job in (("A", result.job_a), ("B", result.job_b), ("C", result.job_c)):
            if job is not None:
                reasoning_snapshot[letter] = {
                    "tier_used": job.tier_used,
                    "accepted": job.accepted,
                    "prompt_sha256": job.prompt_sha256,
                    "parsed": job.parsed,
                }
        if reasoning_snapshot:
            _append("reason", reasoning_snapshot)

        if result.grounding is not None:
            _append(
                "ground",
                {
                    "accepted": result.grounding.accepted,
                    "claims_total": result.grounding.claims_total,
                    "claims_verified": result.grounding.claims_verified,
                    "violations": [
                        {"kind": v.kind, "detail": v.detail, "claim_index": v.claim_index}
                        for v in result.grounding.violations
                    ],
                },
            )

        advanced, decision = advance_verifying_case(case, result)

        _append(
            "policy",
            {
                "disposition": decision.disposition,
                "policy_version": decision.policy_version,
                "matched_rules": decision.matched_rules,
                "security_flags": decision.security_flags,
            },
        )

        app.store.update_case(advanced)  # type: ignore[attr-defined]
        app.detail_cache[case.id] = CaseDetail(  # type: ignore[attr-defined]
            corpus_case=corpus_case, narrative=narrative, result=result, decision=decision
        )

        return jsonify(_case_json(advanced)), 201

    @app.get("/cases")
    def list_cases() -> tuple[Response, int] | Response:
        state_param = request.args.get("state")
        if state_param:
            try:
                state = CaseState(state_param)
            except ValueError:
                return jsonify({"error": f"unknown state {state_param!r}"}), 400
            cases = app.store.list_cases_by_state(state)  # type: ignore[attr-defined]
        else:
            cases = []
            for s in CaseState:
                cases.extend(app.store.list_cases_by_state(s))  # type: ignore[attr-defined]
            cases.sort(key=lambda c: c.updated_at)
        return jsonify({"cases": [_case_json(c) for c in cases]})

    @app.get("/cases/<case_id>")
    def get_case(case_id: str) -> tuple[Response, int] | Response:
        case = app.store.get_case(case_id)  # type: ignore[attr-defined]
        if case is None:
            return jsonify({"error": "no such case"}), 404
        trace = app.store.get_trace(case_id)  # type: ignore[attr-defined]
        chain = verify_chain(case_id, trace)
        approvals = app.store.get_approvals(case_id)  # type: ignore[attr-defined]
        payload = _case_json(case)
        payload["trace"] = [_trace_json(e) for e in trace]
        payload["chain_valid"] = chain.valid
        payload["approvals"] = [_approval_json(a) for a in approvals]
        detail = app.detail_cache.get(case_id)  # type: ignore[attr-defined]
        if detail is not None:
            payload["detail"] = _detail_json(detail)
        else:
            payload["detail"] = None
            payload["detail_note"] = (
                "in-process detail cache has no entry for this case (process restarted, "
                "or the case predates this process) -- durable fields only"
            )
        return jsonify(payload)

    @app.get("/cases/<case_id>/card")
    def get_case_card(case_id: str) -> Response:
        case = app.store.get_case(case_id)  # type: ignore[attr-defined]
        if case is None:
            return Response(f"<p>no such case: {html.escape(case_id)}</p>", status=404, mimetype="text/html")
        trace = app.store.get_trace(case_id)  # type: ignore[attr-defined]
        chain = verify_chain(case_id, trace)
        approvals = app.store.get_approvals(case_id)  # type: ignore[attr-defined]
        detail = app.detail_cache.get(case_id)  # type: ignore[attr-defined]
        return Response(_render_card(case, trace, chain.valid, approvals, detail), mimetype="text/html")

    @app.post("/cases/<case_id>/post-for-review")
    def post_for_review(case_id: str) -> tuple[Response, int] | Response:
        case = app.store.get_case(case_id)  # type: ignore[attr-defined]
        if case is None:
            return jsonify({"error": "no such case"}), 404
        try:
            advanced = transition(case, CaseState.HUMAN_REVIEW)
        except IllegalTransition as exc:
            return jsonify({"error": exc.detail}), 409
        app.store.update_case(advanced)  # type: ignore[attr-defined]
        last = app.store.last_trace_event(case_id)  # type: ignore[attr-defined]
        ev = append_event(case_id, "review", _hash_json({"posted_for_review": True}), prior=last)
        app.store.append_trace_event(ev)  # type: ignore[attr-defined]
        return jsonify(_case_json(advanced))

    @app.post("/cases/<case_id>/decision")
    def post_decision(case_id: str) -> tuple[Response, int] | Response:
        case = app.store.get_case(case_id)  # type: ignore[attr-defined]
        if case is None:
            return jsonify({"error": "no such case"}), 404
        body = request.get_json(silent=True) or {}
        approver = body.get("approver")
        decision_str = body.get("decision")
        channel = body.get("channel")
        override_reason = body.get("override_reason")
        if not approver or not decision_str or not channel:
            return jsonify({"error": "approver, decision, and channel are required"}), 400

        trace = app.store.get_trace(case_id)  # type: ignore[attr-defined]
        review_event = next((e for e in reversed(trace) if e.stage == "review"), None)
        requested_at = review_event.at if review_event is not None else None

        try:
            approval = record_decision(
                id=_new_id("appr"),
                case_id=case_id,
                approver=approver,
                decision=decision_str,
                channel=channel,
                override_reason=override_reason,
                requested_at=requested_at,
            )
        except DecisionValidationError as exc:
            return jsonify({"error": exc.detail}), 400

        target_state = CaseState.APPROVED if decision_str == "approved" else CaseState.ESCALATED
        try:
            advanced = transition(case, target_state)
        except IllegalTransition as exc:
            return jsonify({"error": exc.detail}), 409

        app.store.insert_approval(approval)  # type: ignore[attr-defined]
        app.store.update_case(advanced)  # type: ignore[attr-defined]
        last = app.store.last_trace_event(case_id)  # type: ignore[attr-defined]
        ev = append_event(
            case_id,
            "decision",
            _hash_json({"approval_id": approval.id, "decision": approval.decision, "approver": approval.approver}),
            prior=last,
        )
        app.store.append_trace_event(ev)  # type: ignore[attr-defined]

        return jsonify({"case": _case_json(advanced), "approval": _approval_json(approval)})

    @app.post("/cases/<case_id>/publish")
    def post_publish(case_id: str) -> tuple[Response, int] | Response:
        case = app.store.get_case(case_id)  # type: ignore[attr-defined]
        if case is None:
            return jsonify({"error": "no such case"}), 404
        try:
            advanced = transition(case, CaseState.PUBLISHED)
        except IllegalTransition as exc:
            return jsonify({"error": exc.detail}), 409
        app.store.update_case(advanced)  # type: ignore[attr-defined]
        last = app.store.last_trace_event(case_id)  # type: ignore[attr-defined]
        ev = append_event(case_id, "publish", _hash_json({"published": True}), prior=last)
        app.store.append_trace_event(ev)  # type: ignore[attr-defined]
        return jsonify(_case_json(advanced))

    return app


def main() -> None:
    """Dev server entry point for `make serve`. Not a production WSGI target -- Flask's
    own docs say so, and nothing in this project claims otherwise."""
    import os

    db_path = os.environ.get("DESK_DB_PATH", ":memory:")
    store = CaseStore(connect(db_path))
    app = create_app(store=store)
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
