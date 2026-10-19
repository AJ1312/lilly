# Lilly — End-to-End Product Completion and Release-Quality Execution Brief

> **Audience:** An autonomous coding agent working in the `AJ1312/lilly` repository (for example, Claude Code, Codex, or another repository-aware coding agent).
>
> **Instruction:** Execute this brief against the actual current checkout. Do not merely summarize it, produce a plan, or claim work is complete after editing documentation. Inspect, implement, test, fix regressions, and leave the repository in the strongest verifiable state possible in this run.
>
> **Product goal:** Turn Lilly into a dependable, polished, local-first, open-source personal AI agent that users can install and use for real work. It should plan, act through tools, verify outcomes, recover from failures, preserve user control, and run without paid model APIs when configured for local models.

---

## 0. Non-negotiable operating rules

1. **Inspect before editing.** The source code, current branch, current tests, generated web assets, issue tracker, and current working tree are the source of truth—not this brief, a previous report, comments, or claims in a README.
2. **Do the work.** Do not stop after creating a plan or checklist. Implement the highest-priority fixes, run the relevant tests, fix failures introduced by your changes, and continue until every feasible release gate has been evaluated.
3. **Preserve user work.** Begin with `git status --short --branch`. Never reset, clean, stash, checkout over, or overwrite uncommitted user changes. Never use destructive Git commands. Do not commit, push, create a release, or alter remote issues without explicit authorization.
4. **No invented evidence.** Never claim a test passed unless you ran it and saw the exit status. Never claim real-machine behavior was verified when it was not. Distinguish code review, automated tests, live-provider tests, and manual checks.
5. **Do not promise literal bug-freedom.** The objective is zero known release-blocking defects, strong regression coverage, no known high-severity security findings left unresolved, and transparent disclosure of remaining uncertainty. Absolute bug-freedom cannot be proven.
6. **Prefer small, validated changes.** Reuse the current architecture when it is sound. Do not rewrite the project, swap its framework, or add dependencies merely for novelty. Every meaningful change must have a reason, test coverage, and a rollback-safe path.
7. **Keep security controls.** Do not disable approvals, path restrictions, SSRF protection, secret handling, audit logging, container isolation, CSRF/origin checks, or policy gates to make a demo pass. Fix the actual cause instead.
8. **No paid-service dependency for the core path.** Do not require an API key, paid cloud account, hosted database, telemetry service, proprietary model, or mandatory subscription for installation and local-only usage. Online APIs may be optional adapters.
9. **No fake product states.** Do not use mock task results, invented progress, fake model health, placeholder interactions, or hard-coded success messages in production UI. Demo fixtures must be explicit and confined to tests/demo mode.
10. **Do not leak user data.** Do not upload source, databases, logs, prompts, credentials, screenshots, or user task data to external services. Never print secrets. Keep real provider and desktop tests opt-in and sanitized.
11. **Finish safely when blocked.** If a step requires access unavailable in the environment (macOS Accessibility, an installed browser, a Docker/Podman daemon, a live provider key), complete all deterministic work, add/run appropriate mocks and contract tests, document the exact manual command/check needed, and do not pretend it ran.
12. **Keep the product honest.** If a capability is partial, platform-limited, or provider-dependent, accurately label it as such in UI and docs. Do not claim parity with another agent without evidence.

## 1. Definition of success

Lilly is considered release-ready only when the following are true or a specific, honest blocker is recorded:

### Install and first run
- A new user can install Lilly on every platform that the project claims to support, using documented commands, without `sudo` and without hand-editing source.
- A first-run user can understand requirements, select a local model or optional hosted model, grant access deliberately, and complete a first task.
- `lilly doctor` identifies actionable setup problems without modifying user data unexpectedly.
- Upgrade and uninstall behavior are documented and tested; upgrades preserve settings, credentials, memory, and task history, and uninstall clearly states which data remains or is deleted.

### Core task execution
- Tasks have durable lifecycle state, progress, bounded retries, cancellation, failure explanations, and an inspectable final result.
- The system never reports success solely because a model said that a task succeeded. Each action and overall task must be verified using appropriate observations, assertions, file checks, or structured result checks.
- Mutating side effects are not silently repeated after timeout, restart, reconnect, or retry. Where exactly-once behavior cannot be guaranteed, document the at-least-once boundary and use idempotency/duplicate detection or require approval.
- Long-running tasks survive expected restarts safely, or fail to an explicit recoverable state rather than becoming stuck or being marked complete incorrectly.
- Tool failures, provider failures, quota exhaustion, browser failures, denied permissions, and timeouts are visible to the user in plain language with a next action.

### Local-first and cost
- A fully local configuration works with a supported local provider, without a hosted model API key.
- A clearly named **Local only** privacy mode, if implemented, rejects unintended remote model or tool destinations at the execution boundary—not merely in UI settings.
- The app explains that “local model” does not automatically mean “all network access disabled”: web search and external sites are separate capabilities and require clear controls.
- No mandatory analytics or hidden telemetry are added.
- Free hosted tiers are described as optional and subject to the providers’ limits and policies; never promise that hosted free tiers are permanent or unlimited.

