# basseparate — local bass practice studio
#
# Every target is offline. `make doctor` explains the machine, `make bootstrap`
# prepares it from the preserved local assets, `make gate` is the local gate.
# Python work uses the preserved .venv; the harness script is stdlib-only.

SHELL := /bin/bash
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
STUDIO := $(PY) scripts/studio.py

.DEFAULT_GOAL := help
.PHONY: help doctor bootstrap install-tools install-model models-list models-install models-verify \
	htdemucs_ft scnet-xl-ihf bs-roformer-sw dev dev-smoke build build-web test test-backend test-web \
	test-separation e2e accept gate gate-lite analysis-check fix fixtures demo

# The second make goal is the model id for `make models-install <id>`.
MODEL_GOAL := $(word 2,$(MAKECMDGOALS))
MODEL_NAMES := htdemucs_ft scnet-xl-ihf bs-roformer-sw

help: ## Show this target list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'

doctor: ## Report toolchain, assets, Vamp plugin pack, Piper, model bundle and GPU
	@$(STUDIO) doctor

bootstrap: ## Offline, idempotent setup: python env, web links, fixtures
	@$(STUDIO) bootstrap

install-tools: ## Fetch pinned Vamp/Piper tools; add ACCEPT_MODEL_TERMS=1 for weights
	@$(PY) scripts/install_tools.py $(if $(ACCEPT_MODEL_TERMS),--accept-model-terms,)

install-model: ## Fetch the htdemucs_ft weights after accepting their research terms
	@$(PY) scripts/install_tools.py --accept-model-terms --skip-tools

models-list: ## List separation models and installed/missing state (no network)
	@$(PY) scripts/models.py list

models-install: ## Install a model: ID=<id> or `make models-install <id>`
	@$(PY) scripts/models.py install $(or $(ID),$(MODEL_GOAL))

models-install-%: ## Install a model by id suffix (models-install-<id>)
	@$(PY) scripts/models.py install $*

models-verify: ## Verify installed model files by size and sha256 (no network)
	@$(PY) scripts/models.py verify

$(MODEL_NAMES):
	@:

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

analysis-check: ## Check Vamp plugin pack, Piper server, native host and model bundle
	@$(STUDIO) analysis-check

fix: ## Apply automatic formatting and lint fixes
	@$(STUDIO) fix

fixtures: ## Write the deterministic audio fixtures
	@$(STUDIO) fixtures

demo: ## List the demo fixtures and the next steps
	@$(STUDIO) demo
