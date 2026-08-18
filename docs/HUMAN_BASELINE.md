# Human Baseline Study

**Status: not yet run.** This document is the protocol, not the result. Plan section 24
requires this to come from Rasheed's own hands-on, stopwatch-timed work against real cases,
and no other source is acceptable. Nothing in this repository fabricates or estimates the
numbers this study produces. `eval/roi.py` enforces that structurally: `--baseline-minutes`
and `--review-minutes` have no default and the calculator refuses to run without them.

## Why it has to be him, by hand

The whole thesis of this project is that a claim only ships once something independently
confirmed it. The one claim nothing in the codebase can confirm is how long the manual
version of this work actually takes a person. A model cannot time itself doing what a human
support engineer does with a HAR viewer, `openssl`, and a text editor, and an invented number
would be exactly the kind of unverified assertion `desk/ground` exists to reject if the model
tried to make it. The honest move is to run the study, not to estimate around not having run it.

## Published context, not a substitute input

Three external figures are worth knowing while reading this document, and none of
them may be used in place of `--baseline-minutes` or `--review-minutes`. Each measures
a different population than a single hands-on SAML/SSO diagnosis, and none is
SAML-federation-specific:

- General IT ticket handling averages **63 minutes per ticket** across 10,900 users
  and 400+ companies, with only 54.3% resolved in a single pass
  ([Unthread, 2026](https://unthread.io/blog/support-ticket-resolution-statistics/)).
  This spans every ticket type and includes wait and reassignment time, not isolated
  hands-on diagnosis minutes.
- Root-cause identification specifically runs **30 to 90 minutes with traditional
  tooling**, versus 5 to 15 minutes with AI-assisted observability
  ([OpenObserve MTTR guide, 2026](https://openobserve.ai/blog/mean-time-to-resolution-mttr-guide/)).
  This is general SRE/observability incident data, not identity federation. It happens
  to bracket this project's own unverified plan-stage estimate of 45-55 minutes
  (plan section 14), which is a useful sanity check, not corroboration.
- A clean Entra ID SAML *integration* (new tenant, admin access both sides) takes 1 to
  4 hours of joint work, and a self-test page cuts new-tenant support time 60-80%
  ([Scalekit SAML debugging handbook, 2026](https://www.scalekit.com/blog/saml-debugging-handbook-2026-how-to-diagnose-log-and-resolve-sso-failures)).
  That is initial onboarding, not break/fix diagnosis on an already-working
  integration, so it is not comparable to this study's cases either.

These numbers motivate why the problem is worth solving. They cannot answer the one
question this study exists to answer, which is how long *this specific diagnostic
workflow* takes a person's hands, because nobody has published that number and every
adjacent figure measures a different task. `eval/roi.py` still refuses to run without
a real timed input for exactly this reason; nothing above changes that.

## What to do

1. **Pick the 20 cases.** A stratified random sample: 15 from the `normal` stratum, 5 from
   `ambiguous`, drawn from `corpus/cases/` (checked against `corpus/MANIFEST.json` so the case
   IDs are real and unmodified). Write the 20 case IDs down before starting, so the sample
   cannot be quietly cherry-picked after seeing which ones go fast.
2. **For each case, in order, with a real stopwatch:**
   - Start the clock when you open the case's artifact bundle.
   - Work it the way a support engineer would with no tool built for this: open the HAR in a
     viewer, find the SSO POST, base64-decode the SAMLResponse, pretty-print the XML, compare
     the fields that matter against the tenant's expected config, check the certificate with
     `openssl x509 -fingerprint -sha256`, form a hypothesis, write the reply.
   - Stop the clock when you would hit send.
   - Record: case ID, elapsed minutes, your stated root cause, and how many separate times you
     would have had to go back to the customer for more evidence.
3. **Score yourself against the label**, not from memory. `corpus/cases/<case_id>/` carries an
   `expected_root_cause` and `expected_disposition`; compare after you have already committed
   to an answer, not before.
4. **Run the same 20 cases through the system** (`make eval-replay` with `--case` repeated, or
   `make demo` for a few of them) and separately time only the human review step: reading the
   case card and clicking approve or override. That is `--review-minutes`, and plan section 24
   item 2 is explicit that this, not the system's own latency, is the number that matters.
5. **Feed both into the calculator:**
   ```
   python3 -m eval.roi --baseline-minutes <mean of your 20 times> --review-minutes <mean review time>
   ```
6. **Report the limitation in the same sentence as the result**, per plan section 24's own
   rule: Rasheed is not a professional SSO support engineer, so this baseline is a conservative,
   directional estimate of a specialist's time, not an industry benchmark. State n=20 every
   time the number is quoted.

## What not to do

Do not average in a case you gave up on without finishing it, do not redo a case after seeing
the answer, and do not swap in an easier case if one runs long. If a case takes 90 minutes,
that is the data. Report the full spread (min, max, mean), not just the mean, so a reader can
see how much the number moves.

## Recording the result

Once run, the raw per-case timings belong in a new `docs/HUMAN_BASELINE_RESULTS.md` (or a
committed CSV alongside it) with the date it was run and the exact 20 case IDs, so it is
reproducible in the same spirit as `eval/runs/20260817T044253Z`: a stranger should be able to
see exactly which 20 cases produced the number, not just the number.