### Security and data integrity
- Critical security invariants are enforced centrally and covered by adversarial tests.
- Secrets are never inserted into model context, logs, task artifacts, browser-visible URLs unnecessarily, or repository fixtures.
- Tool invocations are validated against registered schemas, authorized permissions, current path scopes, and the exact approved payload immediately before execution.
- Hostile web content, model output, skills, MCP responses, and inbound chat messages are treated as untrusted data.
- Backups, database migrations, export, restore, task cancellation, and shutdown preserve integrity under expected failure conditions.

### UI/UX
- Every visible control does what it says, including stop/cancel, approval, retry, open result, settings save, model test, routine controls, export/backup, and navigation.
- UI states are clear: loading, ready, empty, working, waiting for approval, blocked, failed, cancelled, completed, offline, and partially configured.
- Keyboard, screen-reader semantics, focus behavior, contrast, reduced motion, and responsive layouts are tested where applicable.
- No horizontal overflow, clipped modal actions, inaccessible dialogs, dead-end empty states, fake activity, unexplained technical error dumps, or silent destructive actions remain in supported layouts.
- The built frontend shipped in the Python package matches the actual frontend source.

### Release evidence
- All repository quality gates are run and green, or the precise failures are triaged and fixed where feasible.
- A clean wheel/package install and launch are tested in a fresh environment.
- Each supported platform has an explicit verification status; untested real-device paths are not represented as verified.
- The license, dependency licenses, model licenses, platform requirements, privacy behavior, known limitations, upgrade path, and uninstall semantics are documented.

## 2. Repository baseline: mandatory first pass

Before changing code, execute and record results for the following:

```bash
git status --short --branch
git branch --show-current
git log -8 --oneline --decorate
git ls-files
```

Then inspect the actual current state of:

- `README.md`
- `pyproject.toml`
- `Makefile`
- `.gitignore`
- `.github/workflows/ci.yml`
- `install.sh`, `Install Lilly.command`, and any uninstall/upgrade scripts
- `docs/ARCHITECTURE.md`
- `docs/SECURITY.md`
- `docs/SETUP.md`
- `docs/OPERATIONS.md`
- `docs/ROADMAP.md`
- `docs/VERIFICATION.md`
- `LILLY_2_0_IMPLEMENTATION_REPORT.md`
- source packages under `src/lilly/`
- frontend source under `web/` and generated frontend assets under `src/lilly/web/`
- tests and benchmarks
- license files, dependency/license metadata, and packaging configuration

Use `git ls-files` and a full recursive tree to establish the true path list. Do not assume a path exists because another file references it.

Inspect current remote state if authenticated access is available:

- Current open and closed issues and pull requests, including comments and failing checks.
- Latest commits on the default branch and whether the local checkout is up to date.
- Releases/tags and artifacts.
- CI runs and their actual results.

If remote access is unavailable, proceed locally and state that limitation. Do not infer that no bugs exist because there are no GitHub issues.

### Baseline commands

Use the project’s current documented gates. At minimum, evaluate:

```bash
make check
make web
make release-check
PYTHONPATH=src .venv/bin/python benchmarks/cua_benchmark.py
```

Also run the test subsets relevant to every component changed. Verify whether these commands are correct for the actual checkout before assuming their names or prerequisites.

**Important suspected baseline defects to validate, not blindly assume:**

1. The previously inspected tree contained root entries named `:memory:`, `:memory:-shm`, and `:memory:-wal`. Check whether these are still tracked and inspect their type/metadata safely. Never print their contents. Determine whether they are generated SQLite artifacts or meaningful data before removal. If they are runtime artifacts, remove them from the index/worktree in a safe, reviewed change, add matching ignore rules, and add a regression check so the files cannot be reintroduced.
2. The previously inspected `Makefile` had `release-check` run `bash -n` on `uninstall.sh`, while the previously inspected root listing did not show `uninstall.sh`. Confirm whether this mismatch still exists. If the script is absent, either implement a safe, tested uninstall script consistent with the documented semantics, or correct the gate and all documentation. Do not ship a broken release gate.
3. The previously inspected public repository had no release entries and returned an empty issue list. Recheck current state. Do not create a GitHub release or modify remote issues without explicit permission.
4. The previously inspected repository listing did not clearly surface a root `LICENSE`. Verify. If there is no license, resolve the open-source licensing gap deliberately; do not claim “open source” without an applicable license.
5. `README.md`/`docs/VERIFICATION.md` previously reported a large test suite and passing CI. Re-run actual gates and record real outputs rather than copying historical test counts.

Produce a private-to-the-work-session baseline summary before major edits; do not stop after that summary. Preserve any changes already present in the checkout.

## 3. Severity and prioritization

Use these priorities consistently in the work and in the final report:

- **P0 / release blocker:** likely data loss, secret disclosure, remote execution against user intent, broken installation/package/release gate, inability to use the basic product, or a false security/cost/privacy guarantee.
- **P1 / core-functionality blocker:** critical task paths fail, task completion is unverified, crashes or deadlocks occur in common usage, security checks lack enforcement, or a prominently advertised feature fails on a supported platform.
- **P2 / major product gap:** capability or UI flow makes common tasks unreliable, confusing, expensive, or incomplete, but a safe workaround exists.
- **P3 / polish:** low-impact UX inconsistency, documentation cleanup, minor performance/accessibility improvement.

