# Lilly 2.0 Baseline Measurements

Measured on 2026-10-05 on macOS Darwin x86_64, Python 3.12.13, Node v26.3.1.

## 1. Test Suite & Checks Baseline (`make check`)

```
1703 passed, 27 skipped in 148.2s
Required test coverage of 82.0% reached. Total coverage: 87.4%
all checks passed
```

- Total tests: 1,730 (1,703 passed, 27 skipped)
- Linter: Ruff (clean)
- Types: mypy `--strict` (clean)
- Security: Bandit (clean)
- Dead code: Vulture (clean)
- Dependencies: Deptry (clean)
- Web tests: Vitest (1 passed)

## 2. Web Bundle Metrics

- Directory size (`du -sh src/lilly/web`): `540K`
- Production JS bundle: `src/lilly/web/assets/index-BS7j0uFM.js`
  - Uncompressed: `369,647 bytes`
  - Gzip compressed: `110,861 bytes` (108.26 KiB)

## 3. Rate Limit & Capacity Reproduction (`tests/perf/repro_ratelimit.py`)

Command: `.venv/bin/python tests/perf/repro_ratelimit.py`

Output:
```
=== Lilly Rate Limit & Capacity Baseline Reproduction ===

Running Scenario A (24 calls across 3 providers with rpm=5)...
Scenario A result: completed=15, failed=9, elapsed=0.012s
Distribution: {'model-a': 5, 'model-b': 5, 'model-c': 5}
Exceptions: {'NoModelAvailable: every model is busy, over quota or down: try again shortly': 9}

Running Scenario B (Provider answers 429 Retry-After: 2 s)...
model model-rate-limited failed: rate limited by the provider
Scenario B result: outcome=QuotaExhausted, elapsed=0.0011s
Error: (False, 2.0, 429)

Running Scenario C (30 calls with 3 models in list order)...
Scenario C distribution: {'model-1': 30}
```

### Analysis of Baseline Failures
1. **Scenario A (Rate limit ends task instead of waiting)**:
   24 concurrent calls over 3 providers (rpm=5 each) immediately hit per-minute limits. 15 succeeded, and 9 failed instantly after 0.012s with `NoModelAvailable`. Tasks terminate rather than waiting.
2. **Scenario B (429 is never retried)**:
   When a provider returns HTTP 429 with `Retry-After: 2`, Lilly maps this to `QuotaExhausted(retryable=False)`. The call fails without waiting, and the next call sends no request.
3. **Scenario C (No load balancing)**:
   All 30 calls land on the first model in list order (`model-1`: 30, `model-2`: 0, `model-3`: 0).
