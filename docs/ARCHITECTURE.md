# Architecture

Lilly is one local Python process (`lilly run`) that serves a React interface and a JSON/SSE API on `127.0.0.1`, runs tasks, and stores everything in a single SQLite file.

## Principle

**The planner proposes, the policy disposes.** A language model may suggest a plan, but nothing it says can raise its own permissions. Every step is judged by `domain/policy.py::decide()`, a pure function of the tool's pinned risk, the task's data label and taint, the agent's access mode and the allowed folders. Risk and labels come only from the code-defined registry (`domain/tools_registry.py`), never from model output.

## Layers

Imports go strictly downward; `tests/unit/test_import_boundaries.py` enforces it.

| Rank | Package | Role |
| --- | --- | --- |
| 0 | `domain` | Pure rules and types: labels, risk, policy, plans, skills, settings, grants, errors. Standard library only. |
| 0 | `obs` | Logging with secret redaction. |
| 1 | `core` | Rate limiters, daily quotas, circuit breaker, model pool and routing. |
| 2 | `store` | SQLite: schema and migrations, single writer, tasks, events (hash-chained), approvals, memory, spaces/notes, agents, retention and backup. |
| 3 | `providers` | Mistral, OpenAI, OpenRouter, Gemini and Ollama adapters (streaming where the provider supports it); key stores (Keychain / `0600` file); the model router; the local-model gate. |
| 3 | `tools` | Built-in tools: files, data, web, memory, notes (read, and `notes.write`, which always asks), system, llm, computer control, the agent browser (`tools/browser`), MCP clients (`tools/mcp`) and the devbox (`tools/devbox`). |
| 3 | `decide` | Quick deciders (rules, search ranker, small local model, Laya) and the Laya installer and worker. Advice only. |
| 4 | `engine` | Planner, runner, lane executor, orchestrator (submit, cancel, Stop all, and `cancel_agent_tasks`, called when an agent is narrowed or deleted: see `store.agents.narrows`), approval service, decision pipeline, streaming throttle, event bus. |
| 5 | `app` | `Runtime`: wires everything, applies settings live, housekeeping (power, prune, backup, routines), `LayaService`, data folder layout. |
| 6 | `ui` | Starlette app: security (`security.py`), API handlers (`api_*.py`), static single-page app. |
| 6 | `bridges` | Chat apps (Telegram). `ui` and `bridges` are siblings and never import each other; the daemon connects them. |
| 7 | `daemon` | The `lilly` command, the server process (wires the chat bridge into the web app), the macOS login item. |

`providers`, `tools` and `decide` are siblings at rank 3, as are `ui` and `bridges` at rank 6.

The interface source is in `web/` (React 19, Vite, TypeScript, zustand); `npm run build` writes the static files to `src/lilly/web`, which ship inside the Python package so Lilly runs without Node.

## A request, end to end (Agent Loop)

1. The browser posts a message to `POST /api/tasks`. `guarded()` checks the session cookie, CSRF token and origin.
2. The orchestrator creates a task (label PUBLIC, untainted), records it, and starts the runner.
3. The runner invokes `AgentLoop` (rank 4). Initial messages are built: system prompt (`AGENT_SYSTEM`), agent's pet sheet instructions, visible tools catalog, recent conversation answers, and the user's goal.
4. **Turn-by-turn dynamic execution**:
   - **Role selection**: Turn 1 and turns following escalation use `plan` role; subsequent tool-calling turns use `act`; final reserved budget turn uses `write` with `tool_choice="none"`.
   - **Model call**: Dispatched via `StepExecutor.with_model_permission`. If a model needs user permission for sensitive data (`Label.PERSONAL`), an approval request is triggered and the loop resumes upon decision.
   - **Tool execution**: Calls in each turn are validated against their schemas. Read-only, unconfirmed, non-serial calls eligible under policy execute concurrently via `LaneScheduler`. Mutating or confirm steps execute serially.
   - **Observations**: Every tool call generates a structured observation (`RESULT {step_id} ...`). Policy blocks, tool errors, and user declines generate observations without aborting the task.
   - **Loop guard & Escalation**: Step executions trigger `_advise()`. On first `LOOPING` detection, `NOTICE_LOOPING` is injected; a second consecutive loop aborts. Consecutive invalid turns escalate to the `plan` model once.
   - **Completion**: When the model answers directly without tool calls, or budget exhaustion forces a final answer, the final response is recorded and the task transitions to `DONE`.

### Legacy plan path

Tasks configured with skills or `engine.mode == "plan"` use the pre-2.0 ahead-of-time planner (`_execute_plan()`). The planner generates a static JSON plan (`llm.work` as final step), validates references, pre-flights policy, and executes steps through `LaneScheduler`.

## Data

Everything is in `~/.lilly` (override with `LILLY_HOME`): `lilly.db` (SQLite, WAL, FTS5), `config/` (settings, access token, cookie secret, key file if no keychain), `backups/`, `log/`. A single writer thread owns all writes; readers use their own connections.

## Deliberate omissions

Not built, on purpose: email, voice, an OAuth gateway, passkeys, push notifications, and exposing Lilly beyond this computer. Not built yet, and listed as such in `ROADMAP.md`: agent-built extensions, learned playbooks, model-per-step routing, a desktop or phone screen view.

## Decision layer

