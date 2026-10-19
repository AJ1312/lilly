# Lilly — Intelligent Harness, Host/DevBox Execution, Learning, Research, and UI/UX Implementation Brief

**Target repository:** `https://github.com/AJ1312/lilly`  
**Known default branch:** `master`  
**Reference snapshot reviewed:** commit `45183f2ed11bc47339faba3aed013b5af6cbaa9d` (2026-10-19; re-check the live checkout before changing anything).  
**Purpose:** This is an execution brief for a repository-aware coding agent. Carry the work through code, tests, UI build, and truthful verification. Do not just summarize this document or produce a plan.

---

## 0. Non-negotiable rules

1. Start with `git status --short --branch`, `git rev-parse HEAD`, `git log -8 --oneline`, and inspect the full tracked tree. Record uncommitted work and preserve it. Never use destructive Git commands or overwrite existing user edits.
2. Re-fetch/re-read the current repository before implementation. The reference commit below is only a locator; newer code, recent token-efficiency changes, tests, and issue status are the source of truth.
3. Validate every suspected defect against code, reproduction, and a regression test. Distinguish confirmed bugs from design gaps and hypotheses. Do not invent failures, benchmarks, pass rates, line numbers or task success.
4. Implement the features in phases, in priority order. Do not stop after writing documentation. Run checks after each meaningful group and fix your own regressions.
5. Reuse the current Python + Starlette backend + React/Vite frontend + SQLite runtime. Avoid framework rewrites and new dependencies unless they give a measurable benefit and are justified.
6. Do not disable or weaken policy, approval payload binding, path scopes, SSRF checks, local-only enforcement, DevBox isolation, secret handling, audit logging, cancellation, or CSRF/session protections to make a scenario pass.
7. Never claim “bug-free.” Aim for no known release-blocking defects, full regression coverage for changed paths, and transparent disclosure of platform-dependent tests that could not run.
8. Never silently fall back from an explicitly chosen execution target. If Host mode is selected and a local-control capability is missing, report it. If DevBox is selected, do not execute a command on the host instead.
9. Do not upload repository content, local databases, logs, prompts, browser profiles, secrets, or user task data to external systems. Do not print or commit secrets.
10. For public research, inspect primary documentation and maintained open-source implementations where useful. Verify license, recent activity, supported platforms, dependencies and relevant issue history. Adapt design ideas; do not copy code without license compatibility and attribution obligations being met.
11. Do not make network calls to providers in unit tests. Live integrations, real-browser tests and real-desktop tests must be opt-in and clearly separated from deterministic tests.
12. Leave remote GitHub issues, branches, pull requests, releases, settings and deployment state untouched unless the user explicitly authorizes those remote mutations.

## 1. Current architecture and paths to inspect first

The latest observed code contains many of the foundations already. Validate each one before adding a parallel implementation.

### Task creation, runtime, completion

- `src/lilly/ui/api_chat.py` — `submit_task`, task detail/events, resume, cancel, receipts, built-in skills list and stop-all.
- `src/lilly/engine/orchestrator.py` — `SubmitRequest`, validation, task creation and queue/lifecycle. The inspected `SubmitRequest` had no explicit per-task execution target.
- `src/lilly/engine/runner.py` — `RunSpec`, `TaskRunner`, plan/loop dispatch and completion handling.
- `src/lilly/engine/agent_loop.py` — agent prompting, tool visibility/discovery, model routing, action intent, result handling and loop controls.
- `src/lilly/engine/steps.py` — tool execution, policy, approvals, context, timeout, and permission handling.
- `src/lilly/domain/tasks.py` / `src/lilly/store/tasks.py` / database migration files — lifecycle and persistence.
- `src/lilly/engine/receipt.py` — task receipt and stored usage/action summaries.
- `src/lilly/engine/context.py`, `src/lilly/core/shortlist.py`, `src/lilly/decide/system1.py`, `src/lilly/decide/laya_decider.py`, `src/lilly/providers/model_broker.py`, and `src/lilly/providers/*` — current token-saving/routing work. Verify rather than recreate these features.

### Host, browser, DevBox, tool permissions

- `src/lilly/tools/__init__.py` — `build_tools`, module-controlled tool registry and injection.
- `src/lilly/domain/tools_registry.py` — canonical tool names, descriptions, schemas, risk, egress, sensitivity and module properties.
- `src/lilly/domain/policy.py`, `src/lilly/domain/grants.py`, `src/lilly/engine/approvals.py`, `src/lilly/domain/payload.py` — policy and approval invariants.
- `src/lilly/tools/computer.py` and `src/lilly/tools/computer_runtime.py` — host-side OS/computer interaction. The observed native backend is macOS-specific; inspect supported backends before promising Windows/Linux parity.
- `src/lilly/tools/browser/manager.py`, `actions.py`, `page.py`, `chrome.py`, `cdp.py`, `guard.py`, and `src/lilly/domain/browser_policy.py` — browser automation and network policy.
- `src/lilly/domain/devbox.py`, `src/lilly/tools/devbox/manager.py`, `engines.py`, `tool.py` — isolated container execution. The inspected DevBox uses no network and sees only one shared folder. That restriction is intentional and must not be silently loosened.
- `src/lilly/domain/sheet.py` and `src/lilly/domain/settings.py` — per-agent capabilities and settings. Existing settings include `computer`, `browser`, and `devbox` modules, `network.local_only`, and a DevBox config, but that is not a per-task execution-target control.

### Memory, skills, routines, agents

- `src/lilly/store/memory.py`, `src/lilly/tools/memory.py`, `src/lilly/ui/api_data.py`, `web/src/views/Memory.tsx` — user-editable long-term memory exists; agent memory writes are currently direct store operations gated through tool policy/approval. Extend this carefully.
- `src/lilly/domain/skills.py` — hash-pinned deterministic built-in plan templates (`BUILTIN_SKILLS`).
- `src/lilly/tools/agent.py` — `skill.load` loads named skills from an agent sheet, a separate path from built-in skills.
- `src/lilly/domain/sheet.py` — custom per-agent skills and instruction sections.
- `src/lilly/ui/api_chat.py:list_skills`, `web/src/views/Talk.tsx:SkillDialog` — the current chat skill dialog lists built-in skills via `/api/skills`. Check whether agent-sheet skills are discoverable/visible in the selected-agent UI; unify the experience without conflating the two sources.
- `src/lilly/domain/schedule.py`, `src/lilly/ui/api_routines.py`, routine store/scheduler, `web/src/views/Routines.tsx` — recurring requests already exist. The requested addition is a safely learned, versioned workflow attached to a routine—not a duplicate scheduler.
- `src/lilly/engine/crew.py` — delegation/crew support; do not introduce new agents just to replace existing capabilities.

### Frontend

- `web/src/App.tsx`, `web/src/api.ts`, `web/src/store.ts`, `web/src/types.ts`, `web/src/styles.css`.
- `web/src/views/Workspace.tsx` — task-oriented split-pane workspace and composer.
- `web/src/views/Talk.tsx` — conversation-oriented chat, controls and Skills dialog.
- `web/src/ui/RunCard.tsx`, `ApprovalCard.tsx`, `BrowserWatch.tsx`, `ComputerWatch.tsx`, `kit.tsx`, `Markdown.tsx`, `Palette.tsx`.
- `web/src/views/Settings.tsx`, `ModelsSection.tsx`, `SecuritySection.tsx`, `DevboxSection.tsx`, `Agents.tsx`, `Memory.tsx`, `Routines.tsx`, `Activity.tsx`, `Resources.tsx`.
- Compiled assets live under `src/lilly/web/`; run the repository’s prescribed frontend build so the shipped UI matches source.