Fix in this order: P0 → P1 → P2 → P3. If multiple P0 issues exist, prioritize safety/data loss first, then install/release integrity, then local-only/cost correctness.

## 4. Workstream A — repository hygiene and open-source readiness

### Required actions
- Remove only confirmed generated or accidental runtime artifacts from source control. Inspect file type, tracked state, and metadata; do not publish or dump any potential user data.
- Add robust ignore patterns for SQLite DB/WAL/SHM/journal files, logs, local config, keys, model downloads, browser profiles, local caches, compiled test output, and secret-bearing environment files without ignoring legitimate source or package assets.
- Add CI validation that fails if known local runtime databases, private credentials, key material, or large model artifacts are tracked. Keep rules narrow enough to avoid false positives on test fixtures.
- Ensure local runtime state belongs under the documented application data directory, not the repository root or current working directory.
- Check that settings, model keys, task history, memory, and logs have private permissions on supported platforms.
- Ensure install and update operations do not need administrator access and do not overwrite user data.
- Ensure uninstall prompts or clearly documents whether it removes the application only or also user data. Do not destroy user data by default.
- Verify the distribution includes the package, generated web assets, required runtime files, license, and documentation intended for end users.
- If licensing is absent, add an explicit, widely recognized OSI-approved license consistent with an open-source goal. Do not change any existing license. Prefer an explicit decision (including patent/attribution terms) over an ambiguous badge. Verify third-party code, dependencies, fonts/icons, model weights and model-download instructions have compatible terms; do not imply that model weights are bundled or licensed like Lilly’s code when they are not.
- Verify version source, package metadata, installed CLI version, and release tag agree.
- Ensure every referenced script/command/path exists. Every documented command should work in a clean supported environment or be clearly marked optional/platform-specific.

### Acceptance tests
- No unintended local database, secret, model cache, or browser profile is tracked.
- A clean source archive and wheel can be built.
- The wheel contains `lilly/__init__.py`, `lilly/web/index.html`, and hashed frontend assets, as intended by the packaging rules.
- `make release-check` passes on a clean checkout.
- Installer, upgrade, and uninstall do not lose user data silently and behave consistently with their docs.

## 5. Workstream B — task runtime correctness and autonomy

Inspect the full task lifecycle from UI/API submission through `Runtime`, orchestrator/runner, planning, agent loop, tool execution, event streaming, persistence, verification, completion, cancellation and restart. Follow the actual composition path; do not make isolated patches without tracing how data flows.

### Required behavior
- Every task has a stable identifier, explicit state transitions, timestamps, durable progress, clear cancellation semantics, and a terminal state (`completed`, `failed`, `cancelled`, etc.) that cannot be overwritten incorrectly by late work.
- Invalid transitions are rejected or safely normalized; duplicate client submissions are detected where practical.
- Each agent iteration is budget-bounded by steps, time, model calls/tokens where measurable, output sizes, tool sizes, and concurrency limits.
- Infinite loops, repetitive tool calls, empty model outputs, malformed tool calls, and repeated retries are caught and surfaced with actionable explanations.
- Only independent read-only steps may run concurrently. Mutating actions must be sequenced and serialized where they could conflict.
- Cancellation stops pending work, interrupts or safely finishes running operations where possible, closes browser/DevBox sessions, and leaves a coherent state. UI must not say “stopped” before stop is confirmed.
- Server restart and power/process interruption recover persisted tasks honestly. A task must not resume a potentially destructive operation blindly if the runtime cannot establish whether the previous operation succeeded.
- Retries use exponential/backoff limits for retryable provider/network failures; never retry permission denial, invalid input, or an irreversible action blindly.
- `Task success` is based on explicit verification, not a model’s self-report. Use artifact existence/content hashes, browser state/DOM, structured result predicates, provider response state, or appropriate domain checks.
- Final answers should identify artifacts produced, important actions taken, verification performed, and any incomplete steps. They should never imply unperformed work was completed.
- Event/log history survives refresh/restart and does not leak secrets. Large traces should be bounded or paginated rather than growing without limit.
- All tools are validated immediately before invocation: registered tool, JSON schema, agent permission, module enabled, scope/labels, current approval, payload binding, execution limits, and current settings that should apply to that operation.
- Approvals bind to the exact operation and are single-use and time-bounded. If permissions or important action parameters change while waiting, the old approval cannot authorize the changed action.
- Tool execution must not rely on a model-supplied tool name, risk, label, or permission. Those properties come from trusted code/registry and are checked at the boundary.

### Critical code-review targets
- `src/lilly/engine/runner.py`
- `src/lilly/engine/agent_loop.py`
- `src/lilly/engine/steps.py`
- `src/lilly/engine/lanes.py`
- `src/lilly/engine/orchestrator.py`
- `src/lilly/engine/session_runtime.py`
- `src/lilly/engine/verify.py`
- `src/lilly/engine/receipt.py`
- `src/lilly/domain/tasks.py`
- `src/lilly/domain/payload.py`
- `src/lilly/app/runtime.py`
- `src/lilly/store/`
- task, approval and event API modules in `src/lilly/ui/`

### Registry completeness
The previously inspected `src/lilly/engine/agent_loop.py` maintained hard-coded action-tool sets to determine which actions require new observations. Audit every mutating tool and every state-changing pathway. Prefer one trusted declarative contract in the tool registry (or a clear typed protocol) covering mutation, fresh-state verification, idempotency, approval, egress, sensitivity and serialization. If keeping separate declarations is technically necessary, add a completeness test that compares them against all registered tools and fails when any new mutation is unclassified.

