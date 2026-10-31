# basseparate — local bass practice studio
#
# Every target is offline. `make doctor` explains the machine, `make bootstrap`
# prepares it from the preserved local assets, `make gate` is the local gate.
# Python work uses the preserved .venv; the harness script is stdlib-only.

SHELL := /bin/bash
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
STUDIO := $(PY) scripts/studio.py

.DEFAULT_GOAL := help
.PHONY: help doctor bootstrap dev build test e2e gate gate-lite fix fixtures demo

help: ## Show this target list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

doctor: ## Report toolchain, assets, Vamp plugin pack, Piper, model bundle and GPU
	@$(STUDIO) doctor

bootstrap: ## Offline, idempotent setup: python env, web links, fixtures
	@$(STUDIO) bootstrap

dev: ## Run the UI dev server and the local API server
	@$(STUDIO) dev

build: ## Compile Python and build the production UI when sources exist
	@$(STUDIO) build

test: ## Run Python and web test suites (empty suites are reported, not failed)
	@$(STUDIO) test

e2e: ## Run the Playwright end-to-end suite when specs exist
	@$(STUDIO) e2e

gate: ## Full local gate: lint, format, types, fixtures, tests, build, e2e
	@$(STUDIO) gate

gate-lite: ## Fast gate: lint, format, types, fixtures, tests
	@$(STUDIO) gate --lite

fix: ## Apply automatic formatting and lint fixes
	@$(STUDIO) fix

fixtures: ## Write the deterministic audio fixtures
	@$(STUDIO) fixtures

demo: ## List the demo fixtures and the next steps
	@$(STUDIO) demo