The latest source also includes `benchmarks/token_efficiency_benchmark.py`, `tests/unit/test_token_efficiency.py`, `docs/BASELINE.md`, `docs/VERIFICATION.md`, and `docs/ROADMAP.md`. Keep these accurate as the product changes.

---

## 2. P0 — Correct completion semantics before changing the UI

### Confirmed issue visible in the supplied screenshot

The task title is “play slow hands by niall horan on yt music site.” The page shows `Done` and “Lilly finished and verified this task,” but the result says YouTube Music is not optimized for the current browser and asks whether to switch to Chrome, search manually, or try another platform. That is not successful completion of the requested action. The screenshot is sufficient to prove the UI presents contradictory success semantics; reproduce the underlying route and identify whether the false success originates in task outcome logic, a tool result, or just the UI label.

### Required design: separate execution state from goal outcome

Do not equate “the agent loop stopped” with “the user’s goal was achieved.” Keep lifecycle status (queued, planning, running, waiting for approval, verifying, stopped, failed, etc.) separate from a persisted, typed goal outcome such as:

- `success` — the requested outcome was actually achieved and evidence supports it.
- `partial` — some useful work happened, but part of the requested goal remains unmet.
- `needs_user` — a choice, login, permission, missing preference or hand-off is required.
- `blocked` — policy/platform/provider/site capability prevented the task.
- `unverified` — the available evidence is insufficient to claim success.

Names can follow project conventions, but semantics must remain explicit and database-backed. Add a safe migration for old tasks; historical `DONE` tasks must not automatically become verified successes unless existing evidence genuinely supports that conclusion. Default legacy results conservatively to `unverified` or an explicitly documented legacy state.

### Completion contract

1. For `ACTION` tasks, inspect fresh application/browser state and verify the intended visible result before setting outcome to `success`.
2. Opening a website/app, producing a search results page, writing a plan, or asking the user how to proceed is not success for a task that requested an action.
3. For research tasks, require the requested deliverable and source/evidence criteria, not merely a response from a model.
4. If the result asks the user a question because the original task was not finished, set outcome `needs_user`/`partial`, not success.
5. A blocked or denied action must stay blocked; the model must not route around it. Offer permitted alternatives and label the task honestly.
6. If no verification mechanism exists for an action, show “Not verified” or “Needs confirmation,” not “finished and verified.”
7. The final receipt must distinguish completed tool operations from fulfilled user goal.

Wire the outcome through database rows, server JSON, TypeScript types, API routes, timeline/status pill, task list, chat turn, run card, receipts, resume/retry flows and event log. Use one canonical outcome mapping and ensure the UI cannot manufacture success from lifecycle state alone.

### Required regression tests

- The screenshot scenario: browser reports unsupported site/browser and the assistant asks what to do next. Must not show success/verified.
- A file-write task whose file exists and matches expected content can be success.
- A task that merely opens a URL when asked to play media cannot be success.
- A task with an approval pending is not completed.
- A user-declined action is not retried or labeled success.
- A plan with some successful and some failed steps returns `partial` or `blocked`, with precise status.
- Direct simple Q&A (no tools required) may finish as an answered/success outcome without forcing unnecessary action verification.
- Historical DB migration: old task detail remains readable and no false success assertions are created.

---

## 3. P0/P1 — Explicit per-task execution target: This Laptop vs Isolated DevBox

### Goal

Every new task should have a visible choice for where side-effecting execution occurs:

- **This laptop** (direct/host execution) — existing permission-scoped host tools, allowed file roots, supported native computer control and the browser instance according to settings. Be clear that direct host control can modify the real machine. Existing approvals, policy, and private-data permissions still apply.
- **Isolated DevBox** — code/shell execution inside the current constrained Docker/Podman environment, only within the chosen shared folder. Keep network disabled, root filesystem read-only where configured, resource limits, timeouts, and no host socket. It cannot interact with host desktop apps or see arbitrary host files. Do not pretend it can.
- Optionally `inherit/default` for compatibility if needed; if shown, explain what it resolves to. Avoid a silent “auto” fallback when the user explicitly chose one target.

This is **execution placement**, not the same as model inference privacy. A task running on Host may still use a local or hosted model according to model settings; `Local only` controls inference egress separately. Make both concepts clear.

### End-to-end implementation contract

Add an enum/value to the task submission request, persisted task row and runtime `RunSpec`/context. Thread it from UI → `POST /api/tasks` → `SubmitRequest` → orchestrator/database → runner/agent loop → visible capability set → policy and `StepExecutor` → audit/event/receipt. The backend must be authoritative; a disabled UI control is not security enforcement.

Review at least:

- `src/lilly/engine/orchestrator.py:SubmitRequest` and task creation.
- `src/lilly/engine/runner.py:RunSpec` and dependency flow.
- `src/lilly/ui/api_chat.py:submit_task`, `src/lilly/domain/tasks.py`, task store/schema/migrations.
- `src/lilly/tools/__init__.py:build_tools`, tool registry and `AgentLoop` visibility/capability filtering.
- `src/lilly/tools/computer.py`, `computer_runtime.py`, browser tools and DevBox manager.
- `web/src/types.ts`, `web/src/views/Talk.tsx:Composer`, `web/src/views/Workspace.tsx:TaskComposer`, `web/src/ui/RunCard.tsx`, task detail and receipts.

### Tool eligibility / routing matrix

Define and test a canonical target capability policy rather than scattered name-based conditionals. At minimum:

| Capability | This laptop | Isolated DevBox |
|---|---|---|
| Native desktop observe/click/type/drag | Allowed only on supported OS, with user permissions and policy | Unavailable; never fallback to host GUI |
| Host app opening / process control | Only through explicit registered tools, scope and risk/approval checks | Unavailable as host actions |
| Shell/code execution | Existing host path scopes, command policy, approval/risk and limits | `devbox.run` only; enforce mount and container constraints |
| File read/write | Only user-shared roots/path policy | Only the explicitly shared folder mounted into the box |
| Browser UI | Existing browser policy/profile and consent behavior; visible/headless status must be honest | Not available in network-isolated container unless a separately designed/tested browser-in-container capability is added |
| Web research/search | Existing web tools and external-egress policy | The existing no-network DevBox cannot fetch public listings; do not claim otherwise or silently run the research inside Host mode |
| Model inference | Controlled by model/provider privacy settings independently | Still follows `Local only` and model data-access policy; DevBox selection alone does not guarantee local inference |

Never infer trust from the selected target. Both paths still enforce tool schema, agent permissions, shared roots, hard policy denials, action approvals, cancellation, auditing and task budgets. An explicit target must be stored in approval payloads and hashed along with tool+arguments so an approval cannot be reused after switching targets.

### UI requirements for target selection

Add a clear segmented selector in both Talk and Workspace composers, near the message/task field—not hidden deep in Settings. Suggested labels:

- `This laptop` with a monitor/computer icon and concise “Can use permitted local files, browser and supported desktop controls.”
- `Isolated DevBox` with a box/shield icon and concise “Runs commands in a locked-down container; no network; shared folder only.”

Show the resolved target in task rows, task header, activity/receipt and each action/approval card. Make it possible to change the target before submission. Do not let the composer’s current selection alter existing tasks or global settings accidentally. Explain unsupported actions before starting or return a structured capability error. Offer a “What can this target do?” tooltip/details panel.

Default behavior must be deliberate and backwards compatible: determine current legacy routing behavior before choosing a default. If the app has a global execution preference, add it in Settings and treat per-task selection as an override. Do not change a global default by manipulating a per-task composer control.

### Essential tests

