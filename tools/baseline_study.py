"""tools/baseline_study.py -- an interactive local timer for docs/HUMAN_BASELINE.md.

This is a research instrument, not product code, which is why it lives outside desk/
rather than inside it (desk/api.py serves the actual system; this serves the human
running an experiment on it). It exists for one reason: the 20-case stopwatch study
docs/HUMAN_BASELINE.md describes is real hands-on work that only Rasheed can do, and
this tool's job is to remove every bit of friction around that work -- sampling,
timing, recording, self-scoring, and writing the results file -- without doing any of
the actual diagnostic work for him. If it diagnosed the case, the study would be
measuring the tool, not the manual baseline it exists to measure.

Two things this tool enforces structurally, matching the project's own habits:

1. **No peeking before committing.** docs/HUMAN_BASELINE.md is explicit: "compare
   after you have already committed to an answer, not before." /case/<id> never
   renders label.json or check_results.json until /case/<id>/submit has been called
   for that case. There is no route that would show both at once.
2. **The sample is written down before any timing starts**, exactly like the protocol
   asks ("so the sample cannot be quietly cherry-picked after seeing which ones go
   fast"). The very first request to this app samples the corpus once, with a fixed
   seed for reproducibility, and persists the full case list to
   docs/baseline_timings.json immediately -- before a single clock has been started.
   Restarting this process never reshuffles an in-progress study; it only re-reads
   what is already on disk.

Honest deviation from the written protocol, surfaced rather than silently patched:
docs/HUMAN_BASELINE.md calls for 15 cases from `normal` and 5 from `ambiguous` (n=20).
corpus/MANIFEST.json only contains 2 ambiguous-difficulty cases in the whole 51-case
corpus (withheld_cert, withheld_clock) -- Phase 3 never generated a fifth. Inventing
3 more ambiguous cases to hit the protocol's number would be exactly the kind of
fabrication this whole project exists to refuse, so this tool samples 15 normal + the
2 ambiguous cases that actually exist (n=17) and says so, both here and on every page
that shows the sample.

Run it:
    python3 tools/baseline_study.py
Then open http://127.0.0.1:5151/
"""

from __future__ import annotations

import html
import json
import random
import statistics
import time
from pathlib import Path
from typing import Any

from flask import Flask, Response, redirect, request, url_for

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus" / "cases"
MANIFEST_PATH = ROOT / "corpus" / "MANIFEST.json"
STATE_PATH = ROOT / "docs" / "baseline_timings.json"
RESULTS_MD_PATH = ROOT / "docs" / "HUMAN_BASELINE_RESULTS.md"

# Fixed on purpose: if docs/baseline_timings.json is ever deleted, re-running this
# module reproduces the identical 17-case sample rather than a new random one.
SAMPLE_SEED = 20260817

NO_GUESS = "NO_DIAGNOSIS_REQUEST_EVIDENCE"  # the "I would ask for more, not guess" option

app = Flask(__name__)

_manifest_cache: dict[str, Any] | None = None
_check_ids_cache: list[str] | None = None


def load_manifest() -> dict[str, Any]:
    global _manifest_cache
    if _manifest_cache is None:
        _manifest_cache = json.loads(MANIFEST_PATH.read_text())
    return _manifest_cache


def known_check_ids() -> list[str]:
    """Derived from the corpus itself (not hardcoded) so the dropdown can never drift
    out of sync with what desk/verify actually emits."""
    global _check_ids_cache
    if _check_ids_cache is not None:
        return _check_ids_cache
    ids: set[str] = set()
    for f in CORPUS_DIR.glob("*/check_results.json"):
        data = json.loads(f.read_text())
        if not isinstance(data, dict):
            continue
        for c in data.get("results") or []:
            ids.add(c["check_id"])
    _check_ids_cache = sorted(ids)
    return _check_ids_cache


