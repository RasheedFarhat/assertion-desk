SHELL := /bin/bash
PYTHON := .venv/bin/python3
TIMESTAMP := $(shell date -u +%Y%m%dT%H%M%SZ)

.PHONY: help test verify policy case custody ground reason pipeline api corpus-verify \
        corpus eval eval-replay demo serve

help:
	@echo "Assertion Desk -- available targets:"
	@echo "  make test           full pytest suite (desk/, eval/, harness/)"
	@echo "  make verify         desk/verify's ~20 SAML checks (tests/verify/)"
	@echo "  make policy         desk/policy's disposition rule table (tests/policy/)"
	@echo "  make case           desk/case's state machine, trace, store (tests/case/)"
	@echo "  make custody        desk/custody's secret/PII quarantine (tests/custody/)"
	@echo "  make ground         desk/ground's grounding validator (tests/ground/)"
	@echo "  make reason         desk/reason's fixture/live/fallback cascade (tests/reason/)"
	@echo "  make pipeline       desk/pipeline's verify->reason->ground sequence (tests/pipeline/)"
	@echo "  make api            desk/api.py's Flask endpoints and case card (tests/api/)"
	@echo "  make corpus-verify  corpus/MANIFEST.json checksums + fault->check label sanity"
	@echo "  make corpus         regenerate the frozen corpus (needs Keycloak + Playwright)"
	@echo "  make eval           live corpus run (Gemini, falls back to Ollama/deterministic)"
	@echo "  make eval-replay    corpus run from fixtures only -- no network, no API key, \$$0"
	@echo "  make demo           CLI walkthrough of 5 illustrative cases (see target for caveat)"
	@echo "  make serve          run desk/api.py's dev server on http://127.0.0.1:5050"
	@echo ""
	@echo "Note (2026-08-17): desk/api.py now exists (POST /cases, case state machine over"
	@echo "HTTP, and a server-rendered /cases/<id>/card). 'make demo' is still a CLI-only"
	@echo "walkthrough of the eval corpus, not the case-card experience -- run 'make serve'"
	@echo "and open a card in a browser for that. n8n (plan section 17) is still not wired."

# --------------------------------------------------------------------------------- #
# Test suites -- one target per package, matching the doc precedent in
# docs/PHASE1_NOTES.md and docs/PHASE4_NOTES.md ("pytest tests/<pkg>/ -v").
# --------------------------------------------------------------------------------- #

test:
	$(PYTHON) -m pytest tests/ -q

verify:
	$(PYTHON) -m pytest tests/verify/ -v

policy:
	$(PYTHON) -m pytest tests/policy/ -v

case:
	$(PYTHON) -m pytest tests/case/ -v

custody:
	$(PYTHON) -m pytest tests/custody/ -v

ground:
	$(PYTHON) -m pytest tests/ground/ -v

reason:
	$(PYTHON) -m pytest tests/reason/ -v

pipeline:
	$(PYTHON) -m pytest tests/pipeline/ -v

api:
	$(PYTHON) -m pytest tests/api/ -v

# corpus/MANIFEST.json's own checksums plus label sanity (every fault ID maps to a
# check that can detect it) -- plan's own Verification section item 1, "make
# corpus-verify". This is a pytest module, not a standalone script; skips cleanly
# with a clear message if the corpus hasn't been generated yet.
corpus-verify:
	$(PYTHON) -m pytest tests/harness/ -v

# --------------------------------------------------------------------------------- #
# Corpus regeneration and evaluation
# --------------------------------------------------------------------------------- #

# Regenerates corpus/cases/ and corpus/MANIFEST.json from scratch by driving a real
# Keycloak login through Playwright and injecting each fault. Unlike every other
# target in this file, this one has a real infrastructure dependency: Keycloak must
# be up first (`docker compose --profile idp up -d`, per compose.yaml). Running the
# already-committed corpus, verifying it, and evaluating against it (the targets
# above and below) never needs this.
corpus:
	@echo "corpus regeneration needs Keycloak running: docker compose --profile idp up -d"
	@echo "(the committed corpus/ is already frozen -- only run this to regenerate it)"
	$(PYTHON) -m harness.generate