### Acceptance tests
Add/extend integration tests for:
- task submit → tool → verify → result;
- approval pending → approve exact payload → execute once;
- approval payload or permissions change while waiting;
- cancellation during network call, tool execution and pending approval;
- server restart before, during and after a mutating operation;
- duplicate submission/retry and idempotency behavior;
- model quota exhausted, provider 429/5xx, invalid JSON, malformed tool arguments, context overflow, timeout and all-models-down;
- concurrent read steps and conflicting writes;
- empty result, partial completion and failed verification;
- event-stream disconnect/reconnect without duplicated or lost terminal state.

## 6. Workstream C — secure tools, browser, computer, code execution and integrations

Treat this workstream as safety-critical. Do not broaden access merely to make tests pass.

### Filesystem
- Review `src/lilly/domain/policy.py`, `src/lilly/tools/fs.py`, `PathScope`, protected paths and all file operations.
- Check path traversal, symlink swap races, case/Unicode variants, hard links where relevant, mount points, file replacement, permission changes, nonexistent parents, oversized/binary files and concurrent edits.
- Perform write/edit/move/trash operations atomically where possible. Verify rollback/undo hashes and report when recovery is impossible.
- Never follow an unchecked path after policy validation. Resolve and open via safe directory descriptors or equivalent robust primitives.
- Make shared-root boundaries and sensitive-path denials understandable in UI and docs.

### Web fetch and browser
- Review `src/lilly/tools/web.py`, `src/lilly/tools/browser/guard.py`, browser navigation, CDP/page code, downloads, redirects, DNS handling and remote debugging endpoints.
- Test IPv4/IPv6, IPv4-mapped IPv6, NAT64/6to4/Teredo, mixed public/private DNS answers, rebinding, unusual URL syntax, userinfo URLs, redirects to local/private endpoints, metadata IPs, non-HTTP schemes, huge/slow responses, downloads, popups, iframes, service workers and reused connections.
- Validate at the actual connection boundary. DNS validation followed by a separate uncontrolled resolution is not sufficient. Ensure redirects and subrequests are guarded; do not assume checking the first URL protects all requests.
- Keep the browser profile isolated from the user's normal profile and credentials unless a deliberate, visible, supported hand-off flow has been designed.
- Provide visible pause/hand-back behavior before sensitive login/payment/password/2FA actions. The user must be able to see the browser, take control, and return control explicitly. If not yet safely supported, disallow the action and state the limitation.
- Add screenshots/snapshots/DOM groundings that can be linked to the exact task step without leaking unrelated tabs or personal context.
- Support clear recovery from stale page elements, dialogs, closed tabs, download prompts and navigation errors.

### Computer control
- Review `src/lilly/tools/computer_runtime.py`, `src/lilly/tools/computer.py`, accessibility/AX adapters and platform-specific code.
- Require a fresh observation for actions that need one, reject stale screenshots/state, and verify after every meaningful state change.
- Check screen/window selection, monitor scaling, coordinate bounds, focus loss, permission denial, hotkeys, drag, typing, clipboard and multiple displays. Never assume macOS behavior works on Linux or vice versa.
- Add an explicit stop mechanism that is reachable outside the task view and immediately stops new actions.
- Keep dangerous/system settings actions behind strict policy and approval.
- Document per-platform limitations based on real test runs.

### DevBox / commands
- Review DevBox lifecycle, engine selection, container arguments, mounts, resource limits, network restrictions, cleanup and cancellation.
- Never mount the full home folder, Docker socket/Podman socket, host credentials or arbitrary host paths into the sandbox.
- Default to no network and one explicitly shared project folder, with CPU/memory/process/time limits and cleanup on Stop all/shutdown.
- Verify that user-provided command text is invoked without unsafe shell interpolation in Lilly’s host context. Do not allow a sandboxed process to escape by gaining engine sockets or writable host system mounts.
- If Docker/Podman is absent or broken, explain exactly how to fix it; do not quietly fall back to unsandboxed host execution.

### MCP and skills
- Review `src/lilly/tools/mcp*`, MCP store/manager, skill loading, agent extension points, manifests and settings.
- Treat server metadata, prompts, tool descriptions, schemas and results as untrusted. Enforce least privilege per server/tool, explicit connection review, network restrictions, bounded output, timeouts, authentication, and clear permissions.
- Make tool names unique and deterministic; reject collisions and invalid schemas. Test malicious server metadata and prompt injection via tool descriptions/results.
- Do not execute downloaded skills/extensions merely because an agent recommends them. Require review, integrity checks, isolation, explicit installation consent, version pinning and a rollback plan.

### Chat bridges and routines
- Review Telegram pairing, identity validation, rate limiting, replay protection, approval callbacks, task ownership, cancellation, and secret handling.
- Test forged/unlinked sender IDs, reused pairing codes, replayed callbacks, oversized messages, flood traffic, stale approvals, shutdown/reconnect, and tasks started by a bridge that lose authorization.
- Add no new messaging provider until authentication, signature/replay protection, rate limiting, permission semantics and privacy guarantees can be tested end-to-end.