`decide/` and `engine/decisions.py`. Six questions (which tools to show the planner, is a run looping, does text read as orders, pick one of a list, and the two Laya assist questions below) go through a chain of deciders per question. A decider returns one of the options code supplied, with a confidence, or nothing. Advice can only add caution; nothing in the layer can express "allow" and nothing in it imports the policy. Deciders are resolved at the moment of each question (`DecisionPipeline(deciders=callable)`), so installing or removing Laya takes effect without a restart. Laya runs in its own process (`decide/laya_worker.py`) inside `~/.lilly/addons/laya`, loaded on first use and let go when idle. Setup is guided and runs from the installer by default: `laya_install.preflight` (no download), the installer, and `laya_selftest.self_test` (the real decider and worker asked three questions with known answers, through `LayaDecider.ready()`; the service and `lilly laya test` use a decider of their own and close it straight after). The user-facing guide is [LAYA.md](LAYA.md).

**Laya assist** (optional, both off by default). Two yes/no questions have Laya judge what the language model does against the user's request and the agent's standing instructions. *Plan check* (`Kind.PLAN`, FITS or OFF): before a step that is not read-only (risk above R0) would run on its own, Laya is asked whether it serves the request. If it answers OFF, a step policy would ALLOW becomes NEEDS_APPROVAL (`add_doubt` in `engine/steps.py`); NEEDS_APPROVAL and DENY are never touched, so the layer still only adds caution, and the approval stays bound to the payload hash as before. *Reply check* (`Kind.REPLY`, FOLLOWS or DRIFTS): after the reply is saved and the task is DONE, `engine/replycheck.py` asks in the background, records a `reply_check` task event and publishes a bus event; the task detail API shows it as `reply_check` (`follows`, `drifts` or null). It never rewrites or blocks a reply, is capped at 32 waiting checks, and is cancelled when the orchestrator closes. Both are bounded texts built by `plan_state` / `reply_state` in `domain/decisions.py`. Enabling either (`with_assist`) starts it as shadow (watch only: logged, nothing acts) because Laya's precision on these questions is unmeasured; the owner switches to acting after reading `lilly decisions report`. When a task starts the pipeline calls `prepare(kind)`, which warms deciders that satisfy the `Warmable` protocol, so Laya is loaded before it is needed. Turning Laya off turns both checks off.

## Streaming

A provider that streams reports the whole text so far through `CompletionRequest.on_text`. `engine/stream.py::TextStream` throttles to ten updates a second, keeps the last 12,000 characters and publishes `{"type":"text"}` events on the bus. These are not stored in the hash-chained log. The interface keeps them in memory per task, clears them when the task ends and refreshes the task only while the tab is visible.

## Chat apps

`bridges/telegram.py` (API calls, outbound long polling only, no open port) and `bridges/service.py` (pairing, allowlist by numeric account id, rate limit, size cap). Pure rules are in `domain/bridges.py`. Messages from chat start tainted tasks and reach only agents marked reachable from chat. Approval buttons carry the exact action and a single-use id. `ui/api_bridges.py` talks to the running bridge through the `BridgeControl` protocol on `app.state.bridges`, handed in by the daemon.

## Devbox

`domain/devbox.py` holds the rules and builds the container command: no network, no engine socket, a read-only root, all capabilities dropped, one bind mount, CPU, memory and process caps. `tools/devbox/engines.py` runs Docker or Podman by command line (fixed argument lists, no shell). `tools/devbox/manager.py` creates the box on first use, runs one command at a time, stops it when idle, removes it after a longer idle time, on timeout, on cancel, on Stop all and at shutdown, and rebuilds it when its settings changed or when it was left by an earlier run. `devbox.run` streams its output through the same `on_text` path as a model reply.

## Resource discipline

Nothing runs unless something needs it, and what was started is stopped again:

| Part | Rule |
| --- | --- |
| Devbox | Warms in the background when a plan includes a devbox step; sleeps after 10 min idle (wakes in about a second); removed after 24 h idle |
| Agent browser | Tabs close after 2 min, browser quits after 5 min idle |
| Local models | One call at a time; one model in memory; unloaded after `local_unload_s` (default 300 s); the previous model is unloaded on a switch |
| Laya | Loaded on first use, let go after 90 s idle, left alone after three timeouts |
| MCP servers | Started on first use, stopped after idle |
| Routines | Housekeeping sleeps until the next routine is due (at most 60 s when idle) and wakes when a routine or task changes; 10 s while tasks run |
| Chat bridge | Off until enabled; long polling with back-off |
| Live view | A picture only when the interface asks, never opens a tab or keeps the browser awake |
| Hidden browser tab | No polling and no live refresh |

## Computer control, limits and pets

* `tools/computer.py` holds six tools (open link, open app, processes, stop process, notify, run command). Their `ToolSpec.confirm` flag makes `domain/policy.py` require approval in every mode. They are visible to an agent only when the `computer` module is on and `agents.computer_allowed` is set (`engine/orchestrator.py::_scoped_deps`).
* `LimitSettings` (tasks at once, step timeout, task minutes; bounds in `LIMIT_BOUNDS`) is read live by the runner; the orchestrator's `Gate` resizes without restarting, including for queued work.
* `GET /api/resources` returns machine stats, Lilly's own footprint, tasks, limits and model quotas for the Resources screen.
* Pets are original SVGs in `web/src/ui/Pet.tsx`; the pet id is stored on the agent (migration `0002`). States come from task status.

## Routines

* `domain/schedule.py` is pure: parse and validate a schedule, compute the next run (time zone passed in), describe it in words.
* `store/routines.py` (migration `0003`) keeps the request, schedule, next run and how the last run went.
* `engine/scheduler.py` is driven by the runtime's housekeeping loop, which sleeps until the next routine is due. It starts due routines through `Orchestrator.submit`, skips a slot while the previous run is active, and records finished runs on later ticks. It owns no timers, so there is nothing to leak or restart.
* `ui/api_routines.py` exposes `/api/routines` (list, create, patch including `enabled`, delete, `/run`). `POST /api/stop` also pauses all routines.
