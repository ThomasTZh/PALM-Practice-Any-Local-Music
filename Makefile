# basseparate — local bass practice studio
#
# Every target is offline. `make doctor` explains the machine, `make bootstrap`
# prepares it from the preserved local assets, `make gate` is the local gate.
# Python work uses the preserved .venv; the harness script is stdlib-only.

SHELL := /bin/bash
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
STUDIO := $(PY) scripts/studio.py

.DEFAULT_GOAL := help
.PHONY: help doctor bootstrap dev dev-smoke build build-web test test-backend test-web \
	test-separation e2e accept gate gate-lite analysis-check analysis-timing fix fixtures demo

help: ## Show this target list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

doctor: ## Report toolchain, assets, Vamp plugin pack, Piper, model bundle and GPU
	@$(STUDIO) doctor

bootstrap: ## Offline, idempotent setup: python env, web links, fixtures
	@$(STUDIO) bootstrap

dev: ## Run the UI dev server and the local API server
	@$(STUDIO) dev

dev-smoke: ## Start the server, fetch /api/health and /, stop it (scratch data root)
	@$(STUDIO) dev-smoke

build: ## Compile Python and build the production UI when sources exist
	@$(STUDIO) build

build-web: ## Typecheck and build the UI only
	@$(STUDIO) build-web

test: ## Run Python and web test suites (empty suites are reported, not failed)
	@$(STUDIO) test

test-backend: ## Fixture check + backend pytest; TESTS="paths" scopes it
	@$(STUDIO) test-backend $(if $(TESTS),-- $(TESTS))

test-web: ## Run the Vitest suite only
	@$(STUDIO) test-web

test-separation: ## Real Demucs stem tests (slow, opt-in); TESTS="paths" scopes it
	@$(STUDIO) test-separation $(if $(TESTS),-- $(TESTS))

e2e: ## Run the Playwright end-to-end suite when specs exist
	@$(STUDIO) e2e

accept: ## Run the five-recording acceptance report (scripts/accept.py)
	@$(STUDIO) accept

gate: ## Full local gate: lint, format, types, fixtures, tests, build, e2e
	@$(STUDIO) gate

gate-lite: ## Fast gate: lint, format, types, fixtures, tests
	@$(STUDIO) gate --lite

analysis-check: ## Check Vamp/Piper assets, lint, types and the analysis test suites
	@$(STUDIO) analysis-check
	@$(PY) -m ruff check src/basseparate/piper.py src/basseparate/features.py \
		scripts/analysis_timing.py tests/unit/test_piper.py \
		tests/unit/test_piper_features.py tests/integration/test_analysis.py
	@$(PY) -m ruff format --check src/basseparate/piper.py src/basseparate/features.py \
		scripts/analysis_timing.py tests/unit/test_piper.py \
		tests/unit/test_piper_features.py tests/integration/test_analysis.py
	@$(PY) -m mypy src/basseparate/piper.py src/basseparate/features.py
	@$(PY) -m pytest -q tests/unit/test_piper.py tests/unit/test_piper_features.py \
		tests/integration/test_analysis.py

analysis-timing: ## Measure cold analysis of the preserved five-minute recording
	@$(PY) scripts/analysis_timing.py

fix: ## Apply automatic formatting and lint fixes
	@$(STUDIO) fix

fixtures: ## Write the deterministic audio fixtures
	@$(STUDIO) fixtures

demo: ## List the demo fixtures and the next steps
	@$(STUDIO) demo