- Host target: eligible desktop tool invocation hits the host backend, obeys OS availability and retains permissions.
- DevBox target: `computer.click`, `computer.run` on host, `browser.*` host UI and arbitrary host file access are blocked/unavailable; nothing falls back to the host.
- DevBox command sees only shared folder; path traversal/symlink/mount boundary tests remain blocked.
- Provider/model routing respects `network.local_only` independently of execution target.
- Target survives reload, task resume and history display.
- Approval made for one target becomes invalid if the target or approved arguments change.
- Legacy request with no target retains explicitly documented behavior.
- On unsupported platforms, Host desktop capabilities display a clear status and are not represented as usable.

---

## 4. P1 — Local-first adaptive memory and learning from successful work

### Extend existing memory; do not create a second unrelated memory database

Lilly already has long-term memory (`store/memory.py`, `tools/memory.py`, Memory UI) and agent-specific skills in sheets. It lacks a complete, measurable, user-controlled learning lifecycle connecting successful tasks to reusable procedures. Add it on top of existing persistence where appropriate.

### UI settings

Add a focused **Learning & memory** section in Settings with clear opt-in modes such as:

- `Off` — save only explicitly requested memories / existing user-managed flow.
- `Suggest for review` — create candidate memories/playbooks after eligible tasks; user reviews before activation.
- `Auto-save safe learning` — automatically save only low-risk, non-sensitive, local-only candidate facts and verified workflow templates. High-impact, ambiguous or sensitive candidates still require review.

Make clear that learning stays local, what it stores, when a local model is needed, whether task history is used, and how to inspect/export/delete/undo it. No hidden telemetry or remote training.

### What can be learned

Prefer structured records with provenance rather than fine-tuning model weights in the background:

1. Stable user preferences (format, units, recurring constraints) when clearly expressed and not sensitive.
2. Project context and known decisions with source task/project identifiers.
3. Verified workflow templates/playbooks: task signature, parameter schema, preconditions, minimal tool sequence, required permissions/target, expected output, verification procedure, failure handling, success count and version.
4. Operational hints such as a confirmed working command or browser flow, with OS/provider/version constraints.

Do **not** store whole conversations by default. Do not store credentials, API keys, passwords, tokens, private keys, secrets or sensitive personal data as learned facts. Never treat instructions embedded in web pages, external files, MCP outputs or other untrusted content as rules/memories to follow. Record provenance and trust label for every candidate.

### Task-completion learning pipeline

After a task reaches a terminal outcome:

1. Check eligibility: successful/verified tasks are candidates for playbook learning; partial/failing/unverified tasks may contribute failure diagnostics but not a runnable learned procedure.
2. Extract structured candidates. Prefer the local inference runtime/model where it is usable. If no local model is installed, use deterministic extraction or place a candidate in review; do not silently send private task history to a hosted provider. Follow local-only policy at the execution boundary.
3. Redact potential secrets/PII and reject candidates that include unsafe content, arbitrary shell commands with untrusted provenance, or expanded privileges.
4. Normalize, deduplicate semantically (not just exact-text), detect contradictions against existing memories, and store source task, timestamps, confidence, scope, model/version if used, and evidence pointers.
5. For safe eligible items under Auto-save mode, persist them. For anything else, show a review card with candidate, evidence, “Save”, “Edit”, “Reject”, “Forget/undo” and why it was suggested.
6. Update usefulness/success evidence when the memory or playbook is reused. Support correction, rollback/version history and deleting all derived records for a source task if the user requests it.
7. Bound memory retrieval by relevance, label/permission and token budget. Inject only the most relevant few items into context; never stuff the entire memory store into every prompt.

### Local small model / basic-task learning

Do not claim a small model “learns” merely because a prompt or memory changed. Use explicit architecture:

- Deterministic rules first for obvious task categories.
- Existing Laya/System1 small classifier for routing/classification where its measured confidence warrants it.
- A learned playbook matcher that uses task signature + preconditions and is calibrated from prior runs.
- If the best matching playbook has low confidence, a mismatch, missing parameter, unsupported target/platform, stale dependency or poor success rate, use the normal planner.
- Track false matches, fallbacks, completed-task success, latency, cloud tokens/cost and local CPU/RAM. Use labeled outcomes to calibrate thresholds.
- Playbooks are data/templates and must be revalidated against the live tool registry, current schemas, current policy and current approvals every time they run. They must never raise risk, widen permissions or bypass a gate.
- Do not perform unreviewed model-weight fine-tuning or arbitrary self-modification. Keep system policy, tool registry, security code and provider-routing rules immutable to learned workflow data.

### Efficient learned workflow execution

A validated playbook should be able to skip redundant planning calls and invoke known safe steps deterministically, but only with exact schema validation, target constraints, policy checks, fresh preconditions, idempotency, and action verification. Read-only steps may be parallelized where existing `LaneScheduler` deems them safe. Side effects stay ordered and gated. Record playbook version and provenance in every run receipt.

### Tests

- Auto-save works only when enabled; default behavior is conservative.
- Secrets/untrusted instructions never become runnable memories.
- Similar memories deduplicate; conflicting memories prompt review and preserve provenance.
- Deleting/undoing memory and deleting a learned playbook work end-to-end.
- Incorrect playbook preconditions cause safe fallback, not execution.
- Every playback revalidates live tool schema, risk, permission, user grant, target and approval hash.
- Local-only learning never contacts a remote model for extraction.
- Tests measure whether the small-model/playbook route really reduces provider calls without reducing verified completion rate.

---

## 5. P1 — Learn-and-repeat daily workflows, built on existing Routines

Routines already schedule arbitrary requests. Add a clear way to turn a verified successful task/playbook into an opt-in repeatable workflow.

### User flow

After a task’s outcome is `success`, present secondary actions such as:

- `Remember this workflow` — save a versioned playbook.
- `Repeat daily…` / `Schedule…` — use that playbook in the existing Routine system.

Do not offer an “auto-repeat” prompt after a failed/partial/unverified task unless explicitly described as diagnostic monitoring. Do not schedule without an explicit user opt-in.

### Routine fields and execution contract

Connect the routine to a `playbook_id` and immutable `playbook_version` or an explicit “use latest approved version” policy; do not silently change a running routine when a playbook updates. Record schedule/time zone, execution target, permitted tools/agent, model/privacy limits, max runtime/model calls/tokens, current enable/pause state, next run, last result/outcome, last cost and notification preference.

At a daily run:

1. Confirm the routine is enabled, not paused, target supported, agent permissions unchanged, required tools installed and playbook version valid.
2. Execute the learned template with current parameters and fresh inputs. Never reuse stale search/job listings as current data.
3. Enforce duplicate/idempotency keys for writes and external actions. Where idempotency cannot be established, require approval or stop.
4. Apply bounded retries, task/time/token/cost budget and loop detection. Do not recursively schedule a routine from its own output.
5. Verify results and update the routine's last run/outcome. If blocked or failed, pause or alert according to explicit user settings; do not repeatedly spend tokens retrying daily without surfacing the problem.
6. Respect existing Stop All behavior: stop current work and pause future runs.

### UX

In Routines, show “learned workflow” badge, playbook version, execution target, last outcome, next run in local time, estimated/actual resource use and why a run paused. Provide Run now, Pause, Edit, Change target, View playbook, History and Delete actions. Confirmation is needed for destructive or high-impact changes. Empty states must link to a successful task or new routine.

### Tests

- Daily schedule handles local timezone/DST and restart correctly.
- Disabled/paused routines do not run; Stop All pauses them.
- Routine runs the referenced version; edits/version upgrades are explicit.
- Repeated run does not duplicate file writes or other side effects.
- Playbook/tool/agent permission changes stop a routine safely.
- Failed workflow pauses/notifies per configuration and records failure honestly.
- Fresh web/job data is retrieved each time rather than reused from cached historical text.

---

## 6. P1 — Make research behavior genuinely useful and specific by default

