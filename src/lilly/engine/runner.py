"""TaskRunner: one coroutine drives one task from goal to answer.

plan -> preview the policy verdicts -> run the steps (side by side when that is safe) -> verify -> answer.
Nothing escapes this coroutine: every outcome ends in a recorded terminal state. How a single step runs lives in
steps.py, and which steps may run together in lanes.py; this module only orchestrates."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from lilly.core.shortlist import shortlist, tool_options
from lilly.decide.system1 import System1Engine
from lilly.domain.caps import Cap
from lilly.domain.clock import Clock
from lilly.domain.decisions import ASSIST_KINDS, DIRECT, ROUTE_OPTIONS, Brief, Context, Kind, Outcome, route_state
from lilly.domain.errors import ConflictError, LillyError, ValidationFailed
from lilly.domain.grants import GrantStore
from lilly.domain.labels import Label, Mode, TaskCtx, Verdict
from lilly.domain.payload import canonical, payload_hash
from lilly.domain.plan import preflight
from lilly.domain.policy import PathScope
from lilly.domain.ports import Completed, Completer, CompletionRequest
from lilly.domain.reasoning import Layer
from lilly.domain.settings import EngineSettings, GroundingSettings, LimitSettings
from lilly.domain.sheet import PetSheet, TaskProfile
from lilly.domain.skills import BUILTIN_SKILLS, check_skill, instantiate
from lilly.domain.tasks import TERMINAL, TaskState
from lilly.domain.tools_registry import ToolSpec
from lilly.engine.agent_loop import AgentLoop
from lilly.engine.approvals import ApprovalService
from lilly.engine.bus import EventBus
from lilly.engine.decisions import DecisionPipeline
from lilly.engine.lanes import LaneScheduler, dependencies
from lilly.engine.outcome import StepFailed, Stop, clip, describe_error
from lilly.engine.planner import HistoryItem, PlanInputs, direct_plan, generate_plan, replan
from lilly.engine.receipt import ReceiptBuilder
from lilly.engine.record import TaskRecord
from lilly.engine.replycheck import ReplyChecker
from lilly.engine.steps import StepExecutor

# Import for type hints - avoid circular import issues
try:
    from lilly.engine.quick import QuickAction, QuickRouter
except ImportError:
    QuickAction = Any  # type: ignore
    QuickRouter = Any  # type: ignore
from lilly.store import conversations, decisions, tasks
from lilly.store.db import Database
from lilly.store.readcache import ReadCache
from lilly.store.standing import StandingStore
from lilly.tools.base import Tool

log = logging.getLogger("lilly.runner")

MAX_ATTEMPTS = 2           # the first plan and at most one replan


@dataclass(frozen=True, slots=True)
class RunSpec:
    goal: str
    conversation_id: str
    agent_instructions: str = ""
    skill: str | None = None
    params: Mapping[str, str] = field(default_factory=dict)
    pin_model: str | None = None
    sheet: PetSheet | None = None
    profile: TaskProfile | None = None


@dataclass(frozen=True, slots=True)
class EngineDeps:
    db: Database
    completer: Completer
    tools: Callable[[], Mapping[str, Tool]]
    scope: Callable[[], PathScope]
    file_roots: Callable[[], tuple[str, ...]]
    bus: EventBus
    approvals: ApprovalService
    grants: GrantStore
    clock: Clock
    limits: Callable[[], LimitSettings] = LimitSettings
    decisions: DecisionPipeline | None = None   # cheap advisers; None means every question gets no decision
    engine_settings: Callable[[], EngineSettings] = EngineSettings
    grounding_settings: Callable[[], GroundingSettings] = GroundingSettings
    read_cache: ReadCache | None = None
    quick: QuickRouter | None = None
    standing: StandingStore | None = None
    system1: System1Engine | None = None


class TaskRunner:
    def __init__(self, deps: EngineDeps, task: tasks.TaskRow, spec: RunSpec, replies: ReplyChecker | None = None) -> None:
        self._d, self._task, self._spec, self._replies = deps, task, spec, replies
        self.stop_reason = "stopped"      # what a cancelled task shows as its reason
        self._brief = Brief(spec.goal, spec.agent_instructions)
        self._route: Outcome | None = None     # the route question of this task, until it is labelled
        self._rec = TaskRecord(deps.db, deps.bus, deps.clock, task.id, TaskCtx(task.label, task.tainted, Mode(task.mode)),
                                TaskState(task.state))
        self._steps = StepExecutor(self._rec, deps.approvals, deps.grants, deps.scope, deps.limits, spec.pin_model,
                                   deps.decisions, self._brief, engine_settings=deps.engine_settings,
                                   read_cache=deps.read_cache, standing=deps.standing)

    @property
    def agent_id(self) -> str | None:
        return self._task.agent_id

    @property
    def steps(self) -> StepExecutor:
        return self._steps

    def request_cancel(self, reason: str = "stopped") -> None:
        """Tell worker threads (which asyncio cannot interrupt) to stop at their next check. The first reason given
        is the one the task shows."""
        if not self._rec.cancelled:
            self.stop_reason = reason
        self._rec.cancelled = True

    # ---- entry point ----------------------------------------------------------------------------
    async def run(self) -> None:
        try:
            async with asyncio.timeout(self._d.limits().task_minutes * 60.0):
                await self._execute()
        except asyncio.CancelledError:
            await asyncio.shield(self._finish(TaskState.CANCELLED, error=self.stop_reason))
            raise
        except Stop as stop:
            await self._finish(stop.state, error=stop.message)
        except TimeoutError:
            await self._finish(TaskState.FAILED, error="the task took too long and was stopped")
        except Exception as exc:  # the last line of defence: a task always ends in a recorded state
            if not isinstance(exc, LillyError):
                log.exception("task %s crashed", self._task.id)
            await self._finish(TaskState.FAILED, error=describe_error(exc))

    async def _finish(self, state: TaskState, *, answer: str | None = None, error: str | None = None) -> None:
        try:
            task_id, conv, now = self._task.id, self._spec.conversation_id, self._d.clock()
            label, untrusted = self._rec.ctx.label, self._rec.ctx.tainted

            def reply(con: sqlite3.Connection) -> None:     # in the answer's transaction: the chat never misses it
                assert answer is not None
                conversations.add_message(con, conv, "assistant", answer, now, label=label, untrusted=untrusted,
                                          task_id=task_id)

            await self._rec.state(state, answer=answer, error=error, also=reply if answer is not None else None)
        except ConflictError:
            row = tasks.get_task(self._d.db.reader, self._task.id)
            if row is not None and row.state not in TERMINAL:  # a bug, not a race: never leave a task hanging
                log.error("task %s could not move to %s from %s", self._task.id, state.value, row.state.value)
                await self._d.db.write(lambda con: tasks.set_state(
                    con, self._task.id, TaskState.FAILED, self._d.clock(), error="internal state error"))
        except LillyError:
            log.exception("could not record the end of task %s", self._task.id)

    # ---- the work -----------------------------------------------------------------------------------
    async def _execute(self) -> None:
        if self._spec.skill or self._d.engine_settings().mode == "plan":
            await self._execute_plan()
            return

        # Quick Actions hook (P2-A)
        if self._d.quick is not None and not self._spec.skill:
            tools = dict(self._d.tools())
            allowed = self._spec.sheet.tools if self._spec.sheet else None
            allowed_names = {n for n in tools if allowed is None or n in allowed}
            found = self._d.quick.match(self._spec.goal, allowed_names)
            if isinstance(found, QuickAction):
                await self._run_quick(found, tools)
                return
            # Ambiguous: fall through to the normal loop

        self._prepare_assist()
        await self._rec.state(TaskState.PLANNING)
        pet_name = self._spec.sheet.name if self._spec.sheet else "Lilly"
        role_models = dict(self._spec.sheet.models) if self._spec.sheet else None
        loop = AgentLoop(
            rec=self._rec,
            completer=self._d.completer,
            steps=self._steps,
            tools=self._d.tools,
            scope=self._d.scope,
            file_roots=self._d.file_roots,
            limits=self._d.limits,
            engine_settings=self._d.engine_settings,
            db=self._d.db,
            goal=self._spec.goal,
            conversation_id=self._spec.conversation_id,
            agent_instructions=self._spec.agent_instructions,
            pin_model=self._spec.pin_model,
            pet_name=pet_name,
            decisions=self._d.decisions,
            stop_reason=lambda: self.stop_reason,
            role_models=role_models,
            grounding_settings=self._d.grounding_settings,
            system1_engine=self._d.system1,
            sheet=self._spec.sheet,
            profile=self._spec.profile,
        )
        answer = await loop.run()
        await self._answer(answer)

    async def _execute_plan(self) -> None:
        self._prepare_assist()
        tools = dict(self._d.tools())   # what the plan is made from; each step looks its tool up again when it starts
        specs: dict[str, ToolSpec] = {n: t.spec for n, t in tools.items()}
        await self._rec.state(TaskState.PLANNING)
        inputs = await self._plan_inputs(specs)
        plan = await self._direct(inputs)
        if plan is None:
            try:
                plan = await self._make_plan(inputs, specs)
            except ValidationFailed:
                if len(inputs.tools) == len(specs):
                    raise
                inputs = replace(inputs, tools=specs)    # the shortlist may have hidden the tool the plan needed
                plan = await self._make_plan(inputs, specs)
            await self._label_route(not plan["steps"])
        for attempt in range(1, MAX_ATTEMPTS + 1):
            outputs: dict[str, str] = {}
            if plan.get("reasoning"):
                await self._rec.thought(Layer.UNDERSTAND, plan["reasoning"], "model")
            if not plan["steps"]:
                await self._answer(str(plan["answer"]).strip())
                return
            await self._announce(plan, specs, attempt)
            for name in {step["tool"] for step in plan["steps"]}:
                if name in tools:
                    tools[name].warm()      # anything slow to start (the devbox) begins while earlier steps run
            await self._rec.state(TaskState.RUNNING)
            try:
                answer = await self._run_steps(plan["steps"], specs, attempt, outputs)
            except StepFailed as failed:
                if failed.kind == "capacity":
                    raise Stop(TaskState.FAILED, failed.reason) from None
                if attempt == MAX_ATTEMPTS:
                    raise Stop(TaskState.FAILED, failed.reason) from None
                await self._rec.thought(Layer.REFLECT, f"A step failed ({failed.reason}). Planning another way.")
                plan = await self._replan(inputs, specs, failed.reason, outputs)
                continue
            await self._answer(answer)
            return

    async def _direct(self, inputs: PlanInputs) -> dict[str, Any] | None:
        """Laya's shortcut to save tokens: when it judges that no tool is needed, a cheap model answers without being
        sent the tool list. Anything unclear (Laya cold, unsure, watch-only, or the model asking for tools) returns
        None and the normal planner runs, so this can only ever skip work, never widen what may be done."""
        pipeline = self._d.decisions
        if pipeline is None or self._spec.skill or not pipeline.active(Kind.ROUTE):
            return None
        self._route = await pipeline.decide(Kind.ROUTE, self._task.id, ROUTE_OPTIONS, Context(text=route_state(self._brief)))
        if self._route.choice != DIRECT:
            return None
        plan = await direct_plan(self._complete_for_planning, inputs)
        if plan is not None:
            await self._rec.thought(Layer.PLAN, "No tool needed, so a quick model answered without the tool list.")
        await self._label_route(plan is not None)
        return plan

    async def _label_route(self, answered_without_tools: bool) -> None:
        """What really happened is the label for the question, so `lilly decisions report` can say how often Laya was
        right, in watch-only mode as well. Only the first call per task counts."""
        asked, self._route = self._route, None
        guess = asked.choice or asked.would if asked is not None else None
        if asked is None or asked.log_id is None or guess is None:
            return
        right = (guess == DIRECT) == answered_without_tools
        log_id = asked.log_id
        with contextlib.suppress(LillyError):
            await self._d.db.write(lambda con: decisions.set_outcome(con, log_id, "accepted" if right else "corrected"))

    def _prepare_assist(self) -> None:
        """Start getting Laya ready now, so it is loaded by the time the first risky step or the reply needs it."""
        if self._d.decisions is not None:
            for kind in ASSIST_KINDS:
                self._d.decisions.prepare(kind)

    async def _plan_inputs(self, specs: Mapping[str, ToolSpec]) -> PlanInputs:
        conv = self._spec.conversation_id
        rows = conversations.recent_messages(self._d.db.reader, conv, 12)
        history = [HistoryItem(m.role, m.content, m.label, m.untrusted) for m in rows if m.task_id != self._task.id]
        for h in history:
            self._rec.absorb(h.label, h.untrusted)
        await self._rec.remember_ctx()
        shown = await self._shortlisted(specs)
        return PlanInputs(self._spec.goal, shown, history, self._spec.agent_instructions, self._d.file_roots())

    async def _shortlisted(self, specs: Mapping[str, ToolSpec]) -> Mapping[str, ToolSpec]:
        """Use ranking only to control prompt size; replans always receive the full catalog."""
        pipeline = self._d.decisions
        if pipeline is None or self._spec.skill:
            return specs
        advice = await pipeline.decide(Kind.TOOLS, self._task.id, tool_options(specs), Context(self._spec.goal))
        return {n: specs[n] for n in shortlist(specs, advice.ranking)}

    async def _make_plan(self, inputs: PlanInputs, specs: Mapping[str, ToolSpec]) -> dict[str, Any]:
        if self._spec.skill:
            skill = BUILTIN_SKILLS.get(self._spec.skill)
            if skill is None:
                raise Stop(TaskState.FAILED, f"unknown skill {self._spec.skill!r}")
            problems = check_skill(skill, dict(specs))
            if problems:
                raise Stop(TaskState.FAILED, f"{skill.name} cannot run here: {'; '.join(problems)}")
            plan = instantiate(skill, dict(self._spec.params))
            return {"reasoning": f"Running the {skill.name} skill.", "answer": None, "steps": plan["steps"]}
        return await generate_plan(self._complete_for_planning, inputs)

    async def _replan(self, inputs: PlanInputs, specs: Mapping[str, ToolSpec], reason: str,
                      outputs: Mapping[str, str]) -> dict[str, Any]:
        progress = f"{reason}\n" + "\n".join(f"{sid} produced: {out[:300]}" for sid, out in outputs.items())
        everything = replace(inputs, tools=specs)
        return await replan(self._complete_for_planning, everything, progress, tainted=self._rec.ctx.tainted)

    async def _complete_for_planning(self, req: CompletionRequest) -> Completed:
        digest = payload_hash(self._task.id, "plan", "plan", {"goal": self._spec.goal})

        async def call() -> Completed:
            done = await self._d.completer.complete(
                req, need=Cap.NONE, label=self._rec.ctx.label, task_id=self._task.id, payload_hash=digest,
                mode=self._rec.ctx.mode, pin=self._spec.pin_model)
            self._rec.models.append(done.model)
            return done

        return await self._steps.with_model_permission(call, "plan", TaskState.PLANNING)

    async def _announce(self, plan: Mapping[str, Any], specs: Mapping[str, ToolSpec], attempt: int) -> None:
        errs, verdicts = preflight(dict(plan), dict(specs), self._rec.ctx, self._d.scope())
        if errs:
            raise Stop(TaskState.FAILED, "the plan was rejected: " + "; ".join(errs))
        by_id = {v.step_id: v for v in verdicts}
        deps = dependencies(plan["steps"])
        steps = [{"id": s["id"], "tool": s["tool"], "expect": s.get("expect", ""), "args": clip(s.get("args", {})),
                  "deps": list(deps[s["id"]]), "verdict": by_id[s["id"]].verdict.name, "why": by_id[s["id"]].reason}
                 for s in plan["steps"]]
        suffix = f".{attempt}" if attempt > 1 else ""
        task_id = self._task.id
        rows = [(f"{s['id']}{suffix}", s["tool"], canonical(clip(s.get("args", {})))) for s in plan["steps"]]
        now = self._d.clock()

        def save(con: sqlite3.Connection) -> None:
            tasks.set_plan(con, task_id, json.dumps(plan), now)
            tasks.create_steps(con, task_id, rows)

        await self._d.db.write(save)
        await self._rec.event("plan", {"attempt": attempt, "steps": steps, "models": self._rec.models[-1:]}, "model")
        await self._rec.thought(Layer.PLAN, "Plan: " + " → ".join(s["tool"] for s in steps))
        asks = [s["id"] for s in steps if s["verdict"] == Verdict.NEEDS_APPROVAL.name]
        blocked = [s for s in steps if s["verdict"] == Verdict.DENY.name]
        note = "no step needs your approval" if not asks else f"you will be asked about {', '.join(asks)}"
        if blocked:
            note += "; blocked by policy: " + ", ".join(f"{s['id']} ({s['why']})" for s in blocked)
        await self._rec.thought(Layer.CRITIQUE, f"Policy preview: {note}. Arguments that depend on earlier "
                                                "results are checked again when the step runs.")

    async def _run_steps(self, steps: list[dict[str, Any]], specs: Mapping[str, ToolSpec], attempt: int,
                         outputs: dict[str, str]) -> str:
        suffix = f".{attempt}" if attempt > 1 else ""

        def row(st: Mapping[str, Any]) -> str:
            return f"{st['id']}{suffix}"

        lanes = LaneScheduler(specs, self._d.scope(), self._d.limits().lanes, lambda: self._rec.ctx,
                              self._steps.may_taint)
        await lanes.run(steps, lambda st: self._steps.run(st, row(st), outputs, self._d.tools()),
                        lambda st: self._steps.abandon(row(st)), outputs)
        await self._rec.state(TaskState.VERIFYING)
        answer = outputs[steps[-1]["id"]].strip()
        if not answer:
            raise Stop(TaskState.FAILED, "the final reply was empty")
        return answer

    async def _run_quick(self, qa: QuickAction, tools: dict[str, Tool]) -> None:
        """Execute a quick action without model calls."""
        import json

        from lilly.engine.outcome import StepDeclined, StepFailed
        from lilly.store import tasks
        
        await self._rec.state(TaskState.PLANNING)
        await self._rec.event("quick", {"tool": qa.tool, "target": qa.shown, "by": qa.matched_by,
                                        "confidence": round(qa.confidence, 2)}, "system")
        step_id = "q1"
        await self._d.db.write(lambda con: tasks.create_steps(con, self._task.id,
                               [(step_id, qa.tool, json.dumps(qa.args))]))
        await self._rec.state(TaskState.RUNNING)
        self._steps.loop_mode = True
        try:
            out = await self._steps.run({"tool": qa.tool, "args": qa.args}, step_id, {}, tools, decline_continues=True)
        except StepDeclined:
            # For now, use a simple message since we don't have access to copy
            await self._answer(f"Quick action declined: {qa.shown}")
            return
        except StepFailed as failed:
            await self._finish(TaskState.FAILED, error=failed.reason)
            return
        await self._answer(tools[qa.tool].summary(qa.args, out))      # code-written; no model text

    async def _answer(self, text: str) -> None:
        if not text:
            raise Stop(TaskState.FAILED, "there was no answer to give")
        if self._rec.ctx.label is Label.SECRET:  # unreachable by policy; a last guard before text is stored as an answer
            raise Stop(TaskState.FAILED, "the answer would contain secret data")
        if self._rec.state_now is TaskState.RUNNING:
            await self._rec.state(TaskState.VERIFYING)
        elapsed = round(time.monotonic() - self._rec.started, 1)
        models = ", ".join(dict.fromkeys(self._rec.models)) or "no model"
        await self._rec.thought(Layer.REFLECT, f"Done in {elapsed}s using {models}.")
        globs = self._d.grounding_settings().protected_globs
        receipt = ReceiptBuilder.build_from_con(self._d.db.reader, self._task.id, protected_globs=globs)
        await self._rec.event("receipt", receipt.to_dict())
        await self._finish(TaskState.DONE, answer=text)
        if self._replies is not None and self._rec.state_now is TaskState.DONE:   # saved and finished: now it may be judged
            self._replies.start(self._task.id, self._brief, text, self._rec.event)