def build_sample(manifest: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    cases = manifest["cases"]
    normal_ids = sorted(cid for cid, e in cases.items() if e.get("difficulty") == "normal")
    ambiguous_ids = sorted(cid for cid, e in cases.items() if e.get("difficulty") == "ambiguous")
    rng = random.Random(SAMPLE_SEED)
    normal_sample = sorted(rng.sample(normal_ids, k=min(15, len(normal_ids))))
    ambiguous_sample = ambiguous_ids  # all that exist; protocol asked for 5, only 2 exist
    return normal_sample + ambiguous_sample, normal_sample, ambiguous_sample


def init_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())

    manifest = load_manifest()
    sample, normal_sample, ambiguous_sample = build_sample(manifest)
    state = {
        "seed": SAMPLE_SEED,
        "protocol_deviation": (
            "docs/HUMAN_BASELINE.md calls for 15 cases from 'normal' and 5 from "
            "'ambiguous' (n=20). corpus/MANIFEST.json contains only 2 ambiguous-"
            "difficulty cases in the entire 51-case corpus (withheld_cert, "
            "withheld_clock). This sample uses 15 normal + both available ambiguous "
            "cases (n=17) rather than inventing 3 that do not exist."
        ),
        "normal_cases": normal_sample,
        "ambiguous_cases": ambiguous_sample,
        "case_order": sample,
        "cases": {
            cid: {
                "stratum": "ambiguous" if cid in ambiguous_sample else "normal",
                "baseline_start_ts": None,
                "baseline_elapsed_seconds": None,
                "guessed_root_cause": None,
                "evidence_requests_count": None,
                "notes": None,
                "scored": False,
                "correct": None,
                "review_start_ts": None,
                "review_elapsed_seconds": None,
            }
            for cid in sample
        },
    }
    save_state(state)
    return state


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def load_case_bundle(case_id: str) -> dict[str, Any]:
    case_dir = CORPUS_DIR / case_id
    narrative = json.loads((case_dir / "narrative.json").read_text())
    context = json.loads((case_dir / "context.json").read_text())
    label = json.loads((case_dir / "label.json").read_text())
    xml_path = case_dir / "saml_response.xml"
    saml_xml = xml_path.read_text() if xml_path.exists() else None
    check_results = json.loads((case_dir / "check_results.json").read_text())

    manifest = load_manifest()
    entry = manifest["cases"][case_id]
    har_note = "no HAR referenced for this case"
    har_ref = entry.get("har_ref")
    if har_ref:
        local_har = case_dir / "login.har"
        if local_har.exists():
            har_note = f"case-local HAR: corpus/cases/{case_id}/login.har (this case's fault changed the HAR bytes)"
        else:
            shared = manifest.get("shared_artifacts", {}).get(har_ref, {})
            shared_path = shared.get("path", har_ref)
            har_note = f"shared HAR (identical across most cases): {shared_path}"

    return {
        "narrative": narrative,
        "context": context,
        "label": label,
        "saml_xml": saml_xml,
        "check_results": check_results,
        "har_note": har_note,
    }


# --------------------------------------------------------------------------------- #
# Rendering helpers -- server-rendered HTML, no template engine, matching desk/api.py
# --------------------------------------------------------------------------------- #

STYLE = """
<style>
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; max-width: 920px;
         margin: 2rem auto; padding: 0 1.25rem; color: #1a1a1a; line-height: 1.45; }
  h1 { font-size: 1.4rem; }
  h2 { font-size: 1.1rem; margin-top: 1.6rem; border-bottom: 1px solid #ddd; padding-bottom: .3rem; }
  table { border-collapse: collapse; width: 100%; margin: .75rem 0; }
  th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #e4e4e4; font-size: .92rem; }
  th { background: #f6f6f6; }
  .pending { color: #a15c00; } .done { color: #1a7a3c; } .miss { color: #b3261e; }
  a { color: #1a56b0; }
  code, pre { background: #f4f4f4; border-radius: 4px; }
  pre { padding: .75rem; overflow-x: auto; font-size: .82rem; }
  .card { border: 1px solid #ddd; border-radius: 8px; padding: 1rem 1.25rem; margin: 1rem 0; }
  .timer { font-size: 2rem; font-variant-numeric: tabular-nums; }
  button, .btn { background: #1a56b0; color: white; border: none; border-radius: 6px;
        padding: .55rem 1rem; font-size: .95rem; cursor: pointer; text-decoration: none;
        display: inline-block; }
  button.secondary, .btn.secondary { background: #666; }
  select, input[type=number], textarea { font-size: .95rem; padding: .35rem; width: 100%;
        box-sizing: border-box; margin: .25rem 0 .75rem 0; }
  label { font-weight: 600; font-size: .9rem; }
  .note { background: #fff8e1; border: 1px solid #f0d98a; border-radius: 6px;
          padding: .6rem .9rem; font-size: .88rem; margin: .75rem 0; }
</style>
"""


def page(title: str, body: str) -> Response:
    return Response(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>{STYLE}</head><body>{body}</body></html>",
        mimetype="text/html",
    )


def fmt_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}m {s:02d}s"