A task such as “search SWE job roles for me” must not return a generic paragraph about job sites. It should either ask a small number of high-impact clarification questions or state sensible defaults and gather current, verifiable listings.

### Research strategy and intake

Introduce task-scoped research strategy that is separate from Host/DevBox execution placement:

- `Public web research` — search and fetch public sources; no visible browser needed unless necessary.
- `Visible browser` — use the installed supported browser for workflows requiring interaction, logged-in state or visible navigation.
- `Both` — collect broadly through public search/fetch, then use the browser for verification or cases requiring interaction.

Do not ask a question when the request is already clear and the choice does not materially change the result. For an ambiguous request like job searching, ask only essential missing constraints (for example geography/remote preference and role level) or show the proposed default plan with an easy edit. Use learned preferences only when relevant, current and provenance-backed. Never ask the user to give information Lilly can safely retrieve itself.

### Exact job-listing workflow

Create or improve a `job-search` skill/workflow with validated parameters, but route through current tools and user criteria rather than a brittle hard-coded website. Process:

1. Resolve search criteria: role titles, seniority, country/city/remote, employment type, recentness, company/industry/skills, result count, sources and exclusions.
2. Search public web/current company career sources and reputable job boards. Prefer direct employer career pages and canonical listings; verify third-party aggregators against the original listing when possible.
3. Fetch each exact listing/page and extract structured fields: job title, company, location/remote status, posted date if present, requisition ID, required qualifications, experience level, compensation only if explicitly published, canonical direct URL, source, and timestamp verified.
4. Verify that the URL is still live and the page still appears to be an active listing. Distinguish “not stated” from inferred information. Do not invent posting dates/salary/work arrangement.
5. Deduplicate by requisition ID and canonical URL; use secondary matching for same-company reposts and flag uncertainty.
6. Rank by explicit filters/fit criteria; show reasons and trade-offs, not a generic summary. Include exact links, last-checked timestamp, sources, and failed/blocked sites. State coverage/limitations.
7. Save a structured artifact/CSV/table if requested, with citation/source columns; verify the artifact exists and row counts match.

If a site blocks access, a login is required, or browser compatibility prevents completing an action, stop that path, surface the limitation and offer the next precise action (switch to visible browser, ask user to log in, or try another source). Never mark a generic apology/question as fulfilled job search.

### General current-information behavior

For fresh-information requests, default to retrieval and verification over memory-only answers. Use multiple sources where appropriate, prioritize primary sources, note publication/update dates, distinguish confirmed data from inference, preserve links and evidence, and state when the source was checked. For code/library/tool questions, search official docs plus maintained public repositories and issue trackers where useful, compare licenses/activity/limitations, and integrate only evidence-backed designs.

### Tests / fixtures

Add a deterministic mock job board/career page fixture with active, expired, duplicate, missing-date, blocked and malformed listings. Assert exact structured fields, canonical URLs, date handling, dedup, stale cache invalidation, citation preservation and honest partial outcomes. Live scraping tests are opt-in.

---

## 7. P1 — Professional conversation-first UI/UX redesign

The current product has both `Workspace.tsx` (task-oriented three-pane layout) and `Talk.tsx` (conversation-oriented chat). Improve them without discarding the useful live execution timeline or rewriting the app framework.

### Screenshot-specific problems to fix

- The current workspace occupies three strong vertical regions: navigation rail, narrow task list/composer, and a wide detail panel. On the supplied 1664px screenshot, the left composer and task list are cramped while the right panel has oversized unused space. Rebalance widths and typography; support collapse/hide of the task list and a focused chat mode.
- The task detail asserts “Lilly finished and verified this task” based solely on `task.state === 'DONE'`. Change it to use persisted goal outcome and real verification evidence (see section 2).
- Step labels fall back to raw internal tool IDs: `web/src/ui/format.ts:TOOL_LABEL` contains only a subset of the registered tools, so items such as `agent.discover` and `browser.open` appear technical/unformatted. Replace the partial display-only map with one canonical tool metadata source or a complete, tested frontend/server metadata contract. Every registered tool should have a user-readable title, short description, icon/category, risk indication and visibility hint. Unknown/new tools should get an explicit safe humanized fallback, never a concatenated raw ID like `browseropen`.
- `Talk.tsx:Composer` and `Workspace.tsx:TaskComposer` expose multiple selectors/buttons beside the message field, and approval-mode changes call `PUT /api/settings` from the composer. This can look task-scoped while changing a global setting. Move global defaults into Settings or add an explicitly persisted task override; the UI must label which scope is being changed and must never surprise-update global configuration while starting a task.
- `Workspace.tsx` requests `/api/tasks?limit=80` but presents the returned length as a task count. Add real pagination/search/filter/total metadata or clearly label “80 loaded”; do not imply the visible page is the entire history.

### Design direction

Make Lilly feel like a polished desktop work application, not a debug dashboard. Keep the forest/cream brand if it tests well, but improve hierarchy, spacing, density and legibility. Avoid unnecessary gradients/glass effects, oversized serif headings inside task details, raw event logs as the primary interface and excessive controls in the composer.

Required layout:

1. **Collapsible navigation rail:** clear active state, compact icons with labels, accessible focus, pending approval count, app health indicator, responsive mobile drawer.
2. **Conversation list:** search, filter by active/failed/completed/archived, new chat, rename/archive/delete, useful previews and cursor pagination. Show task outcome separately from lifecycle status.
3. **Primary chat:** readable max-width message column, clear user/assistant distinction, comfortable density, persistent bottom composer, streamed output and automatic scroll that works while new content streams.
4. **Task execution details:** expandable step timeline/right drawer showing human tool names, status, intent, environment target, approval state, short output previews, error/retry guidance and evidence. Keep raw arguments and low-level trace under Advanced details, not as primary UI.
5. **Composer:** large text area with sensible keyboard behavior, send/stop/cancel, selected agent, auto model by default, task intent where useful, Host/DevBox execution target, approval scope, optional research strategy, and attachments/drag-drop only when safely supported by the backend. Place advanced choices in a clear toolbar/popover instead of forcing every selector into the main row. Keyboard users must reach every control.
6. **Task outcome strip:** “Completed”, “Partially completed”, “Needs you”, “Blocked” or “Not verified”; include evidence/verification status and next action. Never show success merely because the loop stopped.
7. **Contextual affordances:** after a verified successful task, offer Save as skill/Remember workflow/Repeat on a schedule. After failure, offer Retry, Change execution target, Open error details and safe recovery as applicable. Do not offer nonsensical follow-up questions after declaring success.
8. **Mobile/narrow layouts:** hide the task-list pane behind a drawer, ensure the chat gets the available width, wrap controls, avoid horizontal overflow, keep approval actions visible, and restore focus when dialogs close.

### Chat functionalities to add or improve

- Reliable streaming and reconnect: do not lose messages after SSE disconnect; reload persisted task/conversation state on reconnect and avoid duplicates.
- Correct autoscroll: inspect the `Talk.tsx` effect which currently scrolls when message/task count changes; streaming content changes without count changes may not trigger it. Reproduce and fix without yanking the user away if they intentionally scrolled up. Add a “Jump to latest” affordance.
- Message actions: copy, retry task with same intent/target, edit/resend where safe, open task detail, inspect sources, and save useful response as note/memory through explicit flows.
- Long responses: Markdown/code fences/tables/link treatment, copy code, readable truncation/expand and safe external links.
- Research output: render source-linked result cards/table with actual fields (company, title, location, date, URL) instead of one generic block; all values must come from tool evidence.
- Tool and skill discoverability: distinguish built-in reusable skills from agent-sheet/custom skills. When selecting an agent, show the skills truly available to that agent and its permissions. Keep a searchable skill picker with input validation, descriptions, estimated effects, required permissions and the execution target compatibility.
- Approval UI: show exact action, destination, files/diff, target (Host/DevBox), requested data/model, impact, reason and approve/deny. The approved payload must match what executes.
- Empty/loading/error/offline/unauthorized/permission-denied/unsupported-platform states must be understandable and actionable; do not expose secrets or raw tracebacks.
- All buttons must work. No decorative fake functionality, fake percentages, placeholder success toasts, nonfunctional attachment affordances or hidden global setting mutations.

