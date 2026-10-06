# Lilly 2.0 Architecture

Lilly is one local process with one production execution path: `SessionRuntime`
owns durable task/session state, `AgentLoop` performs the work, `Laya` supplies
typed System-1 advice, `ModelBroker` selects a capable healthy model, and the
policy-bound capability registry controls every tool call.

## Runtime flow

1. `POST /api/tasks` authenticates the request and the `Orchestrator` creates a
   durable task and a `SessionRuntime` session.
2. `AgentLoop` observes the task, classifies its intent, discovers the complete
   policy-filtered capability catalog, and asks `System1Engine` for typed
   routing and verification advice.
3. `ModelBroker` chooses a model for the current turn using capabilities,
   health, quota, cost, latency and task history. A later turn may use a
   different eligible model.
4. Tools run through deterministic policy and approval handling. Computer work
   follows `observe -> act -> fresh observation -> verify -> recover`; stale
   frame IDs are rejected.
5. The session records lifecycle, state, events, artifacts and routing data.
   On restart, unfinished tasks are marked interrupted and can only be
   re-driven through the explicit ambiguity confirmation path.
6. The browser receives task and text events over SSE and refreshes task state
   from the API. The task workspace does not maintain a second task database.

## Core boundaries

| Component | Responsibility |
| --- | --- |
| `domain/policy.py` | Deterministic risk, label, mode, permission and approval decisions |
| `domain/tools_registry.py` | Typed capability schemas, namespaces and risk metadata |
| `engine/session_runtime.py` | Durable session authority, recovery, events, artifacts and routing history |
| `engine/agent_loop.py` | The only normal interactive reasoning/execution loop |
| `decide/system1.py` | Typed Laya decisions with deterministic fallback |
| `providers/model_broker.py` | Per-turn provider/model selection and fallback |
| `tools/computer_runtime.py` | Persistent screen/AX/DOM state, grounding, actions and verification |
| `tools/devbox/` | Persistent isolated command environment |
| `ui/` and `web/` | Task-first live workspace over the API/event stream |

## Compatibility boundaries

`engine.mode = "plan"` is deprecated and isolated. It remains for existing
callers and deterministic skills; normal interactive tasks do not depend on
it. The planner is not a second interactive runtime.

`providers.router.ModelRouter` is an import alias for `ModelBroker`, retained
for installed integrations. New code imports `ModelBroker` directly.

`core.shortlist` remains a small compatibility utility for old decision tests
and integrations. The production AgentLoop never hides capabilities using a
ranked shortlist: it passes the full policy-filtered catalog and uses namespace
discovery for lazy schemas.

## Security invariant

Laya and generative models recommend. Deterministic policy, permissions,
sandboxing, stale-state checks and auditing decide what can happen. `MANUAL`,
`AUTO` and `OFF` change prompting only; `OFF` cannot bypass hard denies,
permissions, sandboxing or audit records.

## Persistence

The SQLite database uses one writer and read connections. Tasks, sessions,
events, approvals, memory, artifacts and settings are persisted under
`~/.lilly`. Startup reconciles interrupted work before new tasks run.