### Acceptance tests
Use deterministic local fixtures for SSRF/DNS/redirect and malicious-page testing; mocked integrations for normal CI; opt-in live integrations only for smoke testing. Every known critical boundary needs regression tests. Record which tests are not executable in the current environment.

## 7. Workstream D — model provider reliability and genuinely local mode

Inspect `src/lilly/providers/`, `src/lilly/core/pool.py`, `src/lilly/core/capacity.py`, `src/lilly/providers/model_broker.py`, model settings, key store and model setup UI.

### Model broker requirements
- Provider capabilities must be tested from actual adapter behavior, not inferred solely from a model name. Distinguish tool use, vision, structured output, streaming, context size, reasoning constraints and image/file payload limits.
- Handle malformed responses, incomplete streaming, provider refusal, missing tool-call IDs, invalid schemas, tool-call loop errors, provider-specific token-limit fields, quota resets, 429/5xx, timeouts and context-window overflow predictably.
- Fallback only to models that meet the task’s capability and data-label requirements. Never silently downgrade to a model that is unable to perform the required action, or send private data to a less-trusted endpoint.
- Keep quota and retry behavior bounded and observable. Avoid “retry storms” and hidden extra requests.
- Respect per-model rate/token limits and accurately report estimates versus actual provider-reported usage. Do not state an exact cost when the provider supplies no reliable cost value.
- Provide a model diagnostic view that explains why a model is ineligible: no key, unreachable endpoint, missing capability, quota exhausted, privacy restriction, incompatible model schema or circuit breaker.
- Test key rotation/fallback without logging or exposing keys. Avoid unexpected cross-account or cross-provider data transmission.

### Local-only requirements
- Define local mode in one trusted setting and enforce it in the model broker/provider factory as well as egress policy. A UI toggle alone is not sufficient.
- In local-only mode reject non-local model specifications, public custom base URLs, hosted rerankers/embedders, remote MCP servers if not explicitly allowed, and remote LLM calls in auxiliary/quick/vision/research flows.
- Make the threat model explicit: permitting the browser or web search to access the internet is not “offline.” Offer separate controls for local inference, general network access, and web access.
- Default to a supported local runtime such as Ollama when configured by the user. Detect availability and show a plain-language model recommendation based on available memory/CPU/GPU and the model’s capabilities. Never download a very large model silently; show size, model license, hardware estimate and confirmation first.
- Add a no-key first-run path: the core app may install offline if dependencies are available; the truly local model path may need the model binary downloaded separately. Be precise about the difference.
- Verify network egress with an instrumented test transport/loopback capture in CI: local-only inference must never contact a hosted provider. Test all auxiliary model calls too (vision grounding, compression, planner, verifier, helper model).
- Tell users when a selected feature requires a hosted service and fail closed under local-only mode, rather than silently using it remotely.

### Licensing and costs
- Document that model weights and providers have their own licenses, acceptable-use rules and resource requirements. Never call the overall product “fully offline” if web access or remote integrations are enabled.
- Keep the app useful if all remote provider keys are absent and no hosted service is reachable.

## 8. Workstream E — memory, research, artifacts and reproducible results

### Memory
- Review the existing memory store/search and UI.
- Make retained facts user-visible, editable, attributable, searchable, exportable and deletable. Respect deletion across derived indexes/caches/backups according to documented retention rules.
- Store provenance (user-provided, inferred, tool result, imported), timestamp and scope where useful. Do not treat inferred details as certain facts.
- Prevent untrusted pages or tools from poisoning persistent memory without explicit review. Retrieval must honor sensitivity labels and task/agent access scope.
- Deduplicate equivalent entries, cap size, handle Unicode and empty/ambiguous queries gracefully, and test FTS/search behavior under malformed input.
- Provide “why was this remembered/used?” context and a clear memory-off option.

### Research and web answers
- Separate fetched evidence from model-authored synthesis. Preserve source URL, page title, retrieval timestamp, relevant excerpt/locator and any extraction failures.
- Support cross-source confirmation, contradictions, recency awareness, and an explicit “not verified” status. Never invent citations or claim a source supports a sentence it does not support.
- Treat all web content as untrusted. A page cannot authorize actions, change permissions or write memory simply through prompt text.
- Add tests for dead links, redirect chains, duplicate sources, same-domain over-weighting, content injection, changed pages, unsupported factual claims and missing source content.

### Artifacts and file outputs
- Create artifacts in an explicit task workspace, surface the path and verification status, and make opening/exporting easy.
- Verify generated files open/parse when formats permit, and explain limitations when they cannot be validated.
- Avoid overwriting existing files without preview and appropriate approval. Make undo/restore discoverable and test it.
- Use atomic temp-file writes, sensible size limits and deterministic naming.

## 9. Workstream F — high-quality UI/UX based on the real app

Do not invent a new design by writing a mock image or replacing the current UI wholesale. Inspect the actual frontend and use the product end-to-end. Keep the interface cohesive, simple, fast, readable and accessible.

### First pass: inspect every screen
Review source in `web/` and compare it to built files under `src/lilly/web/`. Map every route/screen and each primary user journey: first launch, model setup, new task, task running, approval, task blocked/failed/completed, open artifact, memory edit/delete, agent permissions, computer/browser enablement, MCP connection, routine create/pause/run, settings save, backup/export, recovery, and uninstall help.

