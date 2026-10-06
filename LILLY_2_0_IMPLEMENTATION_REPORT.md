# Lilly 2.0 Implementation Status

This is the current implementation record for Lilly 2.0. The source of truth
for runtime behavior is the code and test suite; this document summarizes the
boundaries and verification status without describing a second design.

## Complete runtime

- `SessionRuntime` is created once by `Runtime`, persists session state, records
  lifecycle/events/artifacts/routing, and is wired to task submission,
  cancellation, completion and failure.
- `AgentLoop` is the normal interactive execution loop.
- `System1Engine` exposes typed Laya choices for classification, complexity,
  model tier, capability, tool family and verification, with deterministic
  fallback when Laya is unavailable.
- `ModelBroker` owns model capability, health, quota, latency, cost and
  fallback selection for each model call.
- Tool visibility is the complete policy-filtered capability catalog. Namespace
  discovery is lazy; ranked advice cannot hide a required capability.
- `mode="plan"` and `providers.router.ModelRouter` remain deprecated,
  explicitly isolated compatibility surfaces only.

## Computer and execution

`ComputerRuntime` maintains persistent task-scoped observations with frame IDs,
screenshots, macOS accessibility data, browser DOM metadata, window state and
DevBox state. It supports semantic grounding, visual grounding injection,
coordinate fallback, pointer movement, clicks, typing, key presses, scrolling
and drag operations. Actions reject stale observations and record fresh-state
verification/recovery events.

DevBox is persistent and isolated: no network, constrained resources, fixed
mounts, no ambient engine socket and deterministic cleanup on timeout, cancel,
Stop all and shutdown.

## User experience

The interface is a task-first workspace: tasks, live progress, approvals,
computer/browser state, results, artifacts and an expandable advanced trace
share one API/event source. First launch uses a resumable setup wizard for
identity, models, Laya, permissions, computer/browser, DevBox, approval mode,
notifications, health and readiness. Pets are presentation state only.

## Verification

The repository gates currently pass with Python 3.12/3.13 on macOS/Linux,
frontend lint/test/build, static/security/dependency checks and wheel/release
validation. The exact commands and known real-device limitations are recorded
in [`docs/VERIFICATION.md`](docs/VERIFICATION.md).
