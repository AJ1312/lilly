# Lilly 2.0 Release Baseline

This file records the current reproducible commands, not historical 1.x
measurements.

```sh
make check
make web
make release-check
PYTHONPATH=src .venv/bin/python benchmarks/cua_benchmark.py
```

The current local audit passed the Python suite at 83.09% coverage and passed
Ruff, strict mypy, Bandit, vulture, deptry, frontend lint/tests/build and the
wheel gate. GitHub CI repeats the release, web and Python gates on macOS and
Ubuntu with Python 3.12 and 3.13.

The CUA benchmark reports observation, grounding, action, fresh-frame and
verification timings. It is a deterministic contract benchmark, not a claim
that every third-party desktop application or provider has been validated.
