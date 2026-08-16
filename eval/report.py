"""Renders eval/metrics.py's output as a Markdown report: the numbers, the
methodology behind each one, and the honest caveats -- no result appears without the
sentence that qualifies it. This module does no computation of its own; it is
presentation only, reading the same metrics dict eval/metrics.py produces.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from eval.metrics import DEFAULT_FIXTURES_DIR, compute_all_metrics, load_records

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pct(x: float | None) -> str:
    return "n/a (n=0)" if x is None else f"{x * 100:.1f}%"


def _fmt_ms(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0f} ms"


def render_report(metrics: dict) -> str:
    lines: list[str] = []
    w = lines.append

    w("# Assertion Desk -- Phase 4 Evaluation Report")
    w("")
    w(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    w(f"Source run: `{metrics.get('generated_from')}`  ·  replay_only: `{metrics.get('replay_only')}`")
    w(f"Cases in run: **{metrics.get('case_count')}**")
    gap_ids = metrics.get("documented_gap_ids") or []
    if gap_ids:
        w(
            f"Excluded as `documented_gap` (no executable case, see `harness/faults/base.py`): "
            f"`{', '.join(gap_ids)}`"
        )
    w("")
    w(
        "**How to reproduce every number below with no API key and $0 cost:** "
        "`make eval-replay` runs the identical corpus from the recorded `fixtures/` "
        "cache. Live tiers (Gemini, Ollama) are never contacted in replay mode; a "
        "cache miss raises `ReplayMiss` loudly rather than silently falling through."
    )
    w("")

    # ---------------------------------------------------------------- #
    w("## Root-cause accuracy (normal, non-adversarial cases)")
    rc = metrics["root_cause_accuracy"]
    w("")
    w(
        f"n = {rc['n']}. AI-assisted (the real pipeline, after grounding): "
        f"**{_pct(rc['ai_assisted_accuracy'])}** ({rc['ai_correct']}/{rc['n']}). "
        f"Deterministic-only baseline (what the system would answer with every model "
        f"tier disabled, computed by replicating the deterministic template's own "
        f"tie-break rule over the same check results): "
        f"**{_pct(rc['deterministic_only_accuracy'])}** ({rc['deterministic_correct']}/{rc['n']})."
    )
    w("")
    w(
        "This is the honest 'what does AI add' comparison. The deterministic template "
        "always picks the first `FAILED` check in verifier-result order as root cause; "
        "it has no way to know which of several genuinely-FAILED checks is the fault "
        "the corpus actually injected, so a case with multiple real failures (a "
        "cascade) can score wrong here even though every individual claim it makes is "
        "true. That is a known, named limitation of the deterministic fallback, not a "
        "bug -- see `desk/reason/jobs.py:render_deterministic_job_c`."
    )
    w("")
    w(
        "Note: this implementation's Job C schema produces a single `root_cause`, not "
        "a ranked list, so there is no top-3 variant of this metric -- an intentional "
        "simplification from the original plan, not an oversight."
    )
    w("")
    if rc["rows"]:
        w("| Case | Expected | AI-assisted | Deterministic-only |")
        w("|---|---|---|---|")
        for r in rc["rows"]:
            ai_mark = "OK" if r["ai_correct"] else "WRONG"
            det_mark = "OK" if r["deterministic_correct"] else "WRONG"
            w(
                f"| `{r['case_id']}` | `{r['expected']}` | `{r['ai_actual']}` ({ai_mark}) "
                f"| `{r['deterministic_actual']}` ({det_mark}) |"
            )
        w("")

    # ---------------------------------------------------------------- #
    w("## Refusal correctness (ambiguous stratum)")
    rf = metrics["refusal_correctness"]
    w("")
    w(
        f"n = {rf['n']} (`withheld_cert`, `withheld_clock`). Correct behavior is "
        f"never publishing a root cause when the deciding artifact was withheld. "
        f"**{_pct(rf['accuracy'])}** ({rf['correct']}/{rf['n']}) correctly stayed silent."
    )
    w("")
    w(
        "Scored on `final_root_cause is None` only. `desk/policy` (the disposition "
        "layer, e.g. `awaiting_evidence`) is not built as of Phase 4, so there is no "
        "computed disposition to check the label's `expected_disposition` against yet."
    )
    w("")

    # ---------------------------------------------------------------- #
    w("## Conflicting-handling correctness (the one conflicting case)")
    ch = metrics["conflicting_handling_correctness"]
    w("")
    w(
        f"n = {ch['n']} (`duplicate_role_attributes`). This is the corpus's own "
        f"documented exception to 'ambiguous/conflicting always refuses': its "
        f"expected root cause is `SAML-ATTR-01`, published under a `review_required` "
        f"framing, not a refusal. **{_pct(ch['accuracy'])}** ({ch['correct']}/{ch['n']}) "
        f"matched exactly."
    )
    w("")
    w(
        "Scored separately from refusal correctness on purpose -- the original plan "
        "(section 23) treated `ambiguous` and `conflicting` as one 'should refuse' "
        "metric, which this corpus's own label data contradicts. See "
        "`eval/metrics.py`'s module docstring."
    )
    w("")

    # ---------------------------------------------------------------- #
    w("## Malformed-handling correctness")
    mh = metrics["malformed_handling_correctness"]
    w("")
    w(
        f"n = {mh['n']} (`truncated_response`, `double_encoded_response`). Correct "
        f"behavior is a clean `parse_error` state, no crash, no fabricated root "
        f"cause. **{_pct(mh['accuracy'])}** ({mh['correct']}/{mh['n']})."
    )
    w("")

    # ---------------------------------------------------------------- #
    w("## No-SAML-response handling correctness")
    ns = metrics["no_saml_response_handling_correctness"]
    w("")
    w(
        f"n = {ns['n']} (`negative_control` -- the IdP rejected the credential before "
        f"producing a SAMLResponse at all; the customer's actual problem was a typo'd "
        f"password, not a broken trust chain). Correct behavior is "
        f"`verify_state == \"no_saml_response\"` and no root cause. "
        f"**{_pct(ns['accuracy'])}** ({ns['correct']}/{ns['n']})."
    )
    w("")

    # ---------------------------------------------------------------- #
    w("## Grounding rejection rate")
    gr = metrics["grounding_rejection_rate"]
    w("")
    w(
        f"{gr['n_rejected']}/{gr['n_graded']} Job C outputs that actually reached the "
        f"grounding validator (live or fixture tier only -- the deterministic "
        f"template is grounded by construction and is never graded) were rejected: "
        f"**{_pct(gr['rejection_rate'])}**."
    )
    if gr["rejected_case_ids"]:
        w(f"Rejected: `{', '.join(gr['rejected_case_ids'])}`.")
    w("")
    w(
        "**Caveat, stated once:** the validator's accept/reject decision is a "
        "deterministic function of its inputs, so 'percent of violations caught' is "
        "tautologically 100% by construction -- a violation only exists because the "
        "validator's own rule defines it. The number above (how often a real Job C "
        "output actually violates grounding at all) is the meaningful one, not "
        "whether the validator notices when it does."
    )
    w("")

    # ---------------------------------------------------------------- #
    w("## Injection resistance")
    ir = metrics["injection_resistance"]
    w("")
    w(f"n = {ir['n']} adversarial cases, split by whether the injection payload has a live path into a model prompt:")
    w("")
    s3 = ir["s3_live_path"]
    tv = ir["s1_s2_s4_structurally_inapplicable"]
    w(
        f"- **S3 (context manipulation via narrative, a real prompt path):** "
        f"{s3['resisted']}/{s3['n']} resisted."
    )
    w(
        f"- **S1/S2/S4 (direct override, persona hijack, obfuscated -- payload "
        f"targets an artifact/location no job reads under the current architecture):** "
        f"{tv['resisted']}/{tv['n']} resisted. {tv['note']}."
    )
    w("")
    w(
        "Reporting these as one four-case number would silently launder three "
        "structural free passes into an apparent full-coverage result. They are kept "
        "separate deliberately."
    )
    w("")
    if ir["rows"]:
        w("| Case | Injection class | Live prompt path | Instruction signals detected | Outcome unaffected |")
        w("|---|---|---|---|---|")
        for r in ir["rows"]:
            w(
                f"| `{r['case_id']}` | `{r['injection']}` | {r['has_live_prompt_path']} "
                f"| {r['instruction_signals_detected']} | {r['outcome_unaffected']} |"
            )
        w("")

    # ---------------------------------------------------------------- #
    w("## Secret leakage to prompt")
    sl = metrics["secret_leakage_to_prompt"]
    w("")
    w(
        f"Independent pattern scan (JWTs, `Bearer` headers, session-cookie "
        f"assignments, PEM private-key blocks -- separate code from `desk/custody`'s "
        f"own detector, on purpose) of {sl['fixtures_scanned']} recorded fixture "
        f"prompts, the literal bytes sent to a model provider: "
        f"**{sl['leak_count']} hit(s)**."
    )
    if sl["hits"]:
        w("")
        w("| Fixture | Pattern | Preview |")
        w("|---|---|---|")
        for h in sl["hits"]:
            w(f"| `{h['fixture_file']}` | `{h['pattern']}` | `{h['span_preview']}` |")
    w("")

    # ---------------------------------------------------------------- #
    w("## Tier usage")
    tu = metrics["tier_usage"]
    w("")
    w("| Job | Tier breakdown |")
    w("|---|---|")
    for job in ("A", "B", "C"):
        counts = tu.get(job, {})
        breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "(no calls)"
        w(f"| {job} | {breakdown} |")
    w("")
    w(
        "`deterministic` entries are real, observed fallback events, not "
        "hypothetical -- local `qwen3:1.7b` reliably fails schema validation or times "
        "out on a subset of prompts (see `docs/PHASE4_NOTES.md`), and the system "
        "degrades cleanly every time rather than crashing or fabricating."
    )
    w("")

    # ---------------------------------------------------------------- #
    w("## Cost, tokens, latency per job")
    ctl = metrics["cost_tokens_latency"]
    w("")
    w("| Job | Live calls | Mean latency | Total input tokens | Total output tokens |")
    w("|---|---|---|---|---|")
    for job in ("A", "B", "C"):
        s = ctl.get(job, {})
        w(
            f"| {job} | {s.get('n_with_live_call', 0)} | {_fmt_ms(s.get('mean_latency_ms'))} "
            f"| {s.get('total_input_tokens', 0)} | {s.get('total_output_tokens', 0)} |"
        )
    w("")
    w(
        "Local Ollama calls are $0. No `GEMINI_API_KEY` is configured in this "
        "environment, so every live call in this run went to the local `qwen3:1.7b` "
        "fallback tier -- see `docs/PHASE4_NOTES.md` for what that means for these "
        "numbers and for prose quality."
    )
    w("")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Markdown eval report from an eval/run.py records.json.")
    parser.add_argument("records_path", type=Path, help="Path to a records.json produced by eval/run.py")
    parser.add_argument("--fixtures-dir", type=Path, default=DEFAULT_FIXTURES_DIR)
    parser.add_argument("--metrics-out", type=Path, default=None, help="Also write the raw metrics JSON here")
    parser.add_argument("--out", type=Path, required=True, help="Where to write the Markdown report")
    args = parser.parse_args()

    records = load_records(args.records_path)
    metrics = compute_all_metrics(records, args.fixtures_dir)
    report = render_report(metrics)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    print(f"Wrote report to {args.out}")

    if args.metrics_out:
        args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
        args.metrics_out.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
        print(f"Wrote metrics to {args.metrics_out}")


if __name__ == "__main__":
    main()
