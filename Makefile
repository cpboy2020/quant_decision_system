PYTHON ?= python3
VENV ?= .venv
PYTEST_OPTS ?= -v --tb=short
COV_OPTS ?= --cov=. --cov-report=term-missing --cov-report=html
MYPY_OPTS ?= --ignore-missing-imports --show-error-codes
BANDIT_OPTS ?= -ll --exclude .venv,tests

.PHONY: help venv install install-dev lint type-check security test test-cov qa backtest run-sim clean

help:
	@echo "📦 量化系统开发工具 | make [test|qa|backtest|run-sim]"

venv:
	$(PYTHON) -m venv $(VENV)

install-dev: venv
	$(VENV)/bin/pip install -q -r requirements/dev.txt

lint:
	$(VENV)/bin/ruff check . --fix --exit-zero
	$(VENV)/bin/ruff format . --check

type-check:
	$(VENV)/bin/mypy . $(MYPY_OPTS)

security:
	$(VENV)/bin/bandit -r . $(BANDIT_OPTS) -f json -o bandit-report.json || true

test:
	$(VENV)/bin/python -m pytest tests/ $(PYTEST_OPTS)

test-cov:
	$(VENV)/bin/python -m pytest tests/ $(PYTEST_OPTS) $(COV_OPTS)

qa: lint type-check security test-cov

backtest:
	$(VENV)/bin/python scripts/backtest_runner.py --mode mc --days 300

run-sim:
	$(VENV)/bin/python main.py --mode paper --env development

clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov/ bandit-report.json 2>/dev/null || true
