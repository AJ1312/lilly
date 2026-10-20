# Lilly — Fine-Grained Repository Audit

**Audit target:** `AJ1312/lilly`, current `master` as observed on 20 October 2026  
**Latest observed commit:** [`3574221`](https://github.com/AJ1312/lilly/commit/3574221bc708a9b331772cb68c00e97570802404) — “Rebuild frontend from scratch…”  
**Scope:** React/Vite frontend, Starlette API contracts, task/conversation flows, routines/memory/approvals, model routing/capacity and latency, settings/options, test/benchmark quality.

## Important limitation

This is a source-level audit of the current GitHub branch, not a claim that the application was run end-to-end. A local `git clone` attempt failed because the environment could not resolve `github.com`; no local tests or real-provider latency measurements were executed. Findings below are labelled as code-confirmed when the mismatch is directly visible in source, or as a risk/hypothesis when runtime conditions affect reproducibility. “Fine-grained” does not mean a guarantee that every possible defect has been found.

## Executive summary

The highest-priority issues are not just missing dropdown entries. Several current frontend flows do not match their backend contracts, and there is a concrete model-routing design flaw that can invalidate the broker's model choice. The slow-response investigation has two especially important leads:

1. **ModelBroker picks a model, but CapacityManager chooses the actual model independently.** The broker's model-tier/task suitability decision is not passed into capacity acquisition. This can route a complex task to a different lane/model than the broker selected, and stored routing history can describe the wrong model.
2. **A capacity timeout can re-enter the same wait without excluding the model that timed out.** The default interactive wait is 60 seconds. The `NoModelAvailable` catch retries selection with the same `skip` set, so a single-model or exhausted-quota setup can repeatedly wait rather than fail promptly.
3. **Talk can look frozen even after backend progress.** It sends `thread_id` where the API expects `conversation_id`, and its selected-thread loader only fetches on thread selection. It does not refresh the open thread as task states/results change.
4. **Routine creation is currently incompatible with the backend schedule schema.** The UI sends `cron` or `interval_s`; the API requires a `schedule` object with `kind: every`/`every_minutes` or `kind: at`/`at`/`days`.
5. **Memory and approval screens use stale frontend data shapes.** Memory sends `fact`/`category` while the API expects `text`/`tags`; approval cards expect `tool`, `why`, `risk`, and `target` fields which the current serializer does not return.

There are also major product-control omissions in the rebuilt frontend: Notes/spaces, Telegram/chat-app setup, shared file roots, safety freedom mode, detailed browser settings, session-token management, and several engine/capacity/learning settings are not exposed in the current UI even though the backend or README describes them.

## Severity scale

- **P1 — High:** a core workflow is broken, the visible behaviour can mislead the user, a security-sensitive control loses important context, or latency can become unbounded/very long.
- **P2 — Medium:** a feature is inaccessible or degraded, telemetry/diagnostics are misleading, or valid backend options cannot be selected.
- **P3 — Lower:** quality, accessibility, usability, or validation gaps that should be fixed but are less likely to block core operation.

---

# 1. Highest-priority confirmed findings

## LLY-001 — ModelBroker's smart routing decision is not enforced during execution — P1

**Evidence:** [`model_broker.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L469-L616), especially candidate scoring and selection; [`complete()`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L687-L839); [`capacity.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/core/capacity.py#L150-L300).

`ModelBroker.complete()` calls `select_model()` and records the result in `_routing_history`, but then calls `capacity.acquire()` with the original user `pin` (if any), not the selected `routing.model_entry.name`. `CapacityManager.acquire()` performs its own model choice using lane, utilization, limits, and availability. It can return a different entry. The broker then overwrites `entry` with `lease.entry` and executes that model.

**Impact:** task complexity, strong/quick tier, measured/expected latency and other broker suitability decisions may not determine the model that actually runs. A high-complexity request can be sent to a different/lower-lane model. The recorded routing history can say model A was selected while the provider call actually used model B. This is both a performance/quality bug and an observability-integrity bug.

**Fix:** establish one canonical routing decision. Either let `CapacityManager` accept the broker's ranked candidates/preferences and choose the best currently eligible model, or make the capacity layer return the chosen model to the broker before finalising routing telemetry. Preserve hard capability, data-label, quota, and approval checks. Record the **actual lease model** and the intended preferred model separately. Add tests asserting model choice for QUICK/STRONG/VISION/tool-required tasks and a test where the preferred model is busy but an eligible fallback is used.

## LLY-002 — Model capacity timeout can cause repeated long waits — P1

**Evidence:** [`model_broker.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L727-L839), especially the `except NoModelAvailable` path; [`settings.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/domain/settings.py#L132-L148) for default capacity waits; [`capacity.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/core/capacity.py#L150-L300).

`capacity.acquire()` can raise `NoModelAvailable` after waiting for capacity. The broker catches that exception and re-runs `select_model()` with `skip=frozenset(skip)`, but the timed-out model is not added to `skip` in that path. If there is only one usable model, or the same model still scores highest while its capacity/quota is unavailable, the loop can select it again and start another wait. The default interactive wait is 60 seconds; this can make a request appear hung for a minute or multiple minutes before task/step cancellation stops it.

**Impact:** a particularly plausible explanation for long stalls when only one provider is configured, a rate/token quota is exhausted, or the provider/model is unavailable due to capacity constraints.

**Fix:** distinguish provider-call failures from capacity-wait expiry. Use a single deadline for the whole completion; on capacity expiry, either try a genuinely different eligible model, use bounded exponential backoff with a strict retry budget, or return a clear availability error. Never loop indefinitely on an unchanged candidate/availability state. Add deterministic tests for one model at daily quota, all models busy, and model capacity that never becomes available.

## LLY-003 — Talk sends `thread_id` instead of the API's `conversation_id` — P1

**Evidence:** [`Talk.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Talk.tsx#L219-L260); [`api_chat.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_chat.py#L75-L125).

The composer submits `payload.thread_id = selectedThreadId`. The `/api/tasks` handler only reads `conversation_id`. The unknown `thread_id` field is ignored, so the backend can create a new conversation rather than attaching the task to the selected one. The response then has a new `conversation_id`, and Talk switches to that new thread.

**Impact:** conversation continuity breaks; follow-up prompts may be detached from the thread the user selected, and the UI can unexpectedly jump to a new conversation.

**Fix:** send `conversation_id: selectedThreadId`; add an integration test that submits two tasks from an existing thread and asserts both task rows have the same `conversation_id` and the thread does not change unexpectedly.

## LLY-004 — Talk does not refresh the open thread as the task progresses — P1

**Evidence:** [`Talk.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Talk.tsx#L165-L260); [`events.ts`](https://github.com/AJ1312/lilly/blob/master/web/src/events.ts#L82-L121); [`api_chat.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_chat.py#L185-L200).

Talk fetches `/api/threads/{id}` when `selectedThreadId` changes and refreshes it immediately after sending a task only in the same-thread branch. It does not subscribe to task-specific events or refetch the selected thread when global task-state events arrive. The global `EventBus` calls `store.bump()`, but Talk does not use that tick to reload its current messages/tasks. Its scroll effect depends only on `messages.length` and `threadTasks.length`, not streaming text/state changes.

**Impact:** the task may be running or finished in the backend while Talk displays stale task/message state. This can look like the model is extremely slow or never returns, even when progress is being recorded elsewhere (for example, Workspace).

**Fix:** subscribe to the selected task's event stream/polling path, refresh the thread on task-created/state/final events, deduplicate resumed events, and reconcile persisted task state after SSE reconnect. Add a “Jump to latest” control and avoid forced auto-scroll when the user has intentionally scrolled up.

## LLY-005 — Routine creation sends a schedule shape the backend cannot parse — P1

**Evidence:** [`Routines.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Routines.tsx#L75-L125) and [`Routines.tsx` creator modal](https://github.com/AJ1312/lilly/blob/master/web/src/views/Routines.tsx#L300-L381); [`api_routines.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_routines.py#L27-L70); [`schedule.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/domain/schedule.py#L1-L65).

The UI constructs either `payload.cron` or `payload.interval_s`. The API ignores both and calls `parse_schedule(data.get("schedule"))`. `parse_schedule()` requires an object with either `{kind: "every", every_minutes: N}` or `{kind: "at", at: "HH:MM", days: [...]}`. Therefore the current create request has no `schedule` object and is rejected. Update also ignores the UI's cron/interval fields and cannot change the schedule. Additionally, the UI offers “Cron Expression” even though the backend does not implement cron parsing, and its interval input allows 1–4 minutes despite the backend minimum being 5.

**Impact:** creating routines is broken; editing a routine's schedule is not supported by the current form.

**Fix:** build the backend's typed `schedule` object directly. Replace cron entry with the actual supported options: every 5 minutes–7 days, or a chosen time and weekdays. Validate interval bounds client-side. Add API/React integration tests for create, update, daily schedule, weekday schedule, and minimum/maximum intervals.

## LLY-006 — Memory UI and API schemas do not match — P1

**Evidence:** [`Memory.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Memory.tsx#L20-L100); [`api_data.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_data.py#L65-L100); [`support.py` serializers](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/support.py#L145-L165); [`store/memory.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/store/memory.py#L20-L95); [`types.ts`](https://github.com/AJ1312/lilly/blob/master/web/src/types.ts#L130-L145).

The UI expects memory records with `fact`, `category`, `created_at`, and `updated_at`, and submits `{fact, category}`. The API accepts `text`, `label`, and `tags`; serialized records return `text`, `label`, `source`, `at`, and `tags`. These are not alias-compatible. Creating memory sends no `text`, so the backend's required nonempty-text validation fails. Editing sends `fact`, which the backend ignores, so it can report success without updating the stored text. Listing uses `item.fact`, so saved entries are displayed/searched as empty; the category filter cannot match the backend's tags.

**Impact:** the Memory screen's main add/edit/list flow is broken or misleading.

**Fix:** define one shared contract. Either adapt the frontend to `text/label/tags/at`, or intentionally version the API and map `fact/category` to stored text/tags. Do not show a success toast until the returned saved record confirms the mutation. Add tests for add/list/edit/delete and category/tag filtering.

## LLY-007 — Approval cards depend on fields the API does not return — P1 (security-sensitive UX)

**Evidence:** [`Approvals.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Approvals.tsx#L75-L150); [`Talk.tsx` approval banner](https://github.com/AJ1312/lilly/blob/master/web/src/views/Talk.tsx#L450-L520); [`support.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/support.py#L130-L145).

The frontend renders `appr.risk`, `appr.target`, `appr.tool`, and `appr.why`. The current `approval_json()` serializer returns `id`, `task_id`, `step_id`, `kind`, `summary`, `payload`, `payload_hash`, `status`, and timestamps; it does not return `risk`, `target`, `tool`, or `why` under those names. As a result, risk/target badges and action summary/tool names can be blank or undefined on both the Approvals page and Talk's inline approval banner.

**Impact:** the user may be asked to approve an action without the intended clear description, target, or risk context. The payload and hash may still be visible, but that does not replace a readable review summary.

**Fix:** make the API return a documented approval DTO that includes the actual tool/action, human-readable summary, target, risk, and exact payload. Do not invent risk or target values on the client. Block approval if required descriptive metadata is missing; add tests asserting that every approval has enough information to make a safe decision.

## LLY-008 — Invalid execution targets silently default to Host for routines/playbooks — P1 (fail-closed issue)

**Evidence:** [`api_routines.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_routines.py#L31-L45); [`api_data.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_data.py#L430-L455); compare with the stricter [`submit_task()` validation](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_chat.py#L95-L125).

When a routine or playbook receives an invalid `target`, the API catches `ValueError` and silently assigns `ExecutionTarget.HOST`. Task submission instead rejects an unknown target. A malformed or stale explicit request can therefore become a Host execution rather than failing. The repository's own `refactor.md` says not to silently fall back from an explicitly chosen execution target.

**Impact:** potentially surprising execution on the host when the caller intended DevBox or sent an invalid/unsupported target. This is particularly important because Host access and DevBox isolation have different risk boundaries.

**Fix:** reject invalid target values with `ValidationFailed` in all create/update APIs. Never coerce an explicit invalid target to Host. Validate routine/playbook `target` the same way as task submission, with tests proving malformed values cannot create Host-target work.

## LLY-009 — Agent prompt preview expects a `prompt` field that the endpoint does not return — P1/P2

**Evidence:** [`Agents.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Agents.tsx#L95-L118); [`api_data.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_data.py#L294-L307).

The frontend reads `{prompt: string}` and calls `setPromptPreview(res.prompt)`. The API returns separate `persona`, `plan`, `act`, `write`, and `check` fields, not `prompt`. The preview request succeeds but the displayed preview is empty/undefined.

**Fix:** either render the five returned role prompts in a tabbed/sectioned preview or change the API to return the expected single prompt. Add a test that verifies the preview contains the saved agent instructions.

---

# 2. Model latency and routing findings

## LLY-010 — The latency field advertised by the router is not used to rank models — P1/P2

**Evidence:** [`ModelCapabilityProfile`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L65-L90); [`_score_model_for_task()`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L300-L430); [`_record_call()`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L888-L920).

`ModelCapabilityProfile` defines `expected_latency`, and call latency plus capacity wait are written to the model-call ledger, but `_score_model_for_task()` does not use observed latency/first-token latency in its suitability score. Actual execution is then subject to the separate CapacityManager choice described in LLY-001. This means “latency-aware routing” is not currently demonstrated by the source path.

**Fix:** record and expose per-provider/model p50/p95 time-to-first-token, provider completion time, and queue wait separately. Feed a bounded rolling latency estimate into the one canonical router, without allowing a fast but incapable model to win. Add live-provider benchmarks; do not infer latency from provider name or the free/quick tag alone.

## LLY-011 — Ollama deliberately applies a 120-second minimum inference deadline — P2, can look very slow

**Evidence:** [`ollama.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/ollama.py#L25-L75), specifically `MIN_DEADLINE_S = 120.0` and `asyncio.timeout(max(req.deadline_s, MIN_DEADLINE_S))`; [`model_broker.py` model test](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L922-L949).

A cold Ollama call can be allowed to run for at least 120 seconds even if its request deadline is shorter. The Models screen labels the action “Test Ping”, but the endpoint performs a real completion (“Reply with the single word: ok”), not a lightweight connectivity ping. A cold model load can therefore leave “Testing…” displayed for a long time.

**Fix:** separate a fast health/connectivity probe from an actual generation test. Show “Warming model”/first-load progress and make the longer deadline explicit. Keep the longer timeout where necessary for real inference, but don't label it as a ping.

## LLY-012 — Failed model tests discard the backend's useful error — P2

**Evidence:** [`Models.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Models.tsx#L98-L120); [`api_admin.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_admin.py#L145-L165); [`ModelBroker.test()`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L922-L949).

The backend returns `{ok: false, error: "..."}` on failure. The frontend types only `ok`, `latency_ms`, and optional `reply`; it ignores `error` and substitutes “Model test failed”. Because the endpoint normally returns HTTP 200 even for `{ok:false}`, the catch block does not preserve the backend explanation.

**Fix:** include `error?: string` in the response type and render it. Show configured/missing-key/quota/unauthorized/model-not-found/timeout separately.

## LLY-013 — “Online” status is inferred from a closed circuit breaker, not verified connectivity — P2

**Evidence:** [`Models.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Models.tsx#L330-L390) (model status card); [`model_broker.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L115-L125) (health semantics).

The badge renders “Online” when `breaker === 'closed'` and `last_error` is empty. A newly configured model with a missing/invalid key or dead endpoint can have a closed breaker and no recorded error before it has been tested, so this can mislead users.

**Fix:** distinguish `Configured`, `Not tested`, `Healthy (last tested at …)`, `Rate limited`, `Quota exhausted`, and `Unhealthy`. A closed breaker means “not currently in cooldown”, not “reachable”.

## LLY-014 — Model test is not accounted for in the same telemetry path as ordinary calls — P2

**Evidence:** [`ModelBroker.test()`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L922-L949) compared with [`complete()`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L735-L810).

The test path reserves via `entry.try_begin()` and executes a completion directly, but does not go through the usual capacity lease, per-call ledger record, usage persistence, or aggregate counter update. Diagnostic calls can consume provider quota without appearing consistently in normal call metrics, making latency/usage analysis incomplete.

**Fix:** use a dedicated health-check ledger event and update quota/accounting consistently, while keeping test calls distinguishable from user task calls.

## LLY-015 — Completion waits for multiple database writes after the provider response — P2, measure before optimising

**Evidence:** [`model_broker.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L790-L810), [`_record_call()`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L888-L920), and [`_persist_usage()`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/model_broker.py#L870-L886).

After a successful inference, the broker awaits a call-ledger write and then awaits usage persistence before returning `Completed`. That is on the response-completion critical path. It may be small on an idle database, but under writer contention it can make the final response/task transition lag behind the last streamed token.

**Fix:** instrument this cost first. If meaningful, combine the ledger + usage updates in a single transaction or use a bounded background persistence queue that preserves durability guarantees and reports persistence failures clearly.

## LLY-016 — Token-efficiency benchmark uses a simulated routing baseline, not a measured LLM baseline — P2 (benchmark claims not empirical)

**Evidence:** [`token_efficiency_benchmark.py`](https://github.com/AJ1312/lilly/blob/master/benchmarks/token_efficiency_benchmark.py#L35-L76).

`benchmark_smart_routing()` sets deterministic routing tokens to zero, then adds a hard-coded 250 “typical” baseline tokens per query and reports 100% reduction. It does not make an actual baseline model call or compare equivalent routing quality/latency. The benchmark is illustrative, not evidence for a measured 100% token saving or an end-to-end latency improvement.

**Fix:** label this as a simulated estimate, then add repeatable tests with a recorded task set and actual token/latency accounting for baseline and optimized paths. Report success rate, p50/p95 latency, model calls, input/output/cached tokens, provider queue time, and cost per successful task.

---

# 3. Other frontend/backend contract mismatches

## LLY-017 — Workspace step results and durations use frontend field names the API does not return — P2

**Evidence:** [`Workspace.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Workspace.tsx#L470-L525); [`support.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/support.py#L130-L140); [`types.ts`](https://github.com/AJ1312/lilly/blob/master/web/src/types.ts#L20-L65).

The UI reads `st.result` and `st.duration_s`. The API's `step_json()` returns `output` and `finished_at`, and does not return `result`, `duration_s`, or `completed_at`. Similarly, `task_json()` doesn't provide the `duration_s`/`tokens_used` metrics declared on `Task`, so the corresponding Workspace cards can display em dashes. The server's actual response shape should be the source of truth.

**Fix:** align `StepRecord`/`Task` types and the API serializer. Return documented `output`, `started_at`, `finished_at`, and a measured duration; render the output field. Compute token/duration metrics from the ledger when available rather than claiming them in the type only.

## LLY-018 — Memory category choices are not backed by the memory API schema — P2

The Memory screen offers `General Fact`, `User Preference`, `Project Architecture`, and `Security / System Constraint`. The backend schema stores `label` and a `tags` list, not a `category` string. These choices currently go in a field the API ignores. Decide whether each choice should be a tag, a separate backend category column, or a client-only filter; then map it end-to-end.

## LLY-019 — The standard Talk composer omits valid task controls — P2

**Evidence:** [`Talk.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Talk.tsx#L219-L260); [`api_chat.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_chat.py#L75-L125); [`types.ts`](https://github.com/AJ1312/lilly/blob/master/web/src/types.ts#L1-L12) and the `REQUEST_INTENTS` constant later in that file.

The API accepts `intent`, `pin_model`, `skill`, and `profile`, but Talk sends only `goal`, `target`, `agent_id`, and the incorrectly named thread field. The frontend already defines the intent values (`AUTO`, `ANSWER`, `WEB RETRIEVE`, `NAVIGATE`, `ACTION`) but does not render/use `REQUEST_INTENTS` in the composer. It also has no per-task model pin or skill chooser. Users therefore cannot explicitly force Answer/Web search/Navigate/Act or invoke a named skill through the normal composer.

**Fix:** add an optional intent selector, an optional configured-model selector, and a skill selector populated by `/api/skills`; keep automatic routing as the default. Include these fields in the request and test that the backend receives them.

## LLY-020 — Agent pinned-model dropdown includes models that may be unusable — P2

**Evidence:** [`Agents.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Agents.tsx#L35-L45) and [`Agents.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Agents.tsx#L400-L430); [`api_admin.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/api_admin.py#L145-L165).

The dropdown uses all `/api/models` records as `availableModels` without filtering for `enabled`, `has_key`, health/cooldown, or local-only compatibility. A user can pin an agent to a disabled model or one without a key. The backend currently validates only that the name is configured, not that it is executable.

**Fix:** either filter to currently usable models or keep unavailable ones visible but disabled with a concrete reason. Backend should return a helpful validation/preflight error for a pinned model that is disabled/missing credentials.

## LLY-021 — Custom model “Runs locally” checkbox permits invalid combinations — P2

**Evidence:** [`Models.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Models.tsx#L720-L818); [`settings.py` validation](https://github.com/AJ1312/lilly/blob/master/src/lilly/domain/settings.py#L250-L320) and [`factory.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/providers/factory.py#L20-L61).

The custom model form allows `customLocal = true` for any provider. Backend validation only permits the local classification for Ollama and validates that a local URL is private/local. Choosing OpenAI-compatible/Mistral/Gemini/OmniRoute plus the checkbox submits an invalid settings object and fails after the user clicks Add.

**Fix:** couple this checkbox to the Ollama provider or dynamically change the provider when the user opts into local mode. Explain that “custom base URL” does not by itself mean the provider is local/private. Validate before submission.

## LLY-022 — Execution lane selector exposes only 1 and 2, while backend accepts any positive integer — P2

**Evidence:** [`Models.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Models.tsx#L785-L806); [`settings.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/domain/settings.py#L280-L330).

The model form dropdown hardcodes Lane 1 and Lane 2, but backend model validation only requires `lane >= 1`. Existing custom settings can use lane 3+ and the UI cannot create/select those values.

**Fix:** either define/enforce a true two-lane domain model server-side or accept/display arbitrary positive lane values and explain their selection priority. The UI and schema should agree.

## LLY-023 — Message DTO timestamp naming is inconsistent — P2

**Evidence:** [`types.ts`](https://github.com/AJ1312/lilly/blob/master/web/src/types.ts#L80-L105); [`support.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/ui/support.py#L145-L160).

Frontend `Message` expects `conversation_id` and `created_at`; `message_json()` returns `task_id`, `label`, `untrusted`, and `at` instead. Message text can still render, but the TypeScript contract is not describing the response. Any timestamp/order/debug UI based on `created_at` will be wrong/empty.

**Fix:** define explicit API DTOs and either return the frontend field names or update the TypeScript types and usages to match the API.

---

# 4. Missing screens, settings, and options in the current frontend

The following is a comparison against the current backend/settings models and README, not a request to add every conceivable setting. Some omissions may be deliberate product cuts, but they are current gaps versus advertised functionality.

## 4.1 Current native dropdown inventory

| Screen | Current options | Audit note |
|---|---|---|
| Talk composer — execution target | Host (Laptop), DevBox (Sandbox) | Matches the backend target enum. |
| Talk composer — agent | Auto Specialist plus configured agents | No task-level model, intent, or skill control. |
| Model setup — provider | OpenAI Compatible, Mistral AI, Google Gemini, OpenRouter, Ollama Local, OmniRoute Gateway | This covers all six values in the current backend `PROVIDERS` enum. The gap is provider-specific integrations/catalog coverage, not missing enum values. |
| Model setup — execution lane | Lane 1, Lane 2 | Restricts UI to two values even though backend accepts any positive integer. |
| Agent setup — pinned model | Auto-route plus all returned configured models | Does not filter/disable disabled models or models without usable credentials. |
| Settings — search provider | DuckDuckGo, Brave Search API, SearXNG | Matches the current `SEARCH_ENGINES` enum. |
| Memory — category | General, Preference, Project, Constraint | Frontend category schema does not match the backend's text/label/tags API. |
| Routine creation — schedule | Interval (minutes), Cron Expression | Neither form matches the backend schedule API; cron is not supported by `parse_schedule()`. |

## 4.2 Missing task-level choices

- **Intent selector:** the type/constants define Auto, Answer, Web search, Navigate, and Act, but Talk does not expose them or send them.
- **Model pin selector in Talk:** users can pin a model to an Agent, but cannot pin one request/task from the normal composer.
- **Skill selector/invocation:** API accepts `skill` and exposes `/api/skills`, but Talk doesn't present or submit a selected skill.
- **Safety/freedom mode:** `LOCKED`, `ASK`, and `OPEN` are represented in `web/src/types.ts` (`FREEDOM_MODES`) but the constant is not used in the current frontend and the settings form doesn't set backend `default_mode`.

## 4.3 Backend settings not surfaced in Settings UI

The rebuilt Settings component uses tabs for General & Safety, Engine & Execution, Limits & Capacity, Grounding & Guardrails, Network & Search, Laya Voice, DevBox Sandbox, MCP Servers, and Data & Maintenance. Cross-checking current `Settings` fields shows these missing or only partially editable:

- **Shared file roots (`file_roots`):** no frontend control was found. README advertises shared-folder setup, and an empty root list means the runtime has no user-selected file scope. This is a core capability/control gap.
- **Default privacy/freedom mode (`default_mode`):** no UI control despite `LOCKED/ASK/OPEN` being defined.
- **Data retention (`retention_days`):** no UI setting found.
- **Browser settings:** no UI controls found for `browser.mode` (`ask_every`, `ask_risky`, `allowlist`), allow-host list, max actions, idle quit, headless mode, or Chrome path.
- **Chat apps/Telegram:** backend exposes `/api/bridges` and Telegram token/pairing/unpair endpoints, but current frontend has no references to these APIs and no Chat Apps tab. README still advertises Settings → Chat apps.
- **Session token/security controls:** backend exposes `/api/session/token` and `/api/session/revoke-all`; current frontend has no calls to either endpoint. Permission revocation exists, but session/access-token management is absent.
- **DevBox tuning:** the UI can show status, prepare and reset the container, but does not surface the `DevboxSettings` fields (runtime, image, shared folder, CPU/memory/PID limits, idle/destroy timers, command timeout).
- **Capacity settings:** no controls found for `max_wait_interactive_s`, `max_wait_background_s`, `inline_retry_max_s`, `max_inflight_per_model`, `learn_limits`, `spread`, or `chars_per_token`.
- **Decision-system settings:** no controls found for the per-kind decision chains, confidence/precision/sample thresholds, budgets, and decision timeouts in `DecisionSettings`.
- **Learning settings:** no controls found for learning mode (`off`/`suggest`/`auto`) or `auto_playbooks`.
- **Crew/delegation settings:** no controls found for delegation depth, child count, budget share, or confidence threshold.
- **Partial task limits:** the UI exposes concurrent tasks, step timeout, whole-task timeout, and max agent steps. It does not expose the other defined limit fields: `lanes`, `local_unload_s`, `max_model_calls`, and `max_task_tokens`.

## 4.4 Advertised backend resources/screens missing from navigation

- **Notes/Spaces/Pages:** the backend exposes `/api/spaces`, pages CRUD, and global page search, but no current frontend component uses those APIs. `MemoryView` is only memory, not notes. README still promises “Notes, Memory”.
- **Playbook creation/deletion/editing:** Routines & Playbooks renders a read-only list; it has no create/delete/edit UI even though API create/get/delete endpoints exist.
- **Routine agent/playbook assignment and editing:** the create form contains no Agent selection or playbook selector, does not submit `agent_id`/`playbook_id`, and the cards expose pause/delete/run but no edit control.
- **Floating Companion:** `web/src/ui/CompanionWidget.tsx` exists but is not imported by the current `App.tsx` or another current view. If the screen companion feature is still intended, the rebuilt UI has orphaned it.

## 4.5 Model/provider catalog coverage

The current static catalog has eight entries: `mistral-small`, `openrouter-free`, `gemini-flash`, `openai` (`gpt-4o-mini`), `ollama-local` (`llama3.2`), `groq-llama`, `cerebras-llama`, and `omniroute` (`auto`). Groq/Cerebras are represented through the generic OpenAI-compatible adapter/base URL rather than dedicated adapter options. The custom provider dropdown itself correctly represents the current six backend provider IDs, but the catalog and provider selection experience are not a broad, dynamic catalog.

Not available as first-class provider-specific options/adapters in the current `PROVIDERS` enum: Anthropic/Claude, DeepSeek, Cohere, Together AI, Fireworks, xAI, Azure OpenAI, AWS Bedrock, and Vertex AI. Some OpenAI-compatible endpoints may be manually configured using the generic adapter and custom base URL where the API protocol is compatible; that is not equivalent to native first-class integration. Make this limitation explicit in the UI rather than implying that any provider name/model ID will work automatically.

---

# 5. Additional behaviour, consistency, and quality issues

## LLY-024 — `OFF` mode semantics contradict repository documentation — P1/P2

**Evidence:** [`steps.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/engine/steps.py#L170-L195); [`policy.py`](https://github.com/AJ1312/lilly/blob/master/src/lilly/domain/policy.py#L65-L115); [`types.ts` approval-mode descriptions](https://github.com/AJ1312/lilly/blob/master/web/src/types.ts#L455-L490); [`README.md`](https://github.com/AJ1312/lilly/blob/master/README.md#L29-L39); [`SECURITY.md`](https://github.com/AJ1312/lilly/blob/master/docs/SECURITY.md#L25-L45).

The current frontend describes OFF as “Responses only” and Talk changes request intent to `ANSWER`. `steps.py` also explicitly denies all agentic tools in OFF. However, README says AUTO **and OFF** execute autonomously without prompts, and `docs/SECURITY.md` describes OFF as suppressing prompts for policy-allowed actions; `domain/policy.py` also treats OFF as no-prompt consent. These are materially different semantics.

**Fix:** choose a single contract. If OFF means chat-only, update README/security/policy copy and tests. If OFF means no prompts, change the step gate and Talk composer consistently while retaining hard policy/approval barriers. Do not leave a safety-mode name with contradictory effective behavior.

## LLY-025 — Model cards overstate their diagnostic action as “Test Ping” — P2

The action sends a real generation request and may trigger model cold-start/provider quota. Rename it “Run test completion” or provide two separate actions: a fast connectivity/credential health probe and a completion test. Show the actual backend error and measured elapsed time.

## LLY-026 — Some interactive surfaces are clickable `div`s, not keyboard-operable controls — P2/P3

**Evidence:** [`Talk.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/views/Talk.tsx#L300-L360) quick-prompt cards; [`Sidebar.tsx`](https://github.com/AJ1312/lilly/blob/master/web/src/ui/Sidebar.tsx#L55-L95) logo/brand wrapper.

Quick-prompt cards and the clickable brand wrapper use `div` elements with click handlers instead of semantic buttons/links. They do not automatically participate in keyboard focus/activation or expose a control role.

**Fix:** use `<button type="button">` or an accessible link with visible focus styles. Add keyboard and axe checks for the main workflows.

## LLY-027 — End-to-end test coverage is insufficient for the breadth of the new UI — P2

**Evidence:** [`web/e2e/smoke.spec.ts`](https://github.com/AJ1312/lilly/blob/master/web/e2e/smoke.spec.ts#L1-L8); [`playwright.config.ts`](https://github.com/AJ1312/lilly/blob/master/web/playwright.config.ts#L1-L16).

The visible Playwright E2E suite contains one sign-in boot smoke test. It doesn't test task submission, conversation continuity, routine creation, memory CRUD, approval data/decision flow, custom model setup, SSE reconnect, or provider errors. The Playwright web server is Vite, not a running backend integration environment; this alone cannot verify API contracts.

**Fix:** add frontend component/API contract tests and a small integration E2E suite backed by the test Starlette app/fakes. Must-have flows: new task in existing thread, routine create/update, memory CRUD, approve action with target/risk/summary shown, model test failures, SSE reconnect/task final outcome, DevBox target failure with no Host fallback.

## LLY-028 — Native/API dropdown list and server schema drift need a contract test — P2

Several lists are hand-maintained in React (`providers`, execution lane, memory categories, routine schedule) while backend options live in `PROVIDERS`, `SEARCH_ENGINES`, `ExecutionTarget`, `Schedule`, and settings validation. Add a small API-schema/options endpoint or generated shared contracts so the UI cannot silently offer unsupported values or hide valid ones.

---

# 6. Recommended repair order

## Phase 1 — Unblock core workflows and fix the highest risk

1. Fix the single canonical model-routing/capacity path and make capacity timeout retries bounded.
2. Fix Talk `conversation_id`, then refresh the open thread from task events/state changes; validate end-to-end response visibility.
3. Fix routine schedule DTO creation/update and remove unsupported cron UI; add target fail-closed validation for routine/playbook APIs.
4. Align Memory API contract/serializer/type/UI together.
5. Align approval serializer and UI so the exact operation, risk, target, and reason are visible before approval.
6. Fix prompt preview DTO and model-test error display/status semantics.

## Phase 2 — Restore product parity and option discoverability

1. Restore Notes/Spaces/Pages UI and shared file-root configuration.
2. Add Chat Apps/Telegram settings and access-token/session management.
3. Restore missing Browser, DevBox, Capacity, Learning, Decision, Crew, default-mode, retention and remaining task-limit settings.
4. Add task-level intent/model/skill selectors and routine Agent/playbook selection/edit flows.
5. Fix model provider visibility/availability filtering, local-model checkbox constraints, and lane options.
6. Reconnect or remove the orphaned CompanionWidget intentionally.

## Phase 3 — Diagnose and optimise real latency

Instrument each task with: routing duration, chosen/preferred/actual model, capacity wait, provider time-to-first-token, provider completion time, number of model calls/retries, token counts/cached tokens, database persistence duration, total task duration, and outcome. Show a per-task latency waterfall in Workspace. Then compare model latency percentiles from the ledger and use measurements in the canonical router. Keep the token benchmark's simulated 250-token baseline labelled as simulated until there is a real equivalent baseline run.

## Phase 4 — Verification gates

- Python: `make python-check` plus focused tests for model routing, quota/capacity timeouts, invalid targets, schedule DTOs, API serializers, and memory CRUD.
- Web: `npm run build`, `npm run lint`, `npm test`, Playwright E2E against the test backend, and a11y checks.
- Release: verify the built `src/lilly/web` assets match `web/` source; run one opt-in smoke with Ollama and one with each configured remote provider where credentials are available. Report tests skipped for missing provider keys rather than guessing.

## Audit status

This document captures current source-evidenced findings and likely performance root causes. No claim is made that tests passed or that these findings are exhaustive: local execution was blocked by network/DNS resolution, and real-provider timing still needs a runtime trace.
