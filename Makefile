SHELL := /bin/bash
VENV  := venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

.PHONY: all setup test lint clean clean-pyc clean-test clean-db clean-all

all: setup

# ── Setup ────────────────────────────────────────────────────────────────

setup: $(VENV)/bin/activate

$(VENV)/bin/activate: requirements.txt
	python3 -m venv $(VENV)
	$(PIP) install -r requirements.txt
	touch $(VENV)/bin/activate

# ── Tests ────────────────────────────────────────────────────────────────

test:
	$(PYTHON) -m pytest tests/ -v --cov=app --cov-report=term --cov-report=html:coverage_html

test-quick:
	$(PYTHON) -m pytest tests/ -v --cov=app --cov-report=term

# ── Lint ─────────────────────────────────────────────────────────────────

lint:
	$(VENV)/bin/ruff check app/ tests/

lint-fix:
	$(VENV)/bin/ruff check --fix app/ tests/

format:
	$(VENV)/bin/ruff format app/ tests/

# ── Clean ────────────────────────────────────────────────────────────────

clean-pyc:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	find . -type f -name '*.pyo' -delete
	find . -type f -name '*~' -delete

clean-test:
	rm -rf .pytest_cache
	rm -rf coverage_html
	rm -f .coverage

clean-db:
	rm -f sitechecker.db

clean: clean-pyc clean-test
	@echo "Cleaned Python caches and test artifacts."

clean-all: clean clean-db
	@echo "Cleaned everything including database."

# ── Migrations ───────────────────────────────────────────────────────────

migrate:
	$(PYTHON) -m alembic upgrade head

migrate-create:
	$(PYTHON) -m alembic revision --autogenerate -m "$(message)"