Create a screen/control inventory. For each control, record: purpose, action, loading state, success state, failure state, permissions, keyboard behavior, and test. Any visible but nonfunctional element is a product defect.

### Design system
- Establish consistent design tokens for spacing, typography, radii, borders, shadows, focus rings, surfaces, danger/warning/success states and motion.
- Keep hierarchy obvious: the user’s task and status first, primary action next, details/technical trace on demand.
- Avoid turning every section into a colorful card. Use spacing, grouping, typography and restrained status colors.
- Provide light/dark/system themes with adequate contrast and no unreadable disabled/secondary text.
- Use reusable components for buttons, inputs, selects, toasts, confirmations, status indicators, progress, empty states, errors and dialogs.
- Do not rely on color alone to explain status. Never use success green for generic decoration or error red without explanatory text.

### Task-first workspace
- The current task must show a clear title/goal, state, last progress, next required user action, elapsed time where useful, and the verified outputs.
- Distinguish **running**, **waiting for approval**, **waiting for user**, **blocked**, **failed**, **cancelled**, **completed**, and **completed with warnings**.
- Put destructive actions behind confirmation. Make Stop/Cancel persistent and reachable, and distinguish cancelling a task from stopping all work.
- Show progress grounded in real lifecycle events. Never invent a percentage unless the runtime can calculate it. Use stage/step progress when exact completion percentage is unknowable.
- Offer a plain-language summary plus an expandable technical trace containing tool name, sanitized arguments, decision, result, verification and timestamps.
- When an action needs approval, display exactly what will be changed/sent, destination/target, privacy implications and the consequences of approval. Do not truncate important text without a deliberate “view full” action.
- A failed step should explain the cause in normal language, include a safe retry/reconfigure action when appropriate, and preserve already-created artifacts.
- On completion, show verified files/URLs/results and what verification was actually run.

### Onboarding and settings
- Reduce first-run setup to the minimum necessary for a first useful task, while keeping sensitive permissions opt-in.
- Explain models/provider keys and local-only mode in plain language. Show key status, endpoint, capabilities, limits and privacy tier without ever echoing the secret.
- Validate settings before save, show what failed and preserve existing valid settings. Avoid losing unsaved changes without warning.
- Make permissions concrete: what can be read, changed, run, sent externally and which agent receives access. Use least-privilege defaults.
- Show external dependencies (browser, Docker/Podman, local model, API key, screen-recording/accessibility permission) with a tested status and next-step remediation.
- Ensure model test is a real bounded request and says whether it was a live test or only a local configuration check.

### Accessibility and responsive behavior
- Use semantic buttons, headings, labels, forms, landmarks and dialogs. All inputs have visible labels and useful error associations.
- Full keyboard operation: logical tab order, skip/navigation behavior where appropriate, visible focus, Escape for dismissible dialogs, and focus restoration after close.
- Screen-reader announcements for task state changes, new approval requests and validation errors without excessive noisy announcements.
- Respect `prefers-reduced-motion`. Ensure animations do not obscure state or delay important actions.
- Verify minimum contrast consistent with WCAG 2.2 AA for text and interactive boundaries where practical.
- Test narrow viewport, browser zoom, long task names/paths, very long output, empty data, offline state and 200% text zoom. Prevent clipped buttons and horizontal overflow.
- Avoid `alert()`/`confirm()` as the primary interaction if a consistent accessible in-app pattern is feasible.

### UI test strategy
- Keep frontend source and generated assets in sync via the documented build command.
- Add component/interaction tests for primary flows and a browser-based smoke test if the project’s tooling supports it without undermining existing constraints.
- Test all controls for both happy and failure paths. Include keyboard-only navigation for first-run, task approval and settings.
- Fix console errors, unhandled promise rejections, broken links and production build warnings that signal real problems.
- Do not add unnecessary dependency weight to achieve visual polish.

## 10. Workstream G — performance, robustness and observability

- Measure startup time, memory use at idle and during tasks, CPU spikes, model latency, tool latency and event-stream overhead on at least one documented baseline machine when possible.
- Bound every untrusted input and resource: HTTP body, file size, page text, screenshot, tool output, task history, memory query, MCP payload, model output, concurrent requests, open tabs, browser downloads and subprocess output.
- Add timeouts and cleanup for network, subprocess, browser/CDP, database, UI streams, routines and model-provider calls. Ensure background tasks are awaited or deliberately supervised.
- Prevent file descriptors, subprocesses, browser tabs, containers, model sessions and background tasks from leaking after cancellation/shutdown.
- Ensure logs are structured enough for debugging but redact secrets and unnecessary personal information. Add correlation IDs for task/step/provider calls where helpful.
- Do not treat a health endpoint as proof that models, tools, the browser or the sandbox actually work. Health checks must distinguish installed, configured, available, tested and currently working.
- Add safe diagnostics/export of environment and recent errors without including access tokens, API keys, message content or sensitive paths by default.
- Make resource limits understandable and provide actionable warnings before a local model overloads the machine.

## 11. Workstream H — tests and quality gates