@app.route("/")
def index() -> Response:
    state = init_state()
    rows = []
    for cid in state["case_order"]:
        c = state["cases"][cid]
        baseline_status = "done" if c["baseline_elapsed_seconds"] is not None else (
            "in progress" if c["baseline_start_ts"] is not None else "pending"
        )
        review_status = "done" if c["review_elapsed_seconds"] is not None else (
            "in progress" if c["review_start_ts"] is not None else "pending"
        )
        score = "-" if c["correct"] is None else ("hit" if c["correct"] else "MISS")
        cls = "done" if baseline_status == "done" else "pending"
        rows.append(
            f"<tr><td><a href='/case/{html.escape(cid)}'>{html.escape(cid)}</a></td>"
            f"<td>{c['stratum']}</td>"
            f"<td class='{cls}'>{baseline_status}</td>"
            f"<td>{fmt_seconds(c['baseline_elapsed_seconds'])}</td>"
            f"<td class='{'miss' if score == 'MISS' else ''}'>{score}</td>"
            f"<td>{review_status}</td>"
            f"<td>{fmt_seconds(c['review_elapsed_seconds'])}</td>"
            f"<td><a href='/review/{html.escape(cid)}'>time review</a></td></tr>"
        )
    body = f"""
    <h1>Human baseline study &mdash; Assertion Desk</h1>
    <div class="note"><strong>Sample deviation from protocol:</strong> {html.escape(state['protocol_deviation'])}</div>
    <p>This walks the {len(state['case_order'])} assigned cases (15 normal + {len(state['ambiguous_cases'])} ambiguous).
    Click a case ID to time it. Nothing about the expected answer is shown until after you submit
    your own hypothesis &mdash; see <a href="https://github.com/RasheedFarhat/assertion-desk/blob/main/docs/HUMAN_BASELINE.md">docs/HUMAN_BASELINE.md</a> for why.</p>
    <table>
      <tr><th>case</th><th>stratum</th><th>baseline</th><th>elapsed</th><th>score</th>
          <th>review</th><th>elapsed</th><th></th></tr>
      {''.join(rows)}
    </table>
    <p><a class="btn" href="/summary">View summary &amp; ROI command</a></p>
    """
    return page("Human baseline study", body)


@app.route("/case/<case_id>")
def case_view(case_id: str) -> Response:
    state = init_state()
    if case_id not in state["cases"]:
        return page("Unknown case", f"<p>{html.escape(case_id)} is not part of the sampled 17.</p>")
    c = state["cases"][case_id]
    bundle = load_case_bundle(case_id)
    narrative = bundle["narrative"]

    if c["baseline_elapsed_seconds"] is not None:
        # Already submitted -- send to the reveal page instead of re-showing the form.
        return redirect(url_for("case_reveal", case_id=case_id))

    context_rows = "".join(
        f"<tr><td>{html.escape(str(k))}</td><td><code>{html.escape(str(v))[:200]}</code></td></tr>"
        for k, v in bundle["context"].items()
    )
    xml_block = (
        f"<pre>{html.escape(bundle['saml_xml'])}</pre>"
        if bundle["saml_xml"]
        else "<p><em>No saml_response.xml on disk for this case (parse-failure case).</em></p>"
    )

    if c["baseline_start_ts"] is None:
        # Not started yet -- show the bundle and a Start button, no form.
        body = f"""
        <h1>{html.escape(case_id)}</h1>
        <p><a href="/">&larr; back</a></p>
        <div class="card">
          <h2>Customer narrative</h2>
          <p><strong>{html.escape(narrative.get('subject',''))}</strong></p>
          <p>{html.escape(narrative.get('body','')).replace(chr(10), '<br>')}</p>
        </div>
        <div class="card">
          <h2>SP-side configuration (context.json)</h2>
          <table>{context_rows}</table>
        </div>
        <div class="card">
          <h2>Artifact bundle</h2>
          <p>{html.escape(bundle['har_note'])}</p>
          <details><summary>saml_response.xml</summary>{xml_block}</details>
        </div>
        <form method="post" action="/case/{html.escape(case_id)}/start">
          <button type="submit">Start timer &mdash; begin working the case</button>
        </form>
        """
        return page(case_id, body)

    # Started, not yet submitted -- show a live clock and the answer form.
    body = f"""
    <h1>{html.escape(case_id)}</h1>
    <p class="timer" id="clock">0m 00s</p>
    <script>
      const start = {c['baseline_start_ts']};
      function tick() {{
        const elapsed = Math.floor(Date.now()/1000 - start);
        const m = Math.floor(elapsed/60), s = elapsed % 60;
        document.getElementById('clock').textContent = m + 'm ' + String(s).padStart(2,'0') + 's';
      }}
      tick(); setInterval(tick, 1000);
    </script>
    <div class="card">
      <h2>Customer narrative</h2>
      <p><strong>{html.escape(narrative.get('subject',''))}</strong></p>
      <p>{html.escape(narrative.get('body','')).replace(chr(10), '<br>')}</p>
    </div>
    <div class="card">
      <h2>SP-side configuration (context.json)</h2>
      <table>{context_rows}</table>
    </div>
    <div class="card">
      <h2>Artifact bundle</h2>
      <p>{html.escape(bundle['har_note'])}</p>
      <details><summary>saml_response.xml</summary>{xml_block}</details>
    </div>
    <div class="card">
      <h2>Your answer</h2>
      <form method="post" action="/case/{html.escape(case_id)}/submit">
        <label>Root cause hypothesis</label>
        <select name="guessed_root_cause">
          <option value="{NO_GUESS}">No diagnosis &mdash; I would request more evidence</option>
          {''.join(f'<option value="{html.escape(cid)}">{html.escape(cid)}</option>' for cid in known_check_ids())}
        </select>
        <label>How many separate times would you go back to the customer for more evidence?</label>
        <input type="number" name="evidence_requests_count" min="0" value="0">
        <label>Notes (optional, not scored)</label>
        <textarea name="notes" rows="3"></textarea>
        <button type="submit">Stop timer &amp; submit</button>
      </form>
    </div>
    """
    return page(case_id, body)


