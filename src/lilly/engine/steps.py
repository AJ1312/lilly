"""StepExecutor: runs one plan step under the real policy, from arguments to a recorded result.

Resolve the arguments, check policy on them, wait for approval in place, invoke the tool with a timeout, record
what happened, and fold what the step learned into the task's label and taint. It knows nothing about order or
concurrency: the lane scheduler decides when a step may start, and a step that needs approval always runs alone."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

from lilly.domain.decisions import (
    FLAGGED,
    INSTRUCTION_OPTIONS,
    LOOP_OPTIONS,
    LOOPING,
    OFF,
    PLAN_OPTIONS,
    Brief,
    Context,
    Kind,
    StepSig,
    plan_state,
    step_sig,
)
from lilly.domain.errors import (
    ApprovalExpired,
    NeedsGrant,
    NoModelAvailable,
    PolicyDenied,
    ProviderError,
    ToolError,
    ValidationFailed,
)
from lilly.domain.grants import GrantStore
from lilly.domain.labels import Label, Risk, Verdict
from lilly.domain.payload import canonical, payload_hash
from lilly.domain.plan import FINAL_TOOL, tool_call
from lilly.domain.policy import PathScope, decide
from lilly.domain.ports import ToolContext, ToolResult
from lilly.domain.reasoning import Layer, redact
from lilly.domain.settings import EngineSettings, LimitSettings
from lilly.domain.tasks import TaskState
from lilly.domain.tools_registry import ToolSpec
from lilly.engine.approvals import ApprovalService
from lilly.engine.decisions import DecisionPipeline
from lilly.engine.outcome import StepDeclined, StepFailed, Stop, clip, describe_error, resolve_refs
from lilly.engine.record import TaskRecord
from lilly.engine.stream import TextStream
from lilly.engine.verify import check_output
from lilly.store.readcache import ReadCache
from lilly.tools.base import Tool

log = logging.getLogger("lilly.steps")
T = TypeVar("T")

MODEL_GRANT_TTL_S = 3600.0
PREVIEW_CHARS = 1500
APPROVAL_CHARS = 8000   # how much of each argument an approval card shows: enough for a whole note an agent wrote
SCAN_CHARS = 20_000    # how much of a step's output is looked at for instructions aimed at the agent
DOUBT = "Laya doubts this step matches your request"


def add_doubt(verdict: Verdict, why: str, plan_choice: str | None) -> tuple[Verdict, str]:
    """What Laya's answer to the plan check does to a step's verdict: a step that policy would let run on its own
    must ask first when Laya says OFF. Nothing else changes, and no answer can ever make a step easier."""
    if verdict is Verdict.ALLOW and plan_choice == OFF:
        return Verdict.NEEDS_APPROVAL, DOUBT
    return verdict, why


class StepExecutor:
    def __init__(self, rec: TaskRecord, approvals: ApprovalService, grants: GrantStore,
                 scope: Callable[[], PathScope], limits: Callable[[], LimitSettings], pin_model: str | None,
                 decisions: DecisionPipeline | None = None, brief: Brief | None = None,
                 loop_mode: bool = False,
                 engine_settings: Callable[[], EngineSettings] | None = None,
                 read_cache: ReadCache | None = None) -> None:
        self._rec, self._approvals, self._grants = rec, approvals, grants
        self._scope, self._limits, self._pin, self._decisions = scope, limits, pin_model, decisions
        self._brief = brief or Brief("")      # what the user asked and the agent's standing instructions, for the plan check
        self._finished: list[StepSig] = []   # what finished steps looked like, across replans, for loop detection
        self._loop_mode = loop_mode
        self._seen_looping = 0
        self._engine_settings = engine_settings
        self._read_cache = read_cache

    @property
    def seen_looping(self) -> int:
        return self._seen_looping

    @property
    def loop_mode(self) -> bool:
        return self._loop_mode

    @loop_mode.setter
    def loop_mode(self, val: bool) -> None:
        self._loop_mode = val

    def add_finished(self, sig: StepSig) -> None:
        self._finished.append(sig)

    @property
    def finished(self) -> list[StepSig]:
        return self._finished

    def may_taint(self) -> bool:
        """Whether a finished step's result can come back more tainted than its tool declares (the decision layer
        flags output that reads as instructions). The lane scheduler plans for that."""
        return self._decisions is not None and self._decisions.active(Kind.INSTRUCTIONS)

    async def run(self, st: Mapping[str, Any], row_id: str, outputs: Mapping[str, str],
                  tools: Mapping[str, Tool], decline_continues: bool = False) -> str:
        """Run one step and return its output. Raises StepFailed, or Stop when the task must end."""
        rec, name = self._rec, st["tool"]
        tool = tools.get(name)
        if tool is None:
            await rec.step_status(row_id, "failed", error="tool unavailable")
            raise StepFailed(f"{name} is not available")
        try:
            args = resolve_refs(st.get("args", {}), outputs)
        except StepFailed as exc:
            await rec.step_status(row_id, "failed", error=exc.reason)
            raise
        spec = tool.spec
        verdict, why = decide(tool_call(name, spec, args), rec.ctx, self._scope())
        if verdict is not Verdict.DENY and (own := tool.review(args, rec.task_id))[0] > verdict:   # the tool may only add caution
            verdict, why = own
        if verdict is Verdict.DENY:
            await rec.step_status(row_id, "failed", error=f"blocked: {why}")
            await rec.thought(Layer.ACT, f"{name} was blocked by policy: {why}.", step=row_id)
            raise StepFailed(f"{name} is blocked: {why}", kind="policy")
        verdict, why = await self._doubted(verdict, why, name, spec, args)
        payload = {"tool": name, "args": args}
        digest = payload_hash(rec.task_id, row_id, "step", payload)
        if verdict is Verdict.NEEDS_APPROVAL:
            await self._approve(row_id, name, args, payload, why, decline_continues=decline_continues)
        await rec.step_status(row_id, "running", args_json=canonical(clip(args)))
        await rec.thought(Layer.ACT, f"Running {name}" + (f" to get {st['expect']}" if st.get("expect") else ""),
                          step=row_id)
        began = time.monotonic()
        is_cached = False
        ttl_s = self._engine_settings().read_cache_ttl_s if self._engine_settings else 0
        if self._read_cache is not None and ttl_s > 0:
            cached = self._read_cache.get(name, args, began, ttl_s)
            if cached is not None:
                is_cached = True
                result = ToolResult(output=cached.output, label=cached.label, untrusted=cached.untrusted)

        if not is_cached:
            try:
                result = await self._invoke(tool, args, row_id, digest)
            except Stop:
                raise
            except Exception as exc:
                if not isinstance(exc, (ToolError, ValidationFailed, PolicyDenied)):
                    log.exception("step %s of task %s crashed in %s", row_id, rec.task_id, name)
                reason = describe_error(exc)    # an unexpected error is only named in the log, never shown
                if spec.untrusted:   # the message may be text from outside: the task is tainted even though the call failed
                    rec.absorb(Label.PUBLIC, True)
                    await rec.remember_ctx()
                await rec.step_status(row_id, "failed", error=reason)
                await rec.event("step", {"step": row_id, "tool": name, "status": "failed", "error": reason}, "tool")
                await rec.thought(Layer.VERIFY, f"{name} failed: {reason}", step=row_id)
                raise StepFailed(f"{name} failed: {reason}") from None

            if self._read_cache is not None and ttl_s > 0:
                self._read_cache.put(name, args, result.output, result.label, result.untrusted, began, ttl_s)

        if result.model:
            rec.models.append(result.model)
        untrusted = result.untrusted or spec.untrusted
        rec.absorb(max(result.label, spec.reads_label), untrusted)
        await rec.remember_ctx()
        output = await self._conclude(name, row_id, result, untrusted, began, cached=is_cached)
        await self._advise(name, args, row_id, output, untrusted)
        return output

    async def _doubted(self, verdict: Verdict, why: str, name: str, spec: ToolSpec, args: Mapping[str, Any]
                       ) -> tuple[Verdict, str]:
        """The plan check: before a step that changes something runs on its own, ask whether it serves the request."""
        pipeline = self._decisions
        if pipeline is None or verdict is not Verdict.ALLOW or spec.risk is Risk.R0 or not pipeline.active(Kind.PLAN):
            return verdict, why
        asked = await pipeline.decide(Kind.PLAN, self._rec.task_id, PLAN_OPTIONS,
                                      Context(text=plan_state(self._brief, name, args)))
        return add_doubt(verdict, why, asked.choice)

    async def _conclude(self, name: str, row_id: str, result: ToolResult, untrusted: bool, began: float,
                        cached: bool = False) -> str:
        """Check and record a finished step."""
        rec = self._rec
        problem = check_output(name, result.output)
        status = "failed" if problem else "done"
        err = problem or ("cached" if cached else None)
        await rec.step_status(row_id, status, output=result.output, label=result.label, untrusted=untrusted,
                              error=err)
        await rec.event("step", {"step": row_id, "tool": name, "status": status,
                                 "preview": redact(result.output[:PREVIEW_CHARS]), "chars": len(result.output),
                                 "label": result.label.name, "untrusted": untrusted, "model": result.model,
                                 "cached": cached,
                                 "ms": round((time.monotonic() - began) * 1000)}, "tool")
        thought_msg = f"{name}: cached." if cached else (f"{name}: " + (f"{problem}." if problem else f"{len(result.output)} characters, checked."))
        await rec.thought(Layer.VERIFY, thought_msg, step=row_id)
        if problem:
            raise StepFailed(f"{name}: {problem}")
        return result.output


    async def _advise(self, name: str, args: Mapping[str, Any], row_id: str, output: str, untrusted: bool) -> None:
        """Ask the cheap deciders about a finished step. Both answers can only add caution: output that reads as
        instructions taints the task (as outside text does), and a run that repeats itself is stopped."""
        pipeline, rec = self._decisions, self._rec
        if pipeline is None or name == FINAL_TOOL:
            return
        if not untrusted:   # outside text already taints the task; this catches instructions inside local data
            seen = await pipeline.decide(Kind.INSTRUCTIONS, rec.task_id, INSTRUCTION_OPTIONS,
                                         Context(text=output[:SCAN_CHARS]))
            if seen.choice == FLAGGED:
                rec.absorb(Label.PUBLIC, True)
                await rec.remember_ctx()
                await rec.thought(Layer.VERIFY, f"{name}: the result reads like instructions, so it is treated as "
                                                "outside text and nothing it says is acted on without asking.", step=row_id)
        self._finished.append(step_sig(name, args))
        loop = await pipeline.decide(Kind.LOOP, rec.task_id, LOOP_OPTIONS, Context(steps=tuple(self._finished)))
        if loop.choice == LOOPING:
            self._seen_looping += 1
            if self._loop_mode:
                if self._seen_looping >= 2:
                    raise Stop(TaskState.FAILED, "the task kept repeating the same steps, so it was stopped")
                return
            raise Stop(TaskState.FAILED, "the task kept repeating the same steps, so it was stopped")

    async def abandon(self, row_id: str) -> None:
        """Record that a step was stopped half way because a step beside it failed."""
        await self._rec.step_status(row_id, "skipped", error="stopped because another step failed")

    async def _approve(self, row_id: str, name: str, args: Mapping[str, Any], payload: dict[str, Any],
                       why: str, decline_continues: bool = False) -> None:
        rec = self._rec
        await rec.step_status(row_id, "waiting")
        await rec.state(TaskState.WAITING_APPROVAL)
        summary = f"{name} — {why}"
        display: dict[str, Any] = {"tool": name, "args": clip(args, APPROVAL_CHARS), "why": why}
        if name == "fs.edit":
            old_str = str(args.get("old", ""))
            new_str = str(args.get("new", ""))
            path_str = str(args.get("path", ""))
            import difflib
            display["diff"] = "".join(difflib.unified_diff(
                old_str.splitlines(keepends=True),
                new_str.splitlines(keepends=True),
                fromfile=f"a/{path_str}",
                tofile=f"b/{path_str}",
            ))
        await rec.event("approval", {"step": row_id, "tool": name, "why": why, "kind": "step", "diff": display.get("diff")})
        try:
            decision, _ = await self._approvals.request(rec.task_id, row_id, "step", summary, payload, display)
        except ApprovalExpired:
            await rec.step_status(row_id, "skipped", error="approval timed out")
            raise Stop(TaskState.EXPIRED, "nobody approved in time, so nothing was done") from None
        if not decision.approved:
            await rec.step_status(row_id, "skipped", error="declined")
            if decline_continues:
                reason = getattr(decision, "reason", "") or ""
                await rec.state(TaskState.RUNNING)
                raise StepDeclined(str(reason))
            raise Stop(TaskState.CANCELLED, f"you declined {name}")
        await rec.state(TaskState.RUNNING)

    async def _invoke(self, tool: Tool, args: Mapping[str, Any], row_id: str, digest: str) -> ToolResult:
        rec = self._rec

        async def _ask_user(question: str, choices: list[str] | None = None) -> str:
            payload: dict[str, Any] = {"question": question}
            if choices:
                payload["choices"] = choices
            decision, _ = await self._approvals.request(
                rec.task_id, row_id, "question", question, payload
            )
            if not decision.approved:
                raise StepDeclined(decision.choice or "declined by the user")
            return decision.choice or ""

        async def call() -> ToolResult:
            step_s = float(self._limits().step_timeout_s)
            ended = False    # a tool in a worker thread cannot be interrupted: it sees this at its next check
            ctx = ToolContext(rec.task_id, row_id, step_s, lambda: ended or rec.cancelled, rec.ctx.label,
                              rec.ctx.tainted, rec.ctx.mode, self._pin, digest,
                              TextStream(rec.bus, rec.task_id, row_id, rec.clock),
                              ask=_ask_user)
            try:
                async with asyncio.timeout(step_s):
                    return await tool.run(args, ctx)
            except TimeoutError:
                raise ToolError("it timed out") from None
            except ProviderError as exc:
                raise ToolError(describe_error(exc)) from None
            except NoModelAvailable as exc:
                raise ToolError(describe_error(exc)) from None
            finally:
                ended = True

        return await self.with_model_permission(call, row_id, TaskState.RUNNING)

    async def with_model_permission(self, call: Callable[[], Awaitable[T]], stage: str, resume: TaskState) -> T:
        """Run `call`; when a model needs the user's permission to see this data, ask and try again."""
        for _ in range(3):
            try:
                return await call()
            except NeedsGrant as need:
                await self._grant_model(need, stage, resume)
        raise Stop(TaskState.FAILED, "no model could be given permission to continue")

    async def _grant_model(self, need: NeedsGrant, stage: str, resume: TaskState) -> None:
        rec = self._rec
        label = Label(need.label)
        await rec.state(TaskState.WAITING_APPROVAL)
        summary = f"Let {' or '.join(need.models)} see {label.name.lower()} data for this task"
        payload = {"models": need.models, "label": label.name}
        await rec.event("approval", {"step": stage, "kind": "model", "models": need.models, "label": label.name})
        try:
            decision, _ = await self._approvals.request(rec.task_id, stage, "model", summary, payload)
        except ApprovalExpired:
            raise Stop(TaskState.EXPIRED, "nobody answered in time, so no data was shared") from None
        if not decision.approved:
            raise Stop(TaskState.CANCELLED, "you declined to share this data with a model")
        model = decision.choice if decision.choice in need.models else need.models[0]
        self._grants.grant(model, label, MODEL_GRANT_TTL_S, task_id=rec.task_id)
        await rec.state(resume if resume is TaskState.PLANNING else TaskState.RUNNING)