# Live run: Gemini primary, Ollama fallback, deterministic-only as the last resort
# (plan section 16's cascade). Costs money only past the Gemini free tier, and $0 for
# any case whose exact prompt is already cached in fixtures/.
eval:
	$(PYTHON) -m eval.run --out-dir eval/runs/$(TIMESTAMP)
	$(PYTHON) -m eval.report eval/runs/$(TIMESTAMP)/records.json \
		--out eval/runs/$(TIMESTAMP)/report.md \
		--metrics-out eval/runs/$(TIMESTAMP)/metrics.json
	@echo "report: eval/runs/$(TIMESTAMP)/report.md"

# The key reproducibility check (plan section 23 and the plan's own Verification
# item 5): every case served from fixtures/, no network, no GEMINI_API_KEY, $0,
# byte-identical output run to run. Raises ReplayMiss on any case not already cached.
eval-replay:
	$(PYTHON) -m eval.run --replay-only --out-dir eval/runs/$(TIMESTAMP)-replay
	$(PYTHON) -m eval.report eval/runs/$(TIMESTAMP)-replay/records.json \
		--out eval/runs/$(TIMESTAMP)-replay/report.md \
		--metrics-out eval/runs/$(TIMESTAMP)-replay/metrics.json
	@echo "report: eval/runs/$(TIMESTAMP)-replay/report.md"

# --------------------------------------------------------------------------------- #
# Demo
# --------------------------------------------------------------------------------- #

# Honest scope note: the plan's section 13 demo is a 90-second recording of a
# server-rendered case card. desk/api.py exists now (POST /cases through the real
# case state machine, GET /cases/<id>/card), so that experience is reachable via
# `make serve` -- but n8n (plan section 17: intake webhook, approval send-and-wait,
# evidence chase, nightly eval report) is still not wired, so there is no scripted
# webhook-to-approval walkthrough yet. This target remains a CLI-only stand-in: it
# runs 5 fixture-covered cases in replay-only mode -- no network, no API key, $0 --
# chosen to show one of each outcome shape the eval framework distinguishes:
#   cert_expired                         clean single-fault root cause
#   duplicate_role_attributes            conflicting evidence -> review_required
#   withheld_clock                       missing evidence -> precise evidence request
#   negative_control                     nothing wrong -> correct refusal
#   cert_rotation__adv_s1_direct_override  injection attempt in an artifact field
demo:
	@echo "=================================================================="
	@echo "Assertion Desk demo (CLI walkthrough of the eval corpus -- for the"
	@echo "server-rendered case card, run 'make serve' and open a card's URL)"
	@echo "=================================================================="
	$(PYTHON) -m eval.run --replay-only \
		--case cert_expired \
		--case duplicate_role_attributes \
		--case withheld_clock \
		--case negative_control \
		--case cert_rotation__adv_s1_direct_override \
		--out-dir eval/runs/demo_$(TIMESTAMP)
	$(PYTHON) -m eval.report eval/runs/demo_$(TIMESTAMP)/records.json \
		--out eval/runs/demo_$(TIMESTAMP)/report.md \
		--metrics-out eval/runs/demo_$(TIMESTAMP)/metrics.json
	@echo ""
	@echo "5 cases: clean diagnosis, conflicting evidence, missing evidence,"
	@echo "negative control, and one injection attempt -- read the report:"
	@echo "  eval/runs/demo_$(TIMESTAMP)/report.md"

# --------------------------------------------------------------------------------- #
# Live server
# --------------------------------------------------------------------------------- #

# desk/api.py's dev server. Port 5050, not 5000 -- macOS's AirPlay Receiver squats on
# 5000 by default. In-memory SQLite unless DESK_DB_PATH points at a file. This is a
# Flask dev server, not a production WSGI target, and desk/api.py's own docstring
# says so; nothing here claims otherwise. POST a case, then open the printed URL:
#   curl -s -X POST localhost:5050/cases -H 'content-type: application/json' \
#     -d '{"corpus_case": "cert_expired"}' | python3 -m json.tool
#   open http://127.0.0.1:5050/cases/<id>/card
serve:
	$(PYTHON) -m desk.api