@app.route("/case/<case_id>/start", methods=["POST"])
def case_start(case_id: str) -> Response:
    state = init_state()
    c = state["cases"].get(case_id)
    if c is None:
        return redirect(url_for("index"))
    if c["baseline_start_ts"] is None:
        c["baseline_start_ts"] = time.time()
        save_state(state)
    return redirect(url_for("case_view", case_id=case_id))


@app.route("/case/<case_id>/submit", methods=["POST"])
def case_submit(case_id: str) -> Response:
    state = init_state()
    c = state["cases"].get(case_id)
    if c is None or c["baseline_start_ts"] is None:
        return redirect(url_for("index"))
    if c["baseline_elapsed_seconds"] is None:
        elapsed = time.time() - c["baseline_start_ts"]
        c["baseline_elapsed_seconds"] = round(elapsed, 1)
        c["guessed_root_cause"] = request.form.get("guessed_root_cause", NO_GUESS)
        try:
            c["evidence_requests_count"] = int(request.form.get("evidence_requests_count", 0))
        except ValueError:
            c["evidence_requests_count"] = 0
        c["notes"] = request.form.get("notes", "") or None

        bundle = load_case_bundle(case_id)
        expected = bundle["label"].get("expected_root_cause")
        if expected is None:
            c["correct"] = c["guessed_root_cause"] == NO_GUESS
        else:
            c["correct"] = c["guessed_root_cause"] == expected
        c["scored"] = True
        save_state(state)
    return redirect(url_for("case_reveal", case_id=case_id))


@app.route("/case/<case_id>/reveal")
def case_reveal(case_id: str) -> Response:
    state = init_state()
    c = state["cases"].get(case_id)
    if c is None or not c["scored"]:
        return redirect(url_for("case_view", case_id=case_id))
    bundle = load_case_bundle(case_id)
    label = bundle["label"]
    checks = bundle["check_results"].get("results") or []
    check_rows = "".join(
        f"<tr><td>{html.escape(r['check_id'])}</td><td>{html.escape(r['assurance'])}</td>"
        f"<td>{html.escape(str(r.get('reason',''))[:160])}</td></tr>"
        for r in checks
    )
    verdict = "Correct" if c["correct"] else "Miss"
    verdict_cls = "done" if c["correct"] else "miss"
    guess_display = "No diagnosis / requested evidence" if c["guessed_root_cause"] == NO_GUESS else c["guessed_root_cause"]
    body = f"""
    <h1>{html.escape(case_id)} &mdash; scored</h1>
    <p><a href="/">&larr; back to dashboard</a></p>
    <div class="card">
      <p><strong>Your time:</strong> {fmt_seconds(c['baseline_elapsed_seconds'])}
         &nbsp;|&nbsp; <strong>Your guess:</strong> {html.escape(str(guess_display))}
         &nbsp;|&nbsp; <strong>Evidence requests you'd need:</strong> {c['evidence_requests_count']}</p>
      <p class="{verdict_cls}"><strong>{verdict}</strong></p>
      <p><strong>Expected root cause:</strong> {html.escape(str(label.get('expected_root_cause')))}
         &nbsp;|&nbsp; <strong>Expected disposition:</strong> {html.escape(str(label.get('expected_disposition')))}</p>
    </div>
    <div class="card">
      <h2>Full check results (the system's answer key)</h2>
      <table><tr><th>check</th><th>assurance</th><th>reason</th></tr>{check_rows}</table>
    </div>
    <p><a class="btn secondary" href="/review/{html.escape(case_id)}">Now time the review step &rarr;</a></p>
    """
    return page(f"{case_id} scored", body)