### Hard-coded values audit

Search with `rg` and inspect every relevant hard-coded string/value. Do not blindly remove all constants—policy limits and protocol values should remain code-defined. Classify each into:

- security/protocol invariant (keep central and test it),
- configurable user preference (persist in Settings with schema/version/validation),
- UI copy/label (centralize to avoid contradictory mappings),
- demo/placeholder (remove from production or gate behind explicit demo mode),
- model/provider assumption (configurable or capability-detected),
- platform-specific command/path (capability-detect and report honestly),
- fixture/test input (keep within tests).

Audit `TOOL_LABEL`, duplicate `statusLabel`/`STATE_LABEL` maps, hard-coded examples in Talk welcome, task list caps, text-length/token limits, max result sizes, model choices, platform availability, browser compatibility assumptions, devbox image defaults, skill names, allowed-host behavior, and default approval/mode behavior. Keep deliberate limits centralized and add comments/tests. Make the UI show the reason when a cap/unsupported capability affects results.

### Design and accessibility gates

- Test a clean frontend build and the existing Playwright smoke suite; expand E2E tests around core user stories.
- Test at common desktop widths (e.g. 1280, 1440, 1664px) and narrow mobile widths; inspect screenshots as well as DOM assertions.
- Keyboard-only navigation, skip link, focus rings/restoration, accessible names for icon buttons, labeled controls, dialog focus trap, reduced motion, contrast and screen reader status messages.
- Ensure the current theme preference works with system preference and survives reload.
- Run `make web` (or current documented equivalent) and check compiled assets under `src/lilly/web/` are updated as expected.

---

## 8. P1/P2 — Task prompting, instruction quality, and intelligent default workflows

### Replace vague “use tools if needed” behavior with capability-aware task plans

Update the appropriate central prompt(s), likely `src/lilly/engine/messages.py`, `src/lilly/engine/agent_loop.py`, `src/lilly/engine/planner.py`, and task-specific skill templates. Avoid repeating large prompt text across components; keep the stable prefix short and cache-friendly.

When the request is an action or current-information task, system instructions must require Lilly to:

- identify the actual desired outcome and any essential missing constraints;
- choose among public web search/fetch, visible browser interaction and host desktop control based on capability and task intent;
- use the explicit Host/DevBox target and never silently cross it;
- discover available tools through the registry rather than hallucinating tool names;
- use primary/current sources, preserve evidence/URLs/timestamps and distinguish fact from inference;
- call tools with the smallest necessary inputs, use compact result references, batch independent safe reads, and avoid repeating identical failed calls;
- read results, inspect fresh state after actions and verify the specified acceptance criteria;
- ask concise clarification when a choice materially changes approach, authorization or result; otherwise state defaults and proceed;
- report completed, incomplete, blocked and unverified items explicitly, never fabricate tool output or tell the user that a task was performed when it was not.

### Public repo/tool research for development tasks

When Lilly (or the coding agent implementing Lilly) needs an unfamiliar library, skill, connector or computer-use capability, require a research procedure: official documentation first; then actively maintained public repositories; check license, releases, recent commits, unresolved issues, platform support, dependencies, security posture and measurable fit. Search active issues for the exact integration and check whether upstream code has known bugs. Add a dependency only if it clearly beats the existing component and can be maintained. Record source links and relevant caveats. Do not add a dependency merely because a blog/demo exists.

### Avoid excessive questions

Do not turn every request into a long setup wizard. Ask at most one concise clarification round containing only high-impact missing filters. Offer a proposed default and allow the user to correct it. Save preference only through the learning controls in section 4.

---

## 9. P2 — Product polish and missing capabilities

Prioritize gaps that improve daily usefulness rather than a long feature checklist.

1. **Task search and pagination:** API-supported cursor/offset pagination, total count, filters for state/outcome/target/date/agent and query search. Avoid fetching all history on every refresh.
2. **Task recovery:** visible retry/resume with exact status, ambiguity confirmation for in-flight desktop actions, safe retry semantics and idempotency checks.
3. **Artifacts/results:** task artifacts panel with open/download/copy, provenance, preview, creation time and verified output; no paths or links made up by the model.
4. **Research as a first-class result:** structured sourced tables, deduplication, freshness label, coverage report, export-to-CSV/Markdown and source inspection.
5. **Skill management:** versioned skill list with source, parameters, last-used/success evidence, enabled/disabled state, permission requirements, compatibility/verification tests, export/import, rollback and delete. Custom per-agent skills and built-in skills must be visibly distinguished.
6. **Memory quality controls:** source/provenance, confidence, last used, scope, review queue, dedup/conflict UI, edit/delete/undo and local-only guarantee where selected.
7. **Routine safety:** learning-playbook version linkage, exact next run, per-routine target and budget, history, failure policy, pause state and safe rerun.
8. **Provider/model UX:** capability-based choices (tool calling, vision, context length, local/remote, privacy access, cost metadata when known), actionable diagnostics and transparent fallback. Never hardcode provider behavior that can be detected.
9. **Health/permissions visibility:** one clear status area for desktop permissions, browser availability, DevBox engine/image, model reachability, and local-only mode. Explain missing prerequisites without forcing user to decode tracebacks.
10. **One source of truth:** tool display metadata, outcome labels, task states, capability descriptions and limits should not disagree between server, UI, prompts, receipt and docs.

---

## 10. P0/P1 security and privacy checks for all new features

- Execution target is part of the tool call authorization scope and approval hash.
- Host mode cannot access paths outside granted roots or bypass per-agent permissions.
- DevBox mode keeps the current no-network, restricted mount, read-only/root/capability/resource constraints unless a separate threat-modelled design is approved. This brief does not authorize network access in DevBox.
- `Local only` must enforce the model endpoint boundary in the backend and all provider fallback paths, including custom base URLs. Do not confuse model inference with web tool egress.
- Learning extraction never uploads private content in Local only mode. If local inference is unavailable, queue a review candidate or skip extraction.
- Untrusted web/skill/MCP content cannot rewrite policy, trigger self-approval, authorize new tools, expand target, or become trusted memory automatically.
- Prompt-injection, malicious tool result, schema poisoning, stale permissions, concurrent settings changes and approval payload tampering have adversarial tests.
- Logs/receipts record enough for debugging but redact keys, credentials and sensitive content.
- Routine replays re-check all permissions and policy, never inherit stale approvals, and use idempotency where side effects repeat.
- Auto-learning can never change tool risk, hard policy, privacy policy, trusted domains, approval minimums, model permission ceilings or target permissions.

---

## 11. Database/API/frontend implementation requirements

1. Add migrations using the repository’s existing migration mechanism. Do not edit already-applied migrations in place. Test fresh databases and upgrades from representative previous schemas.
2. Update typed server/domain/store representations consistently: task submission, persisted task, task detail JSON, event/receipt, routines, memory/playbook candidates, and skill registry.
3. Validate API fields strictly. Reject unknown enum values, wrong types, oversized payloads and disallowed target/capability combinations with clear errors. Do not trust client-supplied permissions/outcome/verification claims.
4. Update `web/src/types.ts` and API wrappers before relying on new properties in UI.
5. Keep event names and event payloads stable where possible; add typed events for target, outcome, memory candidate/review, learned workflow and routine launch.
6. Implement backend behavior before UI decoration. Then wire each control to real API state, error/loading handling and persistence.
7. Ensure task replay/resume preserves the original explicit target or requires a deliberate target change with a new approval. Never mutate target silently.
8. Ensure UI target, task outcome, goal verification, budget, skill version and routine state derive from server results; do not locally invent status.

