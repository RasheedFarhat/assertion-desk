SHELL := /bin/bash
PYTHON := .venv/bin/python3
TIMESTAMP := $(shell date -u +%Y%m%dT%H%M%SZ)

.PHONY: help test verify policy case custody ground reason pipeline corpus-verify \
        corpus eval eval-replay demo

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
	@echo "  make corpus-verify  corpus/MANIFEST.json checksums + fault->check label sanity"
	@echo "  make corpus         regenerate the frozen corpus (needs Keycloak + Playwright)"
	@echo "  make eval           live corpus run (Gemini, falls back to Ollama/deterministic)"
	@echo "  make eval-replay    corpus run from fixtures only -- no network, no API key, \$$0"
	@echo "  make demo           CLI walkthrough of 5 illustrative cases (see target for caveat)"
	@echo ""
	@echo "Note (2026-08-17): desk/api.py and the server-rendered case card (plan section 22)"
	@echo "do not exist yet. 'make demo' is an honest stand-in, not the real demo experience."

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
# server-rendered case card (desk/api.py), which has not been built yet (Phase 5/6).
# This target is a CLI stand-in, not that demo. It runs 5 fixture-covered cases in
# replay-only mode -- no network, no API key, $0 -- chosen to show one of each
# outcome shape the eval framework distinguishes:
#   cert_expired                         clean single-fault root cause
#   duplicate_role_attributes            conflicting evidence -> review_required
#   withheld_clock                       missing evidence -> precise evidence request
#   negative_control                     nothing wrong -> correct refusal
#   cert_rotation__adv_s1_direct_override  injection attempt in an artifact field
demo:
	@echo "=================================================================="
	@echo "Assertion Desk demo (CLI stand-in -- desk/api.py's case card does"
	@echo "not exist yet; this is not the plan's section 13 demo experience)"
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