@app.route("/review/<case_id>")
def review_view(case_id: str) -> Response:
    state = init_state()
    c = state["cases"].get(case_id)
    if c is None:
        return redirect(url_for("index"))

    if c["review_elapsed_seconds"] is not None:
        body = f"""
        <h1>{html.escape(case_id)} &mdash; review already timed</h1>
        <p>Review time recorded: {fmt_seconds(c['review_elapsed_seconds'])}</p>
        <p><a href="/">&larr; back</a></p>
        """
        return page(case_id, body)

    if c["review_start_ts"] is None:
        body = f"""
        <h1>Time the review step: {html.escape(case_id)}</h1>
        <p><a href="/">&larr; back</a></p>
        <div class="note">
          Per docs/HUMAN_BASELINE.md step 4, this times only the human-review step under
          the real system, not its own latency: reading the case card and clicking approve
          or override. Run these two commands in another terminal first, then open the
          printed URL before starting this clock:
        </div>
        <pre>make serve   # in one terminal
curl -s -X POST http://127.0.0.1:5050/cases \\
  -H 'Content-Type: application/json' \\
  -d '{{"corpus_case":"{html.escape(case_id)}"}}' | python3 -m json.tool
# open http://127.0.0.1:5050/cases/&lt;id&gt;/card</pre>
        <form method="post" action="/review/{html.escape(case_id)}/start">
          <button type="submit">Start review timer</button>
        </form>
        """
        return page(case_id, body)

    body = f"""
    <h1>Reviewing: {html.escape(case_id)}</h1>
    <p class="timer" id="clock">0m 00s</p>
    <script>
      const start = {c['review_start_ts']};
      function tick() {{
        const elapsed = Math.floor(Date.now()/1000 - start);
        const m = Math.floor(elapsed/60), s = elapsed % 60;
        document.getElementById('clock').textContent = m + 'm ' + String(s).padStart(2,'0') + 's';
      }}
      tick(); setInterval(tick, 1000);
    </script>
    <p>Stop the clock the moment you would click approve or override on the case card.</p>
    <form method="post" action="/review/{html.escape(case_id)}/stop">
      <button type="submit">Stop review timer</button>
    </form>
    """
    return page(case_id, body)


@app.route("/review/<case_id>/start", methods=["POST"])
def review_start(case_id: str) -> Response:
    state = init_state()
    c = state["cases"].get(case_id)
    if c is not None and c["review_start_ts"] is None:
        c["review_start_ts"] = time.time()
        save_state(state)
    return redirect(url_for("review_view", case_id=case_id))


@app.route("/review/<case_id>/stop", methods=["POST"])
def review_stop(case_id: str) -> Response:
    state = init_state()
    c = state["cases"].get(case_id)
    if c is not None and c["review_start_ts"] is not None and c["review_elapsed_seconds"] is None:
        c["review_elapsed_seconds"] = round(time.time() - c["review_start_ts"], 1)
        save_state(state)
    return redirect(url_for("index"))


