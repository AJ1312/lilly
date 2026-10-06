# One command for every check.
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: help install test lint types sec dead deps web web-test release-check check run clean

help:
	@echo "make install   install Lilly and the dev tools into the current environment"
	@echo "make test      run the tests"
	@echo "make lint      ruff"
	@echo "make types     mypy --strict"
	@echo "make sec       bandit"
	@echo "make dead      vulture: unused code"
	@echo "make deps      deptry: unused or missing dependencies"
	@echo "make web       rebuild the interface (needs Node 20+; output goes to src/lilly/web)"
	@echo "make web-test  run web test suite (vitest)"
	@echo "make release-check  validate launchers and the installable wheel"
	@echo "make check     lint + types + sec + test + web-test"
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

web-test:
	cd web && npm test

release-check:
	@set -eu; \
	for script in install.sh uninstall.sh "Install Lilly.command"; do bash -n "$$script"; done; \
	tmp="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp"' EXIT; \
	$(PY) -m pip wheel --no-deps --no-build-isolation --wheel-dir "$$tmp" . >/dev/null; \
	wheel="$$(find "$$tmp" -maxdepth 1 -name '*.whl' -print -quit)"; \
	test -n "$$wheel"; \
	$(PY) -c 'import sys, zipfile; names = set(zipfile.ZipFile(sys.argv[1]).namelist()); assert any(n.startswith("lilly/") and n.endswith("__init__.py") for n in names); assert "lilly/web/index.html" in names; assert any(n.startswith("lilly/web/assets/") for n in names)' "$$wheel"

check: lint types sec dead deps test web-test
	@echo "all checks passed"

run:
	$(PY) -m lilly run

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