---

## 12. Test plan — required before completion

Run existing commands after validating they match current project configuration. At minimum, inspect and run relevant forms of:

```bash
make check
make web
make release-check
PYTHONPATH=src .venv/bin/python benchmarks/cua_benchmark.py
PYTHONPATH=src .venv/bin/python benchmarks/token_efficiency_benchmark.py
```

Run test subsets for task/orchestrator, loop/steps, tools, policy/approvals, browser, computer, DevBox, routines, memory, skills, migrations, and web E2E as relevant. Do not claim real-device support based solely on mocks.

### Acceptance scenarios

1. Screenshot regression: YouTube Music/browser unsupported result → not marked goal-success/verified; result explains the blocker and next action.
2. Host/DevBox control is visible and selectable from Talk and Workspace; selection persists on task row/detail/history and survives page reload.
3. Explicit DevBox task attempting host desktop or host-only network action is blocked with useful guidance, no fallback.
4. Explicit Host task on a system without supported computer backend explains unsupported capability; it must not pretend success.
5. Code task succeeds inside a DevBox mounted to a designated shared folder, cannot read sibling paths, and reports exit code/output plus verification.
6. Local-only model routing never uses remote provider fallback even when configured models are rate-limited/unavailable.
7. Task action approval payload includes target and exact args; editing target/args invalidates approval.
8. User asks “search SWE jobs for me”; Lilly asks only the essential missing preferences or states defaults, gathers exact current listings from tools, validates direct URLs/current status, deduplicates and returns a useful table with source and checked time.
9. Expired/duplicate/blocked job listings are represented correctly; dates/salary are never invented.
10. User explicitly opts into learning after verified workflow; a versioned playbook is saved with preconditions and evidence, then re-runs without unnecessary planning only when safe.
11. Auto-save safe memory works only under chosen user mode; secrets and hostile page instructions are not saved as facts/playbooks.
12. Routine based on a learned workflow runs at chosen local daily time, respects target and budgets, records outcome, and does not duplicate non-idempotent actions.
13. Tool discovery labels are human-readable for every registered tool, including `agent.discover`, all `browser.*` and all `computer.*`/MCP tools.
14. Changing approval mode in a composer does not silently change global settings. UI clearly differentiates global default from per-task override.
15. Task list count equals the server total or clearly indicates how many tasks are loaded; search/filter/pagination works.
16. Streaming chat stays scrolled to the latest content unless the user has scrolled away; it reconnects and reloads state without duplicate text/messages.
17. Keyboard, screen-reader labels, dialog focus, 1280/1440/1664 desktop and narrow mobile layouts are checked. No clipped composer, inaccessible approvals or horizontal overflow.
18. All task buttons (send, stop, resume, retry, approve, deny, target toggle, skill run, learn, schedule, edit/delete) are connected to actual behavior and show success/failure truthfully.
19. Every new DB field migrates on existing data; deleted memories/playbooks and disabled routines behave as expected.
20. `Stop all` cancels active work, pauses routines and prevents new background work from racing after the kill switch.

---

## 13. Work order and definition of done

Implement in this sequence:

### Phase A — P0 correctness
- Reproduce and fix false success/verification semantics.
- Establish outcome model, API/store migration and truthful UI labels.
- Fix any verified task completion, cancellation, retry or result-state defects found during tracing.

### Phase B — P0/P1 execution target
- Implement Host vs DevBox target across request→DB→runtime→policy→tools→approval→receipt→UI.
- Create target capability matrix and tests before exposing the selector.

### Phase C — P1 chat and workspace UX
- Redesign the layout/composer, task outcome strip, step labels, responsive behavior, streaming/scrolling and global-vs-task settings scope.
- Make every control fully functional and server-backed.

### Phase D — P1 learning and workflows
- Add opt-in local-first memory candidate extraction, review/undo, verified playbooks and reuse with confidence/fallback.
- Add “learn this task” and schedule-once/daily flow using existing Routines, with safe replay and budgets.

### Phase E — P1 research intelligence
- Add research-strategy selection and source-grounded job-search/listing workflows. Verify exact listings and currentness.
- Improve system instructions and reusable skills without making every task longer or more expensive.

### Phase F — Hardening and release evidence
- Run full quality gates, migration tests, frontend build/E2E, security adversarial tests, benchmarks and actual supported-platform checks available in the environment.
- Update docs (`README.md`, `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/SETUP.md`, `docs/OPERATIONS.md`, `docs/ROADMAP.md`, `docs/VERIFICATION.md`) to describe what really works, requirements, platform limits, how learning is controlled, target semantics and known gaps.

Do not collapse this into one unreviewable mega-refactor. Make coherent, testable changes. If context/time limits force staging, complete all P0 work first and leave a precise continuation report, not a false “done.”

### Final report format (required)

1. **Implemented:** feature, changed files and user-visible behavior.
2. **Verified defects fixed:** exact reproducer, root cause, regression test.
3. **Tests actually run:** commands, exit status and key result. Separate mocked/unit, integration, live provider, browser and real-desktop tests.
4. **UX review:** before/after major screens and viewport sizes actually inspected.
5. **Execution-target guarantee:** tools allowed/blocked in Host and DevBox, including platform limitations.
6. **Learning behavior:** what is auto-saved, what requires review, how local-only is guaranteed, how to undo/delete.
7. **Efficiency results:** before/after actual provider usage and verified task success; do not report simulated-token estimates as real savings.
8. **Remaining issues/blockers:** sorted P0→P3 with exact file/path and next action.
9. **Known unverified behaviors:** especially native macOS permissions, live sites, browser login and Docker/Podman if unavailable in the run environment.
10. **No exaggeration:** don't claim production-ready, parity, bug-free, completely local, or cost-free unless each specific claim has evidence.

**Execute this brief against the current checkout. Inspect first, fix the product in the order above, test the real paths, and finish with evidence.**

---

## 14. Mandatory full UI/UX redesign contract — implementation detail

This section makes the visual redesign a required product deliverable, not a list of optional polish ideas. It supplements Section 7. If a generic statement in Section 7 permits a cosmetic-only result, this section takes precedence.

### 14.1 Product-level UX decision: one canonical conversation experience

Lilly currently has a chat-oriented surface (`Talk.tsx`) and a task-oriented surface (`Workspace.tsx`) with overlapping responsibilities and different composer/control behavior. Do not leave two divergent experiences that each partly implement the same interactions.

- Make the primary surface conversation-first: the user writes a goal, sees a streamed response, sees a concise progress/approval state while work is running, and can expand an execution inspector when they want to understand the details.
- Keep a task-centric workspace/list as a complementary view for active work, history and operations—not as a second independent implementation of the composer, approvals, target selector, research mode and task actions.
- Extract and reuse typed components for the composer, task outcome/status header, execution target selector, research method selector, progress/step timeline, approval card, artifact/source panel, tool metadata and recovery actions.
- Use one authoritative API contract and shared frontend components for sending a task from chat or workspace. Chat and workspace may choose different layouts, but they must not implement different security semantics or global-setting side effects.
- Preserve useful features that already work. Remove redundant UI only after identifying callers, routes, tests and migration implications.

### 14.2 Target layout and responsive geometry

Use these starting design constraints, then adjust based on actual browser screenshots and usability—not personal preference alone:

