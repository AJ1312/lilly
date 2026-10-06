# Verification

## Automated release gate

Run from the repository root:

```sh
make check
make web
make release-check
PYTHONPATH=src .venv/bin/python benchmarks/cua_benchmark.py
```

`make check` runs Ruff, strict mypy, Bandit, vulture, deptry, the Python
suite with the 82% coverage floor, and the frontend Vitest suite. `make web`
runs npm install, oxlint, TypeScript and the production Vite build. The release
gate validates launchers and that the wheel contains the Python package and
compiled interface.

The latest audited run passed with 1,897 Python tests, 27 skips, 83.09%
coverage, one frontend test file, and all six GitHub CI jobs green. Counts are
informational; the commands above are the gate.

## Covered behavior

The suite includes policy and approval modes, model fallback and quota
handling, Laya fallback and typed routing, intent classification, capability
discovery, sensitive context compaction, AgentLoop execution, browser/CDP
guards, ComputerRuntime stale-frame and verification behavior, DevBox
persistence, task restart/re-drive, SessionRuntime persistence, API auth,
MCP, memory, notes, routines, streaming and the task event API.

## Real-machine checks

The following require the target machine or external account and are not
pretended to be covered by CI:

- macOS Screen Recording and Accessibility permissions, pointer/keyboard
  actions and real desktop screenshots;
- a real Chrome-family browser profile and real interactive website;
- a real Docker or Podman engine for DevBox;
- real provider keys, quotas, Gemini Live or another live multimodal provider;
- the Laya model download and load on the target CPU/GPU;
- real Telegram, Tailscale and phone access.

The automated CUA benchmark is reproducible without those services and tests
the observation/action/verification contract with deterministic adapters. A
real-machine smoke test should be run after installation before enabling
computer control for unattended work.

## Security review

Bandit, strict typing, dependency checks, import-boundary tests, policy tests,
secret handling, SSRF checks, stale-state rejection and approval payload
binding are release gates. Warnings from Bandit are documented annotations,
not suppressed failures.