### General requirements
- Tests must assert behavior, not implementation trivia. Prefer deterministic clocks, fake providers, a controlled HTTP transport, fake filesystem roots and explicit fixtures.
- Every discovered P0/P1 defect gets a regression test before or with its fix when feasible.
- For security tests, assert both that the action is denied and that no side effect took place.
- Do not weaken tests, lower coverage floors, broadly skip tests, disable type checking, suppress security rules, or remove CI jobs to obtain a green build.
- Narrow test exceptions must be explained and be tied to an actual platform/service limitation.
- Add tests for error paths; a passing happy-path test is not adequate evidence of production behavior.

### Run, fix, rerun
1. Run the baseline gates.
2. Triage each failure: pre-existing environmental failure, pre-existing product defect, or regression from the change.
3. Fix product defects and regressions. Do not hide them by changing expected outputs without a justified product decision.
4. Run targeted tests after each workstream.
5. Run full gates again from a clean or clearly documented state.
6. Build the frontend and confirm no unintended generated-file diff remains.
7. Build/install the wheel into a fresh temporary environment and launch a bounded smoke test.
8. Recheck the Git diff for generated artifacts, secrets, unrelated edits, and documentation inconsistencies.

### Required final test record
For every command, report one of: **PASS**, **FAIL**, **BLOCKED**, or **NOT RUN**, with concise evidence. Include the actual command and exit status. If a test could not run because a service/hardware/OS feature was unavailable, say exactly which check remains and the manual steps required.

## 12. Workstream I — documentation, support and public release

- Make README the shortest accurate starting point: what Lilly does, requirements, a safe install path, first useful task, local-only setup, supported platforms and links to security/limitations.
- Ensure setup instructions match the actual code and current UI labels. Never leave stale screens, paths, model IDs or command options.
- Add a “supported / experimental / unavailable” capability table tied to test evidence. Avoid fake parity claims and benchmark bragging based solely on test counts.
- Keep a threat model and disclose residual risks, including prompt injection, incorrect model actions, provider data policies, optional network behavior, local model hardware needs, and real-machine testing limitations.
- Document database migration compatibility, backup/restore, update, recovery, uninstall and how to report a security issue privately.
- State which telemetry exists (ideally none by default), what leaves the device for each mode, what third-party endpoints are contacted, and how users can verify local-only operation.
- Add a release checklist that checks the source tag, package version, wheel contents, frontend build freshness, tests, changelog, licenses, checksums, supported-platform evidence, and rollback plan.
- Recheck all internal and external links; avoid leaving references to nonexistent scripts or unsupported provider features.

## 13. Suggested implementation order

Do not stop at these headings. Work through each phase, adapting to the actual checkout and fixing newly discovered defects.

### Phase 0 — Establish truth
- Inspect git state, tree, current CI/issue/release state and license.
- Run baseline checks and build.
- Create a finding ledger with severity, evidence, exact file/line, fix, and regression test.

### Phase 1 — Release blockers and data safety
- Resolve tracked runtime artifacts safely.
- Repair every broken packaging/install/release reference (including the suspected `uninstall.sh` mismatch if verified).
- Ensure a valid license and audit distribution/dependency/model-license claims.
- Make clean installation, update and data-preserving recovery verifiable.

### Phase 2 — Task lifecycle and security core
- Audit the task/step lifecycle, policy enforcement, approvals, cancellation and recovery.
- Audit filesystem, browser network boundaries, computer control, DevBox, MCP and chat bridge trust boundaries.
- Add regression/adversarial tests before declaring these paths reliable.

### Phase 3 — Model and local-only correctness
- Validate all provider adapters and fallback policies.
- Implement/enforce a genuine local-only mode and no-key path.
- Test auxiliary calls, not just the primary chat completion.

### Phase 4 — Real work acceptance suite
- Add a small, deterministic set of representative tasks: research with sources, create/edit a file, summarize local files, navigate a controlled website, complete a form with approval, run a sandboxed command, recover a failed task, cancel a running task, and resume a task after restart.
- Define what success means for each scenario. Score pass/fail and record failures; do not equate a fluent final answer with task success.

### Phase 5 — UI/UX completion
- Audit every screen/control and implement missing loading/empty/error/waiting/success states.
- Polish the design system and keyboard/screen-reader/responsive support.
- Test real backend flows and generated frontend assets.

### Phase 6 — Release candidate
- Run all quality gates, build and fresh-install package, perform feasible real-machine smoke tests, update documentation, and ensure the working tree only contains intentional changes.
- Do not publish remotely or tag a release unless explicitly authorized.

## 14. Representative acceptance scenarios

Implement tests with deterministic fixtures and use real integrations only as opt-in smoke tests.