- Desktop at 1440–1664 CSS px: navigation rail around 220–240 px when expanded; secondary conversation/task list around 270–320 px and collapsible; main content uses remaining width with a readable max-width around 820–960 px for conversation content. The inspector should be a toggled side drawer or split panel around 360–440 px, not permanent empty space.
- At 1280 px: collapse or slim the secondary list before squeezing the composer; keep the main conversation at a comfortable readable width and retain access to execution details.
- Tablet widths: make the secondary list a drawer; avoid three fixed columns.
- Mobile widths (320–430 px): one primary column, navigation drawer, compact header, wrapped action toolbar, full-width composer, full-screen or bottom-sheet inspector/approval dialog, no horizontal page overflow.
- Use responsive CSS grids/flex with minmax(0, 1fr), consistent gap tokens, and `min-width: 0` on nested content. Long URLs, code, filenames and model names must wrap or scroll inside their own panels rather than widen the page.
- The composer must remain visible at the bottom of the active conversation without covering the latest message, focus target or approval controls. Account for safe-area insets on mobile if the app supports mobile browsers.
- Do not reduce font size to solve layout overflow. Change layout and wrapping first.

### 14.3 Visual system — create and use real design tokens

Centralize the visual language in CSS variables/design tokens instead of adding one-off pixel values on each screen. Keep Lilly's forest/cream and restrained coral identity unless screenshot comparison or contrast testing reveals a reason to adjust it.

Define tokens for:

- background/surface/elevated surface/overlay;
- primary, secondary and muted text;
- subtle and strong borders;
- primary, secondary, destructive and quiet button styles;
- semantic success, warning, error, blocked and information states;
- spacing scale, content widths, rail widths and breakpoints;
- control heights, border radii, elevation/shadows and focus rings;
- heading/body/label/mono typography and line heights;
- animation duration/easing, with reduced-motion fallback.

Rules:
- Use one main font family for UI text and limit display serif to branding or selected top-level headings. Avoid large serif task titles inside dense execution panels.
- Do not use color alone for state; pair it with text/icon and accessible names.
- Maintain WCAG AA contrast for normal text and important controls.
- Minimize decorative gradients, excessive cards, pill overload and large empty hero areas inside active task views. Prioritize hierarchy and content density.
- Establish consistent sizes for controls, icon buttons, cards, form labels, section headers and empty states.
- Ensure dark/light/system themes all use the same semantic tokens; test both themes, not just the default.

### 14.4 Screen-by-screen acceptance contract

**A. Main conversation / chat**
- Header shows conversation title, current activity state, and actions for rename/archive/delete only where valid.
- Messages display readable user/assistant hierarchy, timestamps or useful temporal context, Markdown, code copy, safe external links and artifact/source links.
- Streaming updates the existing assistant turn instead of creating duplicate bubbles. After reconnect, reconcile with persisted API state without duplication or loss.
- Auto-scroll only if the user was already near the bottom; when they have scrolled up, preserve their position and show “Jump to latest” with a count of new content if practical.
- Composer has a clear primary input and Send/Stop behavior; Enter/Shift+Enter conventions are visible and consistent. IME composition must not accidentally submit text.
- Secondary controls are grouped into a clearly labeled toolbar/popover, not a long row of tiny selectors. Controls include agent, model (auto by default), task intent where useful, Host/DevBox, research method when relevant, and task-scoped approvals only if supported by the server.
- Disable only the control whose request is in flight. Preserve draft text on errors. Show actionable errors and retry buttons. Never clear draft content after failed submission.
- New conversation/task creation must not generate a hidden global configuration update.

**B. Active task detail / execution inspector**
- Summary header shows goal, execution target, lifecycle status, goal outcome, selected agent/model if available, elapsed time, and cost/token usage only when backed by actual data.
- Separate “what Lilly is doing” (lifecycle) from “did it achieve your goal?” (outcome) and “what evidence supports that?” (verification). Do not collapse these into a single green Done pill.
- Show progress as actual steps/events, not fabricated percentages. If no reliable percentage exists, show steps completed/total only when the total is known; otherwise show current step and elapsed time.
- Step rows use canonical human titles and show running/done/failed/blocked/waiting/skipped distinctly. Details disclose sanitized arguments, concise output previews, duration, approval state, target, and verification evidence. Raw stack traces belong in an expandable diagnostic section.
- Failed/blocked results provide only applicable actions: Retry, Resume, Change target, Open settings/permissions, Open external page, or Ask me to continue. Revalidate safety before retry/resume.
- Add a visible “Continue task” affordance when user input can resume the existing task. If terminal, clearly show whether it creates a new task linked to the prior conversation.

**C. Host/DevBox selector and capability preflight**
- Render as an explicit segmented control or compact selectable cards, with text labels; avoid an unlabeled icon toggle.
- Host option must explain that Lilly may use local files, supported browser and computer controls within granted scope. DevBox option must explain the isolated container, shared-folder boundary, no-network restriction and any required Docker/Podman engine.
- Under the selected target, show a small capability summary and a preflight warning before execution if the requested task requires unsupported capabilities. Do not present blocked tools as available.
- If a request obviously requires a combination (e.g. public web search and local file writing), expose the distinction between task execution target and research/network strategy; do not pretend the DevBox's no-network container can fetch the web.
- Persist the target with the task and display it in history/receipt. A selection change affects only a not-yet-submitted task; changing a queued/running task requires a deliberate supported flow.
- The selector must be testable through keyboard, screen reader and automation. Never make host access the default on unsupported platforms without a clear warning.

**D. Research workflow and results**
- For research tasks, show the interpreted approach before or as the task begins: `Search public sources`, `Use visible browser`, or `Both`. Let the user change it without retyping the prompt.
- If high-impact criteria are missing, ask at most one focused clarification; otherwise state defaults and continue. Show the applied filters (location, seniority, date window, remote, source constraints) where relevant.
- Display live collection activity with source names and states such as searched, fetched, verified, duplicate, expired, blocked and not checked. Do not invent progress counts.
- Job results use structured rows/cards for role, company, location/remote, posted date (or “not stated”), experience, published salary (or “not stated”), direct link, source and last-checked timestamp. Keep fit reasons separate from factual fields.
- Sources are clickable and open safely. Provide a source/evidence drawer showing why an item was included and what was not verifiable. Clearly label third-party aggregators and suspected duplicates.
- Offer export to CSV/Markdown only if implemented end-to-end; verify that downloaded content matches the displayed rows.

**E. Approvals**
- Clearly identify the exact operation, execution target, resource/path/URL, data classification, why approval is needed and the potential impact.
- For file edits show a readable diff; for destructive changes show what can be deleted/overwritten; for model data grants show the exact data classification and model/provider.
- Put Approve and Deny close together but visually distinct; destructive approval cannot be the easiest accidental click. Use explicit confirmation for unusually broad or irreversible actions where justified.
- Show expiration and changed/expired approval state. If the approved payload changes—including target—require a new approval.
- After decision, disable repeated submission while awaiting the server response; handle conflicts by refreshing actual approval state instead of showing false success.

**F. Settings and health**
- Group settings by user mental model: Models & privacy, Computer access, Browser, Execution & DevBox, Learning & memory, Routines, Integrations, Data & backups, Appearance, Advanced diagnostics.
- Each setting says whether it is global, per-agent, per-routine or per-task. Explain security implications before modifying high-impact settings.
- Show live diagnostics from actual APIs: provider configured/reachable, local model loaded/available, computer permissions, browser readiness, container engine/image status, routine scheduler health, database/backups. Distinguish “not configured”, “unsupported”, “checking”, “unavailable” and “error.”
- Save buttons reflect dirty state; reset/cancel actually restores the server-backed value; failed save keeps edits and displays field-level or clear global errors. Avoid overwriting concurrent settings changes by sending stale whole-settings payloads when a narrow patch is possible.
- Secrets are masked, never prefilled into text fields after load and never exposed in error messages.

