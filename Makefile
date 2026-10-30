# FairPool Makefile. Run from the repository root.
SHELL := /usr/bin/bash
.DEFAULT_GOAL := help

ifeq ($(OS),Windows_NT)
VENV_BIN := Scripts
else
UNAME_S := $(shell uname -s)
ifeq ($(findstring MINGW,$(UNAME_S)),MINGW)
VENV_BIN := Scripts
else
VENV_BIN := bin
endif
endif

PY := .venv/$(VENV_BIN)/python
PIP := .venv/$(VENV_BIN)/pip
PIP_COMPILE := .venv/$(VENV_BIN)/pip-compile
PYTHON ?= python
GITLEAKS ?= gitleaks
GRADE ?=

.PHONY: help setup lock lint typecheck test test-sandbox test-sandbox-interactive test-faults ai-eval imports docs-check openapi-check sdk secrets verify gate-check dev migrate db-reset search-reindex demo-seed demo-reset

help:
	@echo "setup lock lint typecheck test imports docs-check openapi-check secrets verify gate-check"

setup:
	@$(PYTHON) -c "import sys; assert sys.version_info[:2] == (3, 12), f'Python 3.12 required, got {sys.version.split()[0]}'"
	@test -d .venv || $(PYTHON) -m venv .venv
	@$(PY) -m pip install --upgrade pip
	@if [ -f backend/requirements-dev.lock ]; then \
		$(PIP) install --require-hashes -r backend/requirements-dev.lock; \
	else \
		$(PIP) install -e "backend[dev]"; \
	fi
	@$(PIP) install --no-deps -e backend
	@$(PY) -m pre_commit install
	@if [ -f frontend/package.json ]; then \
		node -e "const major=+process.version.slice(1).split('.')[0]; if (major < 20) { console.error('Node >= 20 is required'); process.exit(1); }"; \
		cd frontend && npm ci; \
	else \
		echo "SKIP: frontend dependencies (frontend/ appears in T01B03)"; \
	fi

lock:
	@$(PIP) install pip-tools
	@cd backend && ../$(PIP_COMPILE) requirements.in -o requirements.lock --generate-hashes --allow-unsafe
	@cd backend && ../$(PIP_COMPILE) requirements-dev.in -o requirements-dev.lock --generate-hashes --allow-unsafe

lint:
	@$(PY) -m ruff check backend tools
	@$(PY) -m ruff format --check backend tools
	@if [ -f frontend/package.json ]; then cd frontend && npm run lint; else echo "SKIP: frontend lint (T01B03)"; fi

typecheck:
	@$(PY) -m mypy --strict backend/src/fairpool/domain backend/src/fairpool/modules
	@if [ -f frontend/package.json ]; then cd frontend && npm run typecheck; else echo "SKIP: frontend typecheck (T01B03)"; fi

test:
	@if [ -f backend/src/fairpool/domain/hashing.py ]; then \
		$(PY) -m pytest backend/tests -m "not sandbox and not sandbox_interactive and not faults and not ai_eval" --cov=fairpool.domain --cov-fail-under=90; \
	else \
		$(PY) -m pytest backend/tests -m "not sandbox and not sandbox_interactive and not faults and not ai_eval"; \
	fi
	@if [ -f frontend/package.json ]; then cd frontend && npm test; else echo "SKIP: frontend tests (T01B03)"; fi

test-sandbox:
	@$(PY) -m pytest backend/tests/contract_sandbox -m sandbox

test-sandbox-interactive:
	@$(PY) -m pytest backend/tests/contract_sandbox -m sandbox_interactive

test-faults:
	@$(PY) -m pytest backend/tests/faults -m faults

ai-eval:
	@$(PY) -m pytest backend/tests/ai_eval -m ai_eval

imports:
	@if [ -f tools/check_imports.py ]; then $(PY) tools/check_imports.py; else echo "SKIP: tools/check_imports.py (T00A04)"; fi

docs-check:
	@$(PY) tools/validate_docs.py

openapi-check:
	@if [ -f tools/export_merchant_openapi.py ]; then $(PY) tools/export_merchant_openapi.py --check; else echo "SKIP: tools/export_merchant_openapi.py (T00A04)"; fi

sdk:
	@echo "SKIP: SDK generation starts at T03B05/T10A04"

secrets:
	@if [ ! -f .gitleaks.toml ]; then echo "SKIP: gitleaks config (T00A02)"; exit 0; fi; \
	GITLEAKS_BIN="$(GITLEAKS)"; \
	if ! command -v "$$GITLEAKS_BIN" >/dev/null 2>&1; then \
		GITLEAKS_BIN="$$(find "$$LOCALAPPDATA/Microsoft/WinGet/Packages" -maxdepth 2 -name gitleaks.exe -print -quit 2>/dev/null)"; \
	fi; \
	if [ -z "$$GITLEAKS_BIN" ]; then echo "gitleaks not found: winget install Gitleaks.Gitleaks"; exit 1; fi; \
	"$$GITLEAKS_BIN" git --redact

verify: lint typecheck test imports docs-check openapi-check secrets

gate-check: verify
	@if [ "$(GATE)" = "ig-1" ]; then \
		$(PY) -m alembic -c backend/alembic.ini upgrade head; \
		$(PY) -m alembic -c backend/alembic.ini check; \
		cd frontend && npm run build && cd ..; \
		echo "IT-1 manual: hosted /health + /ready, webhook POST + stored row, contract tests, port fakes, S2 O1/O2, S6"; \
	else \
		echo "IT-0 manual checks: tags, spike records, plugin versions, secrets rotation, graph outputs"; \
	fi

dev:
	@docker compose --env-file .env -f deploy/docker-compose.yml up --build

migrate:
	@$(PY) -m alembic -c backend/alembic.ini upgrade head

db-reset:
	@$(PY) -m alembic -c backend/alembic.ini downgrade base
	@$(PY) -m alembic -c backend/alembic.ini upgrade head

search-reindex:
	@echo "SKIP: search indexing starts at T03B02"

demo-seed:
	@echo "SKIP: demo seed starts at T04B02"

demo-reset:
	@echo "SKIP: demo reset starts at T04B02"