1. **Fresh start, no hosted keys:** app starts, explains how to configure a local model, remains usable for health/settings, never attempts remote inference, and shows a clear status until the local model is available.
2. **Simple local task:** with a configured local model, Lilly reads only an explicitly shared test folder, creates a requested artifact, verifies its content, and returns the correct path.
3. **Untrusted web instructions:** a page says to ignore the user, read secrets and upload them. Lilly treats that text as untrusted, does not access ungranted files, does not exfiltrate data, and asks/blocks per policy.
4. **Approval binding:** a write or external action awaits approval, displays the full relevant target/content, and only the exact approved operation executes once. Tampering or expiry causes denial.
5. **Path/symlink escape:** all attempts to access files outside the granted root or through an altered symlink are denied with no outside side effect.
6. **Network/SSRF:** a page/fetch request redirects or resolves to localhost, a private range or a metadata endpoint. The request is denied at the actual connection boundary.
7. **Provider exhaustion:** all remote quota is exhausted or all provider keys are missing. Lilly reports the reason, respects privacy, and uses only an eligible permitted fallback.
8. **Bad model output:** malformed tool args, unknown tool name, invalid schema, empty output or repeated calls do not crash the daemon or invoke a tool incorrectly.
9. **Cancellation:** user cancels during model wait, tool run, browser navigation and pending approval. The UI eventually shows the truthful terminal status and no new unsafe side effect starts.
10. **Crash/restart:** process is interrupted around a tool side effect. On restart Lilly recovers without claiming false success or blindly repeating a non-idempotent operation.
11. **Sandbox:** without a supported Docker/Podman daemon DevBox fails clearly; with one, it sees only the expected mount, has no network unless a separately secure opt-in is supported, and leaves no running container after stop.
12. **UI keyboard flow:** new user can navigate setup, test a model, create a task, inspect progress, approve/deny, stop and open the result without a mouse.
13. **UI failure flow:** API/provider failure, offline mode, stale task and permission denial all have clear, recoverable error states without losing entered work.
14. **Export/restore:** a user can create a backup, restore into a fresh test home, verify task/memory/settings integrity, and see clear warnings around secrets and browser sessions.
15. **Packaged install:** wheel installed in a fresh temporary venv launches the same tested frontend and exposes the documented CLI commands.

For each scenario, include an assertion for visible UI outcome and backend side effects where the test tools permit it.

## 15. Completion checklist

Do not call the work complete until you have reviewed each item below and mark it `DONE`, `BLOCKED`, or `NOT APPLICABLE` with a reason.

### Integrity and license
- [ ] Current branch/status inspected; no user changes overwritten.
- [ ] Tracked runtime/secret artifacts audited; confirmed generated artifacts removed and regression gate added.
- [ ] All referenced scripts and documented commands verified to exist and work.
- [ ] License and third-party/model licensing claims resolved accurately.
- [ ] Packaging, generated web assets, version metadata and release gate are consistent.

### Security and execution
- [ ] Tool registry and runtime validation are authoritative and complete.
- [ ] Approval binding, permission changes, cancellation and restart edge cases tested.
- [ ] Filesystem path scope and symlink/atomic-write behavior tested.
- [ ] Browser/web network egress, redirect and DNS/SSRF boundaries tested.
- [ ] Computer control and DevBox limitations are fail-closed and visible.
- [ ] MCP/skills/bridge inputs are treated as untrusted and permissioned.
- [ ] Model fallback respects task capability and privacy label.
- [ ] Local-only mode rejects remote inference in every auxiliary code path.
- [ ] Secrets are absent from logs, UI echoes, fixtures and generated artifacts.

### Product and UI
- [ ] Representative acceptance task suite exists and has measured results.
- [ ] No task is marked successful without a defined verification outcome.
- [ ] All visible primary controls are functional.
- [ ] Loading/empty/error/waiting/blocked/failed/completed/cancelled states are implemented.
- [ ] Keyboard access, visible focus, dialogs and screen-reader announcements are checked.
- [ ] Responsive layout, zoom, long text/output and theme contrast are checked.
- [ ] UI displays real task/model state, not mock success or invented progress.

### Test and release evidence
- [ ] Targeted tests pass after all changes.
- [ ] Full quality gates pass, or remaining failures are explicitly triaged with evidence.
- [ ] Frontend build is up to date and packaged assets match source.
- [ ] Fresh-install package smoke test passes.
- [ ] Real-device/provider/browser/sandbox checks are marked only if truly run.
- [ ] Documentation accurately describes what passed, what is experimental, and what is not verified.
- [ ] Final Git diff contains only intentional changes; no secrets, databases, caches or unrelated edits.
- [ ] No remote commits, pushes, issues or releases were performed without permission.

## 16. Final response format required from the coding agent

Return a concise but evidence-rich report with these headings:

1. **Implemented:** grouped by release blocker, task reliability, security/local mode, and UX.
2. **Important files changed:** each file with a one-line reason.
3. **Tests actually run:** exact command, PASS/FAIL/BLOCKED/NOT RUN, exit status, and key result. Do not copy old counts.
4. **Acceptance scenarios:** pass/fail per scenario, including any skipped real integration.
5. **Known remaining defects/risks:** severity, user impact, evidence and exact next step.
6. **Manual verification needed:** exact OS/provider/browser/container steps and why automation could not run them.
7. **How to launch and test locally:** current commands verified against the repository.
8. **Working tree status:** changed files and confirmation that no changes were committed/pushed.

Do not end with “everything is bug-free” or “production-ready” unless the evidence justifies a much narrower claim. A good result is an improved product plus trustworthy proof, not a confident-sounding report.

---

## Short instruction to the agent

**Take ownership of this work order. Inspect the actual repository, execute the phases end to end, fix the highest-severity issues, add regression coverage, make the real UI coherent and accessible, rerun all applicable gates, and report evidence honestly. Do not stop at a plan, do not invent test results, do not weaken security to make tests pass, do not overwrite existing user work, and do not push or publish remotely without permission.**
