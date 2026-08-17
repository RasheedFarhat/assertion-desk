# n8n workflows

Four workflow exports, per plan section 17: `wf1-intake.json`, `wf2-approval.json`,
`wf3-evidence-chase.json`, `wf4-eval-report.json`. n8n is the wire, the clock, and the
doorbell here. It is not the brain.

## What n8n does

- **WF1 (intake):** receives an HMAC-verified webhook, calls `POST /cases`, and routes on the
  resulting `disposition` (`review_required` -> WF2, `awaiting_evidence` -> left for WF3's own
  poll, `escalate` -> a security notification, anything else -> a documented no-op).
- **WF2 (approval gate):** calls `POST /cases/{id}/post-for-review`, waits for a human decision
  via Gmail send-and-wait, and records the decision via `POST /cases/{id}/decision`. Never
  auto-approves on timeout; escalates instead.
- **WF3 (evidence chase):** polls `GET /cases?state=awaiting_evidence` every 4 hours and, for
  cases with an approved, ready draft, sends the missing-evidence request. See "What WF3 does
  not do" below before assuming this closes any loop.
- **WF4 (nightly evaluation report):** runs `make eval-replay`, diffs the result against a
  committed baseline, and notifies on regression. See "What WF4 needs that this repo's default
  Compose profile does not provide" below.

## What n8n does not do

All parsing, cryptographic verification, secret classification, prompt construction, schema
validation, grounding, policy decisions, persistence, and evaluation logic stay in `desk/` and
`eval/`, not in n8n. If a piece of logic needs a unit test, it does not belong in one of these
JSON files. `make demo` and `make eval*` run end to end with n8n stopped; nothing in this
repo's test suite depends on n8n running. That is a deliberate design choice, not an oversight
-- it is the difference between orchestration and the system itself.

## What WF3 does not do

The original plan draft assumed WF3 would receive the customer's reply and call something like
`POST /cases/{id}/artifacts` to re-ingest it, then transition the case back to `verifying`.
Reading the actual code changed that:

- `desk/api.py`'s own module docstring says `/cases/<id>/artifacts` does not exist. There is no
  live artifact intake for a chased reply to feed.
- `desk/case/state.py`'s transition table confirms `awaiting_evidence -> verifying` is the only
  legal outgoing edge from `awaiting_evidence` (a source comment attributes it to "WF3"), so the
  destination state is real and intended -- but nothing in the current API can drive a case
  there.

**WF3 therefore stops after sending the evidence request.** Closing the loop is real, named
future work, not something faked here with an endpoint that does not exist. Until it is built, a
human has to notice the customer's reply and get the case back into the pipeline by hand.

Two more gaps discovered while building WF3, each documented in-canvas at the node it affects:

- `GET /cases/{id}`'s `detail` field (which carries Job B's drafted subject/body and the check
  gap list) comes from an **in-process cache**, not durable storage -- the handler's own comment
  says it is null after a process restart or for a case that predates the current process. WF3
  escalates to a human rather than guess at a missing-evidence request when this happens.
- Nothing in desk's data model has a customer-contact field (checked: no
  `customer_email`/`contact_email`/`reporter_email` anywhere in the repo), and `mocks/itsm/` is
  still an empty directory, so there is no ticket system to post a reply into either. Plan
  section 30 says Gmail here targets his own account for the demo only, never a real customer --
  WF3's customer-facing send follows that rule and targets a configurable demo address, not
  something extracted from the case.

WF3's approval step is also weaker than WF2's for a structural reason, not a shortcut: an
`awaiting_evidence` case cannot legally transition to `human_review` (see above), so it cannot
be routed through `post-for-review` the way WF2 is. WF3 still puts a human between the draft and
the send via its own Gmail send-and-wait, but that approval is recorded only in n8n's own
execution history, not in desk's `Approval` table -- there is no endpoint to record it there.

## What WF4 needs that this repo's default Compose profile does not provide

`make eval-replay` needs this repository checked out plus `.venv/bin/python3` (the Makefile's
own `PYTHON` variable) on the machine that runs it. n8n's Execute Command node runs inside n8n's
own process/container, and `compose.yaml`'s `orchestration` profile is the stock
`docker.n8n.io/n8nio/n8n` image with no repo bind-mount -- deliberately, since mounting the repo
plus a full Python/make toolchain (or the Docker socket, to exec into `app` instead) into that
container is a real complexity and security cost this project is not paying just to make one
nightly job look more finished than it is.

To actually run WF4: run n8n directly on a host that already has this repo checked out and its
`.venv` provisioned (not the containerized `orchestration` profile), and point
`DESK_REPO_PATH` at the checkout. A dedicated runner service with its own HTTP endpoint desk/api.py
could call instead is a reasonable future direction, but that endpoint does not exist today.

WF4 also compares against `eval/baselines/metrics.json`, which is currently an **empty
directory** -- no baseline has been committed yet. The workflow treats a missing baseline as
"nothing to compare" rather than an error, and does not silently write the first run as the new
baseline (that would let a real regression quietly become normal). Committing a baseline is a
deliberate, human decision, not something this workflow does on its own.

`eval/`'s data model has no `MetricsHistory` table (plan section 19 does not define one, and
`desk/api.py` has no endpoint for one), so "append to a metrics history table" is implemented as
one JSON line per run appended to `eval/runs/history.jsonl` -- a real, working substitute that
does not invent a database write path nothing else in this repo has.

## Environment variables the workflows read

| Variable | Used by | Default |
|---|---|---|
| `DESK_API_BASE_URL` | WF1, WF2, WF3 | `http://app:5050` (the `app` service in `compose.yaml`) |
| `DESK_WEBHOOK_SECRET` | WF1 | none -- required, the webhook is rejected without it |
| `DESK_WF2_WORKFLOW_ID` | WF1 | none -- required to trigger WF2 via Execute Workflow |
| `DESK_ANALYST_ALIAS` | WF2, WF3, WF4 | `analyst@example.com` |
| `DESK_SECURITY_ALIAS` | WF1, WF2 | `security@example.com` |
| `DESK_CUSTOMER_CONTACT_DEMO` | WF3 | `demo-customer@example.com` -- see "What WF3 does not do" |
| `DESK_REPO_PATH` | WF4 | `/repo` -- see the deployment-prerequisite note above |

## Credentials

Every Gmail node uses a placeholder credential ID (`PLACEHOLDER_CREDENTIAL_ID`). Importing these
workflows into a real n8n instance requires creating a Gmail OAuth2 credential named "Assertion
Desk Gmail (demo account only)" and re-pointing each node at it. Per plan section 30, this is
meant to run against Rasheed's own account for demo purposes -- not a real customer inbox, not a
real support alias.

## Importing and running

1. `docker compose --profile core --profile orchestration up -d` (add `--profile idp` if the
   corpus's Keycloak-backed cases are in play).
2. Open n8n at `http://localhost:5678`, create the Gmail credential above, and import all four
   JSON files.
3. Set the environment variables in the table above (n8n's own `.env` or the `n8n` service's
   `environment:` block in `compose.yaml`).
4. Activate WF2, WF3, and WF4 (WF1 needs its webhook URL wired into whatever sends the intake
   POST -- a real ticketing system in production, `curl` for a demo).
5. Confirm the system still works with all of this stopped: `docker compose stop n8n && make
   demo`. If that fails, something drifted into depending on n8n, which contradicts the design
   this file describes.