**G. Memory and learning review**
- Separate saved facts, learned workflow candidates, approved playbooks and rejected/archived candidates. Provide provenance/source task, created/last-used timestamps, confidence/calibration evidence where available, scope and local-vs-hosted extraction status.
- Provide Review, Edit, Approve/Activate, Reject, Undo/Version history and Delete. Make deletion/clear operations explicit and confirm irreversible bulk changes.
- Show why an item was retrieved for a task, and allow a user to correct an outdated/incorrect memory. A memory correction must update the stored record and invalidate stale indexes/caches.
- Make it obvious that memory is not model-weight training. If Lilly uses only a local classifier/playbook library and stored facts, say so accurately.

**H. Routines and playbooks**
- Display schedule and timezone, execution target, agent, playbook version, permission requirements, resource budgets, next run, last outcome and last failure reason.
- Controls: Run now, Pause/Resume, Edit, View workflow, View history, Change target (with revalidation), Duplicate and Delete. Disable unavailable actions and explain why.
- Preview the next scheduled time and show DST/timezone interpretation. Do not rely on a client-only timer as the scheduler source of truth.
- The routine screen must distinguish task outcome success from “the scheduled job started.”

**I. Tool/skill registry and activity**
- Every registered tool and skill has canonical display metadata from one source: stable ID, human title, description, icon/category, risk/approval hint, supported targets, required module/permissions and availability reason. Add a completeness test that enumerates the registry and fails when metadata is missing.
- Built-in, agent-sheet, MCP and learned playbooks must have visibly different source/trust labels.
- Activity filters include task, time, event type, outcome, execution target and failures. Show event-chain verification as a real result from the server, not a decorative shield.
- Sensitive values are redacted. Raw JSON and low-level traces are hidden under Advanced, with copy/export only when safe and intentional.

### 14.5 Interaction inventory — no inert controls

Create an inventory of every rendered clickable/input control across all routes, including dialog buttons, keyboard shortcuts, dropdown actions, tabs, switches, links, empty-state CTAs and inline retry/recovery actions. For every item, document: source component, API/handler, state mutation, loading state, success state, error state and a test.

Then automate that inventory where possible. Test that:
- navigation reaches the intended route and retains/clears selection correctly;
- form submit sends the exact current draft once;
- all toggles persist and reflect server state after reload;
- a failed API response is shown without losing draft or creating fake success;
- destructive action confirmation performs the named operation only;
- dialogs trap focus and restore focus on close;
- live task changes update the correct row/details without duplicating content;
- Stop All disables new scheduling immediately and the backend remains authoritative;
- inaccessible capabilities are disabled with a reason, not hidden behind controls that fail later.

### 14.6 Visual QA is mandatory

The code agent must not claim the redesign is complete after a TypeScript build alone.

1. Run the actual frontend build and all existing web unit/E2E tests after checking package scripts and prerequisites.
2. Launch Lilly in an available test environment using test data/fixtures only. Do not use the user's real conversations, keys or browser profile for screenshots.
3. Capture screenshots of: first run, empty chat, active task, blocked task, needs-approval card, completed verified result, failed result/retry, host-vs-DevBox selection, research results, learning review, routine list/edit, settings/health and mobile navigation.
4. Inspect at least 1280, 1440 and 1664 px desktop viewports plus 390 px mobile; inspect light and dark themes. Also test 320 px if mobile is claimed. Record what was actually viewed and any environment limitation.
5. Compare the active-task screenshot against the supplied reference: remove cramped composer controls and excessive unused space; main content must use the available width naturally; task outcome must never be falsely green; tool rows need understandable labels; the target/method must be easy to inspect.
6. Fix visible overlap, clipped menus, scroll traps, modal overflow, wrong focus, low contrast, inconsistent spacing and console/network errors before completion.
7. If screenshots or a graphical runtime cannot be produced in the available environment, do not pretend visual review happened. Still run static/E2E tests and give exact manual visual-check steps.

### 14.7 UI quality metrics

Do not invent subjective “10/10” claims. Record measurable gates:
- 0 known inert visible controls in the audited inventory;
- 0 task screens claiming verified success without persisted goal outcome and qualifying evidence;
- 0 unlabelled tools in registry completeness tests;
- 0 unintended global setting changes from task-level controls;
- 0 horizontal viewport overflow at supported widths in core flows;
- all primary actions keyboard reachable with visible focus;
- no duplicate/lost messages in scripted SSE disconnect/reconnect tests;
- no uncaught frontend console errors or failed local API requests in tested happy/error flows;
- every unsupported target/capability produces a plain-language preflight or runtime explanation;
- screenshots and test reports checked into an appropriate local test-artifact folder only if repository conventions allow it; never commit user-specific output.

---

## 15. Additional end-to-end completion contract

Before declaring the work complete, walk at least one whole flow across each major vertical slice rather than testing APIs in isolation:

### Flow A — Local laptop task

User selects This Laptop → enters “open the browser and play a song” → Lilly verifies computer/browser permission and capability → selects browser or computer tools based on actual availability → runs approved steps → observes fresh post-action state → either proves playback/result or marks `needs_user`/`blocked`/`partial` → user sees accurate status, evidence and next action. A successful tool call or opened website alone is not sufficient proof of playback.

### Flow B — Isolated coding task

User selects DevBox and a shared folder → Lilly preflights engine/image/folder → runs code only through the container tool → runs tests inside the same allowed environment → confirms exit status and produced artifacts → summarizes exact changes. Attempted host shell/browser/desktop and network egress must be denied. Never escape to the host to make tests pass.

### Flow C — Research and job listing

User asks for current SWE job openings → task classifier determines research is needed → asks one crucial missing filter only if necessary → uses public search/fetch, visible browser, or both based on selected method and permissions → captures direct listings, current status and evidence → deduplicates and ranks → generates report/table/export → checks links and artifact contents → records limits and exact source-check time. If sources cannot be reached, the outcome is partial/blocked, not successful completion.

### Flow D — Learn and repeat

User runs a multi-step task successfully → Lilly proposes a memory/playbook with provenance → the user reviews/approves or a configured safe auto-save rule accepts it → playbook is versioned and tested → user explicitly creates a daily routine → each run validates the current permissions/target and refreshes inputs → outcomes are stored → failure pauses/alerts by policy → user can edit, disable, roll back or delete the learned workflow.

### Flow E — Failure and recovery

Provider rate limit, browser incompatibility, expired approval or tool timeout occurs → the exact failure is recorded → no false success or unbounded retry → the UI offers relevant recovery actions → retry avoids repeating completed non-idempotent side effects → the final task outcome and receipt reflect reality.

### Flow F — Privacy boundary

User chooses Local only → every primary/fallback provider route and learning/extraction path uses an allowed local model/endpoint or safely stops → a test network monitor confirms no unintended remote inference call → optional web research remains separately explained and controlled → the UI distinguishes local inference from external website access.

For every flow, save a test trace/report showing initial input, selected target/method, important tool decisions, resulting artifacts, evidence/outcome and actual test command/result. Use fixtures for routine CI and separate opt-in tests for real machine/provider behavior.

---

## 16. Final instruction to the coding agent

This is a full product implementation and visual redesign task, not a documentation-only task. Do not implement all phases as one giant, unreviewable rewrite. Execute phase gates, inspect the diff, add regression tests as you go, and continue until every feasible P0/P1 item and the visual acceptance contract have been evaluated. If scope or environment prevents complete work in one run, finish the highest-priority safe slice, leave the product passing the gates for that slice, and state exactly what remains; never relabel unfinished work as complete.