@app.route("/summary")
def summary() -> Response:
    state = init_state()
    baseline_minutes = [
        c["baseline_elapsed_seconds"] / 60.0
        for c in state["cases"].values()
        if c["baseline_elapsed_seconds"] is not None
    ]
    review_minutes = [
        c["review_elapsed_seconds"] / 60.0
        for c in state["cases"].values()
        if c["review_elapsed_seconds"] is not None
    ]
    hits = sum(1 for c in state["cases"].values() if c["correct"] is True)
    scored = sum(1 for c in state["cases"].values() if c["scored"])
    total = len(state["case_order"])

    def stats_block(label: str, xs: list[float]) -> str:
        if not xs:
            return f"<p><strong>{label}:</strong> no cases timed yet.</p>"
        return (
            f"<p><strong>{label}</strong> (n={len(xs)}): "
            f"mean {statistics.mean(xs):.1f} min, min {min(xs):.1f}, max {max(xs):.1f}</p>"
        )

    roi_cmd = ""
    if baseline_minutes and review_minutes:
        roi_cmd = (
            f"python3 -m eval.roi --baseline-minutes {statistics.mean(baseline_minutes):.1f} "
            f"--review-minutes {statistics.mean(review_minutes):.1f}"
        )

    complete = scored == total and len(review_minutes) == total
    gen_block = (
        f"""<form method="post" action="/generate-results-doc">
              <button type="submit">Write docs/HUMAN_BASELINE_RESULTS.md</button>
            </form>"""
        if complete
        else f"<p class='pending'>{scored}/{total} baseline timings and {len(review_minutes)}/{total} "
             f"review timings recorded. All {total} of each are required before generating the results "
             f"doc &mdash; matching eval/roi.py's own refusal to run on partial input.</p>"
    )

    body = f"""
    <h1>Summary</h1>
    <p><a href="/">&larr; back</a></p>
    <div class="card">
      <p>Root-cause accuracy so far: {hits}/{scored} scored ({total} assigned)</p>
      {stats_block('Baseline (manual) minutes', baseline_minutes)}
      {stats_block('Review minutes', review_minutes)}
    </div>
    <div class="card">
      <h2>ROI calculator command</h2>
      {'<pre>' + html.escape(roi_cmd) + '</pre>' if roi_cmd else '<p>Need at least one timed case in each column.</p>'}
    </div>
    <div class="card">
      <h2>Write the results file</h2>
      {gen_block}
    </div>
    """
    return page("Summary", body)


@app.route("/generate-results-doc", methods=["POST"])
def generate_results_doc() -> Response:
    state = init_state()
    total = len(state["case_order"])
    scored = sum(1 for c in state["cases"].values() if c["scored"])
    reviewed = sum(1 for c in state["cases"].values() if c["review_elapsed_seconds"] is not None)
    if scored != total or reviewed != total:
        return redirect(url_for("summary"))

    baseline_minutes = [c["baseline_elapsed_seconds"] / 60.0 for c in state["cases"].values()]
    review_minutes = [c["review_elapsed_seconds"] / 60.0 for c in state["cases"].values()]
    hits = sum(1 for c in state["cases"].values() if c["correct"] is True)

    from datetime import date

    lines = [
        "# Human Baseline Study Results",
        "",
        f"**Run on {date.today().isoformat()}. n={total}.**",
        "",
        (
            "Rasheed is not a professional SSO support engineer, so this baseline is a "
            "conservative, directional estimate of a specialist's time, not an industry "
            "benchmark. See docs/HUMAN_BASELINE.md for the protocol."
        ),
        "",
        (
            f"**Sample deviation:** {state['protocol_deviation']}"
        ),
        "",
        "## Aggregate",
        "",
        f"- Root-cause accuracy: {hits}/{total}",
        f"- Baseline (manual) minutes: mean {statistics.mean(baseline_minutes):.1f}, "
        f"min {min(baseline_minutes):.1f}, max {max(baseline_minutes):.1f}",
        f"- Review minutes: mean {statistics.mean(review_minutes):.1f}, "
        f"min {min(review_minutes):.1f}, max {max(review_minutes):.1f}",
        "",
        f"```\npython3 -m eval.roi --baseline-minutes {statistics.mean(baseline_minutes):.1f} "
        f"--review-minutes {statistics.mean(review_minutes):.1f}\n```",
        "",
        "## Per-case",
        "",
        "| case | stratum | baseline min | guess | correct | evidence requests | review min |",
        "|---|---|---:|---|---|---:|---:|",
    ]
    for cid in state["case_order"]:
        c = state["cases"][cid]
        guess = "no diagnosis" if c["guessed_root_cause"] == NO_GUESS else c["guessed_root_cause"]
        lines.append(
            f"| {cid} | {c['stratum']} | {c['baseline_elapsed_seconds']/60.0:.1f} | {guess} | "
            f"{'yes' if c['correct'] else 'no'} | {c['evidence_requests_count']} | "
            f"{c['review_elapsed_seconds']/60.0:.1f} |"
        )
    lines.append("")

    RESULTS_MD_PATH.write_text("\n".join(lines))
    return redirect(url_for("summary"))


if __name__ == "__main__":
    init_state()
    app.run(host="127.0.0.1", port=5151, debug=False)
