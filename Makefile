# One command for every check.
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: help install test lint types sec dead deps web check run clean

help:
	@echo "make install   install Lilly and the dev tools into the current environment"
	@echo "make test      run the tests"
	@echo "make lint      ruff"
	@echo "make types     mypy --strict"
	@echo "make sec       bandit"
	@echo "make dead      vulture: unused code"
	@echo "make deps      deptry: unused or missing dependencies"
	@echo "make web       rebuild the interface (needs Node 20+; output goes to src/lilly/web)"
	@echo "make check     lint + types + sec + test"
	@echo "make run       run Lilly in this terminal"

install:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest --cov --cov-report=term:skip-covered

lint:
	$(PY) -m ruff check .

types:
	$(PY) -m mypy

sec:
	$(PY) -m bandit -q -c pyproject.toml -r src

dead:
	$(PY) -m vulture

deps:
	$(PY) -m deptry .

web:
	cd web && npm ci && npm run lint && npm run build

check: lint types sec dead deps test
	@echo "all checks passed"

run:
	$(PY) -m lilly run

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
