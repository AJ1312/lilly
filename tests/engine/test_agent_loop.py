"""Tests for Phase 3: The Agent Loop (LOOP-01 to LOOP-20).

Covers turn-by-turn reasoning, tool execution, observations, parallel execution,
schema validation, policy denials, declines, approval expiry, loop guards,
escalation, budget warnings/exhaustion, fallbacks, state machine transitions,
cancellation, role mapping, allowlists, and the LOOP-03 browser errand gate.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from lilly.domain.decisions import LOOPING, Brief, Context, Kind, Option, Outcome
from lilly.domain.errors import ApprovalExpired, NeedsGrant, ToolError
from lilly.domain.grants import GrantStore
from lilly.domain.ids import new_id
from lilly.domain.labels import Label, Mode, Risk, TaskCtx
from lilly.domain.policy import PathScope
from lilly.domain.ports import (
    Completed,
    CompletionRequest,
    CompletionResult,
    ModelToolCall,
    ToolContext,
    ToolResult,
)
from lilly.domain.settings import EngineSettings, LimitSettings
from lilly.domain.tasks import TaskState
from lilly.domain.tools_registry import ToolSpec
from lilly.engine.agent_loop import AgentLoop
from lilly.engine.approvals import DEFAULT_TTL_S, ApprovalService
from lilly.engine.bus import EventBus
from lilly.engine.decisions import DecisionPipeline
from lilly.engine.messages import (
    NOTICE_BUDGET_EXHAUSTED,
    NOTICE_LOOPING,
)
from lilly.engine.record import TaskRecord
from lilly.engine.runner import EngineDeps, RunSpec, TaskRunner
from lilly.engine.steps import StepExecutor
from lilly.store import conversations, tasks
from lilly.store.db import Database
from lilly.tools.base import Tool
from tests.helpers import Clock, ScriptedCompleter

# ---- Helpers & Test Tool Harness ---------------------------------------------

def reply_text(text: str, in_tok: int = 10, out_tok: int = 10) -> Completed:
    return Completed(CompletionResult(text, in_tok, out_tok, finish_reason="stop"), model="scripted")


def reply_tools(*calls: ModelToolCall, text: str = "", in_tok: int = 10, out_tok: int = 10) -> Completed:
    return Completed(
        CompletionResult(text, in_tok, out_tok, finish_reason="stop", tool_calls=tuple(calls)),
        model="scripted",
    )


def make_call(name: str, args: Mapping[str, Any], call_id: str | None = None) -> ModelToolCall:
    return ModelToolCall(
        id=call_id or f"call_{name}",
        name=name,
        arguments=args,
        raw=json.dumps(args),
        error=None,
    )


@dataclass
class LoopTrace:
    log: list[tuple[str, str]] = field(default_factory=list)
    cancelled: list[str] = field(default_factory=list)
    running: int = 0
    peak: int = 0


class LoopProbe(Tool):
    def __init__(
        self,
        name: str,
        spec: ToolSpec,
        trace: LoopTrace,
        delay: float = 0.0,
        result_text: str | None = None,
        fail: str | None = None,
    ) -> None:
        self.name = name
        self._spec = spec
        self._trace = trace
        self._delay = delay
        self._result_text = result_text or f"result of {name}"
        self._fail = fail

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        self._trace.log.append(("start", ctx.step_id))
        self._trace.running += 1
        self._trace.peak = max(self._trace.peak, self._trace.running)
        try:
            if self._delay > 0:
                await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            self._trace.cancelled.append(ctx.step_id)
            raise
        finally:
            self._trace.running -= 1
        if self._fail:
            raise ToolError(self._fail)
        self._trace.log.append(("end", ctx.step_id))
        return ToolResult(self._result_text, self._spec.reads_label, self._spec.untrusted)


@dataclass
class LoopEnv:
    tmp_path: Path
    db: Database
    bus: EventBus
    clock: Clock
    grants: GrantStore
    approvals: ApprovalService
    completer: ScriptedCompleter
    tools: dict[str, Tool]
    scope: PathScope
    trace: LoopTrace
    root: Path

    def add_tool(
        self,
        name: str,
        spec: ToolSpec,
        delay: float = 0.0,
        result_text: str | None = None,
        fail: str | None = None,
    ) -> LoopProbe:
        probe = LoopProbe(name, spec, self.trace, delay=delay, result_text=result_text, fail=fail)
        self.tools[name] = probe
        return probe

    async def make_runner(
        self,
        goal: str = "test goal",
        mode: Mode = Mode.OPEN,
        limits: LimitSettings | None = None,
        engine_settings: EngineSettings | None = None,
        decisions: DecisionPipeline | None = None,
        pin_model: str | None = None,
    ) -> tuple[TaskRunner, tasks.TaskRow]:
        eff_limits = limits or LimitSettings()
        eff_engine = engine_settings or EngineSettings(mode="loop")
        task_id = new_id()
        now = self.clock()

        def create(con: sqlite3.Connection) -> tasks.TaskRow:
            if not conversations.get_conversation(con, "conv_1"):
                conversations.create_conversation(con, "conv_1", "Test Conversation", now)
            return tasks.create_task(
                con,
                id=task_id,
                goal=goal,
                mode=mode.value,
                label=Label.PUBLIC,
                tainted=False,
                now=now,
                conversation_id="conv_1",
            )

        row = await self.db.write(create)
        deps = EngineDeps(
            db=self.db,
            completer=self.completer,
            tools=lambda: self.tools,
            scope=lambda: self.scope,
            file_roots=lambda: (str(self.root),),
            bus=self.bus,
            approvals=self.approvals,
            grants=self.grants,
            clock=self.clock,
            limits=lambda: eff_limits,
            decisions=decisions,
            engine_settings=lambda: eff_engine,
        )
        spec = RunSpec(goal=goal, conversation_id="conv_1", pin_model=pin_model)
        runner = TaskRunner(deps, row, spec)
        return runner, row


@pytest.fixture
def env(tmp_path: Path) -> LoopEnv:
    root = tmp_path / "shared"
    root.mkdir()
    clock = Clock()
    db = Database(tmp_path / "lilly.db")
    bus = EventBus()
    grants = GrantStore()
    approvals = ApprovalService(db, bus, clock, ttl_s=30.0)
    completer = ScriptedCompleter()
    tools: dict[str, Tool] = {}
    scope = PathScope((str(root),), deny=())
    trace = LoopTrace()
    return LoopEnv(tmp_path, db, bus, clock, grants, approvals, completer, tools, scope, trace, root)


# ---- LOOP-01: Direct answer --------------------------------------------------

async def test_loop_01_direct_answer(env: LoopEnv) -> None:
    """Direct answer from model without tool calls goes PLANNING -> DONE directly."""
    env.add_tool("probe.test", ToolSpec(Risk.R0, schema={"type": "object"}))
    env.completer.replies = [reply_text("Paris is the capital of France.")]

    runner, row = await env.make_runner(goal="What is the capital of France?")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None
    assert final_row.state is TaskState.DONE
    assert final_row.answer == "Paris is the capital of France."
    # Zero tools executed
    assert len(env.trace.log) == 0


# ---- LOOP-02: Tool -> Answer -------------------------------------------------

async def test_loop_02_tool_then_answer(env: LoopEnv) -> None:
    """Model calls one tool, receives observation, and finishes with text answer."""
    env.add_tool(
        "clock.now",
        ToolSpec(Risk.R0, schema={"type": "object"}),
        result_text="2026-10-05T12:00:00Z",
    )
    env.completer.replies = [
        reply_tools(make_call("clock.now", {})),
        reply_text("The current time is 12:00 UTC."),
    ]

    runner, row = await env.make_runner(goal="What time is it?")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None
    assert final_row.state is TaskState.DONE
    assert final_row.answer == "The current time is 12:00 UTC."

    # Verify tool execution and step recorded in DB
    steps = tasks.list_steps(env.db.reader, row.id)
    assert len(steps) == 1
    assert steps[0].step_id == "t1c1"
    assert steps[0].tool == "clock.now"
    assert steps[0].status == "done"

    # Verify second completer request saw the tool observation
    req2 = env.completer.calls[1]
    assert len(req2.messages) >= 4  # system, user, assistant, tool
    tool_msg = req2.messages[-1]
    assert tool_msg.role == "tool"
    assert "RESULT t1c1 clock.now ok" in tool_msg.content
    assert "2026-10-05T12:00:00Z" in tool_msg.content


# ---- LOOP-03: Gate - Browser errand ------------------------------------------

async def test_loop_03_browser_errand_gate(env: LoopEnv) -> None:
    """Gate test: Scripted model opens page, reads target line, and clicks it."""
    # browser.open returns rendered page elements with numbered targets
    open_snapshot = (
        "Page loaded: Example Store\n"
        "Interactive targets:\n"
        "[1] <a href=\"/categories\">Categories</a>\n"
        "[2] <button id=\"checkout\">Proceed to Checkout</button>\n"
        "[3] <a href=\"/help\">Help</a>"
    )
    env.add_tool(
        "browser.open",
        ToolSpec(
            Risk.R0,
            schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        ),
        result_text=open_snapshot,
    )
    env.add_tool(
        "browser.click",
        ToolSpec(
            Risk.R1,
            schema={
                "type": "object",
                "properties": {"target": {"type": "string"}},
                "required": ["target"],
            },
        ),
        result_text="Clicked target [2] <button id=\"checkout\">Proceed to Checkout</button>. Order summary page loaded.",
    )

    clicked_target_arg: dict[str, Any] = {}

    def capture_completer(req: CompletionRequest) -> Completed:
        turn_idx = len(env.completer.calls)
        if turn_idx == 0:
            return reply_tools(make_call("browser.open", {"url": "https://store.example.com"}))
        elif turn_idx == 1:
            # Model inspects observation from browser.open, finds line with [2] button, and clicks it
            last_msg = req.messages[-1]
            assert "[2] <button id=\"checkout\">Proceed to Checkout</button>" in last_msg.content
            target_str = "[2] <button id=\"checkout\">Proceed to Checkout</button>"
            clicked_target_arg["target"] = target_str
            return reply_tools(make_call("browser.click", {"target": target_str}))
        else:
            last_msg = req.messages[-1]
            assert "Clicked target [2]" in last_msg.content
            return reply_text("I navigated to the store and clicked the Proceed to Checkout button.")

    # We use a custom completer handler or pre-fill replies
    env.completer.replies = [
        reply_tools(make_call("browser.open", {"url": "https://store.example.com"})),
        reply_tools(make_call("browser.click", {"target": "[2] <button id=\"checkout\">Proceed to Checkout</button>"})),
        reply_text("I navigated to the store and clicked the Proceed to Checkout button."),
    ]

    runner, row = await env.make_runner(goal="Open store and click checkout button")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None
    assert final_row.state is TaskState.DONE
    assert "Proceed to Checkout" in final_row.answer

    # Verify model calls count: exactly 3
    assert len(env.completer.calls) == 3

    # Verify steps recorded
    steps = tasks.list_steps(env.db.reader, row.id)
    assert len(steps) == 2
    assert steps[0].tool == "browser.open"
    assert steps[1].tool == "browser.click"
    assert json.loads(steps[1].args_json)["target"] == "[2] <button id=\"checkout\">Proceed to Checkout</button>"


# ---- LOOP-04: Parallel read-only calls ---------------------------------------

async def test_loop_04_parallel_read_only_calls(env: LoopEnv) -> None:
    """Read-only calls in the same turn run concurrently through LaneScheduler."""
    env.add_tool("probe.a", ToolSpec(Risk.R0, schema={"type": "object"}), delay=0.1)
    env.add_tool("probe.b", ToolSpec(Risk.R0, schema={"type": "object"}), delay=0.1)

    env.completer.replies = [
        reply_tools(make_call("probe.a", {}), make_call("probe.b", {})),
        reply_text("Both reads finished."),
    ]

    runner, row = await env.make_runner(goal="Read both")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE
    # Concurrency peak was 2
    assert env.trace.peak == 2

    # Verify observations in messages are ordered t1c1 then t1c2
    req2 = env.completer.calls[1]
    tool_msgs = [m for m in req2.messages if m.role == "tool"]
    assert len(tool_msgs) == 2
    assert "RESULT t1c1 probe.a ok" in tool_msgs[0].content
    assert "RESULT t1c2 probe.b ok" in tool_msgs[1].content


# ---- LOOP-05: Serial execution for mutating tools -----------------------------

async def test_loop_05_serial_for_mutating_or_confirm_calls(env: LoopEnv) -> None:
    """Mutating calls (R1) run serially, not in parallel."""
    env.add_tool("probe.w1", ToolSpec(Risk.R1, schema={"type": "object"}), delay=0.05)
    env.add_tool("probe.w2", ToolSpec(Risk.R1, schema={"type": "object"}), delay=0.05)

    env.completer.replies = [
        reply_tools(make_call("probe.w1", {}), make_call("probe.w2", {})),
        reply_text("Both writes completed serially."),
    ]

    runner, row = await env.make_runner(goal="Write both")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE
    # Concurrency peak was 1 (serial)
    assert env.trace.peak == 1
    assert env.trace.log == [("start", "t1c1"), ("end", "t1c1"), ("start", "t1c2"), ("end", "t1c2")]


# ---- LOOP-06: Unknown tool observation ---------------------------------------

async def test_loop_06_unknown_tool_observation(env: LoopEnv) -> None:
    """Model calling nonexistent tool receives OBS_UNAVAILABLE without task failing."""
    env.add_tool("clock.now", ToolSpec(Risk.R0, schema={"type": "object"}))

    env.completer.replies = [
        reply_tools(make_call("mystery.gadget", {})),
        reply_text("Since mystery.gadget is unavailable, here is the answer."),
    ]

    runner, row = await env.make_runner(goal="Try mystery")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE

    req2 = env.completer.calls[1]
    tool_msg = req2.messages[-1]
    assert tool_msg.role == "tool"
    assert "RESULT t1c1 mystery.gadget unavailable: there is no tool with that name" in tool_msg.content
    assert "clock.now" in tool_msg.content


# ---- LOOP-07: Schema failure observation -------------------------------------

async def test_loop_07_schema_failure_observation(env: LoopEnv) -> None:
    """Invalid arguments produce OBS_INVALID_ARGS observation, loop continues."""
    env.add_tool(
        "math.sqrt",
        ToolSpec(
            Risk.R0,
            schema={
                "type": "object",
                "properties": {"number": {"type": "number", "minimum": 0}},
                "required": ["number"],
            },
        ),
    )

    env.completer.replies = [
        # Call 1: missing required 'number'
        reply_tools(make_call("math.sqrt", {})),
        # Call 2: fixed arguments
        reply_tools(make_call("math.sqrt", {"number": 16})),
        reply_text("Square root is 4."),
    ]

    runner, row = await env.make_runner(goal="Compute sqrt")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE

    # Turn 2 request saw schema error observation
    req2 = env.completer.calls[1]
    assert "RESULT t1c1 math.sqrt invalid arguments" in req2.messages[-1].content
    assert "required" in req2.messages[-1].content


# ---- LOOP-08: Policy block observation ---------------------------------------

async def test_loop_08_policy_block_observation(env: LoopEnv) -> None:
    """Tool call blocked by policy yields OBS_BLOCKED without task failing."""
    forbidden = env.tmp_path / "secret.txt"
    env.add_tool(
        "fs.read",
        ToolSpec(
            Risk.R0,
            path_args=("path",),
            schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        ),
    )

    env.completer.replies = [
        reply_tools(make_call("fs.read", {"path": str(forbidden)})),
        reply_text("I cannot read secret.txt because it is outside the allowed directory."),
    ]

    runner, row = await env.make_runner(goal="Read forbidden")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE
    assert "outside the allowed directory" in final_row.answer

    req2 = env.completer.calls[1]
    assert "RESULT t1c1 fs.read blocked by policy" in req2.messages[-1].content


# ---- LOOP-09: Tool error observation -----------------------------------------

async def test_loop_09_tool_error_observation(env: LoopEnv) -> None:
    """Tool raising ToolError yields OBS_ERROR observation, task continues."""
    env.add_tool(
        "net.fetch",
        ToolSpec(Risk.R0, schema={"type": "object"}),
        fail="connection refused to server",
    )

    env.completer.replies = [
        reply_tools(make_call("net.fetch", {})),
        reply_text("The server is offline, so I could not fetch the page."),
    ]

    runner, row = await env.make_runner(goal="Fetch server")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE

    req2 = env.completer.calls[1]
    assert "RESULT t1c1 net.fetch error:" in req2.messages[-1].content
    assert "connection refused to server" in req2.messages[-1].content


# ---- LOOP-10: User decline continues -----------------------------------------

async def test_loop_10_decline_continues(env: LoopEnv) -> None:
    """User declining an approval generates OBS_DECLINED; loop does not abort."""
    target = env.root / "file.txt"
    env.add_tool(
        "fs.write",
        ToolSpec(
            Risk.R1,
            path_args=("path",),
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        ),
    )

    env.completer.replies = [
        reply_tools(make_call("fs.write", {"path": str(target), "content": "hello"})),
        reply_text("You declined writing the file, so nothing was changed."),
    ]

    runner, row = await env.make_runner(goal="Write file", mode=Mode.ASK)

    async def decline_approval() -> None:
        async with asyncio.timeout(3.0):
            while not (pending := env.approvals.pending()):
                await asyncio.sleep(0.01)
        await env.approvals.decide(pending[0].id, approve=False, payload_hash=pending[0].payload_hash)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(runner.run())
        tg.create_task(decline_approval())

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE
    assert "declined" in final_row.answer

    req2 = env.completer.calls[1]
    assert "RESULT t1c1 fs.write declined by the user." in req2.messages[-1].content


# ---- LOOP-11: Approval expiry ends EXPIRED -----------------------------------

async def test_loop_11_approval_expiry_ends_expired(env: LoopEnv) -> None:
    """An approval that expires ends the task in EXPIRED state."""
    target = env.root / "expire.txt"
    env.add_tool(
        "fs.write",
        ToolSpec(
            Risk.R1,
            path_args=("path",),
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        ),
    )
    env.completer.replies = [reply_tools(make_call("fs.write", {"path": str(target), "content": "x"}))]

    runner, row = await env.make_runner(goal="Write expire", mode=Mode.ASK)

    async def expire_it() -> None:
        async with asyncio.timeout(3.0):
            while not (pending := env.approvals.pending()):
                await asyncio.sleep(0.01)
        # Advance clock past TTL and trigger expiry
        env.clock.advance(DEFAULT_TTL_S + 10.0)
        try:
            await env.approvals.decide(pending[0].id, approve=True, payload_hash=pending[0].payload_hash)
        except ApprovalExpired:
            pass

    async with asyncio.TaskGroup() as tg:
        tg.create_task(runner.run())
        tg.create_task(expire_it())

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None
    assert final_row.state is TaskState.EXPIRED


# ---- LOOP-12: Loop guard (notice then stop) ----------------------------------

async def test_loop_12_loop_notice_then_stop(env: LoopEnv) -> None:
    """First LOOPING advisory injects NOTICE_LOOPING; second LOOPING aborts task."""
    env.add_tool("probe.repeat", ToolSpec(Risk.R0, schema={"type": "object"}))

    # Mock decision pipeline that returns LOOPING
    class MockDecisions:
        def __init__(self) -> None:
            self.calls = 0

        def prepare(self, kind: Any) -> None:
            pass

        async def decide(self, kind: Kind, task_id: str, options: tuple[Option, ...], ctx: Context) -> Any:
            self.calls += 1
            return Outcome(kind=kind, choice=LOOPING, reason="looping detected")

    mock_dec = MockDecisions()

    env.completer.replies = [
        reply_tools(make_call("probe.repeat", {})),
        # Turn 2: repeats same tool call
        reply_tools(make_call("probe.repeat", {})),
        reply_text("Never reached"),
    ]

    runner, row = await env.make_runner(goal="Looping task", decisions=mock_dec)  # type: ignore[arg-type]
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None
    assert final_row.state is TaskState.FAILED
    assert "the task kept repeating the same steps, so it was stopped" in (final_row.error or "")

    # Notice was sent on turn 2
    req2 = env.completer.calls[1]
    notice_msgs = [m for m in req2.messages if NOTICE_LOOPING in m.content]
    assert len(notice_msgs) == 1


# ---- LOOP-13: Escalation to plan model once ----------------------------------

async def test_loop_13_escalation_once(env: LoopEnv) -> None:
    """Two consecutive turns of all-invalid calls escalate next turn to plan model once."""
    env.add_tool("clock.now", ToolSpec(Risk.R0, schema={"type": "object"}))

    env.completer.replies = [
        # Turn 1: invalid call
        reply_tools(make_call("invalid_tool_1", {})),
        # Turn 2: invalid call
        reply_tools(make_call("invalid_tool_2", {})),
        # Turn 3: should be escalated to role="plan"
        reply_tools(make_call("clock.now", {})),
        reply_text("Final answer after escalation."),
    ]

    runner, row = await env.make_runner(goal="Escalate task")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE

    # Turn 0 was "plan", Turn 1 was "act", Turn 2 (after 2 all-invalid turns) was escalated to "plan"
    roles = [req.role for req in env.completer.calls]
    assert roles[0] == "plan"
    assert roles[1] == "act"
    assert roles[2] == "plan"  # Escalated!
    assert roles[3] == "act"


# ---- LOOP-14: Budgets and FINAL notice ---------------------------------------

async def test_loop_14_budgets_and_final_notice(env: LoopEnv) -> None:
    """When budget is exhausted, reserved final call has tool_choice='none' and NOTICE_BUDGET_EXHAUSTED."""
    env.add_tool("clock.now", ToolSpec(Risk.R0, schema={"type": "object"}))

    env.completer.replies = [
        reply_tools(make_call("clock.now", {})),
        reply_tools(make_call("clock.now", {})),
        reply_text("Budget reached. Summary of what was done."),
    ]

    # Limits: max 3 model calls
    limits = LimitSettings(max_model_calls=3)
    runner, row = await env.make_runner(goal="Budget task", limits=limits)
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE
    assert "Budget reached" in final_row.answer

    # Call 3 was reserved final call
    final_req = env.completer.calls[2]
    assert final_req.tool_choice == "none"
    assert final_req.role == "write"
    exhausted_msgs = [m for m in final_req.messages if NOTICE_BUDGET_EXHAUSTED in m.content]
    assert len(exhausted_msgs) == 1


# ---- LOOP-15: Fallback final on empty text -----------------------------------

async def test_loop_15_no_text_fallback(env: LoopEnv) -> None:
    """When model returns empty text on final call, code-written FALLBACK_FINAL is used."""
    env.add_tool("clock.now", ToolSpec(Risk.R0, schema={"type": "object"}))

    env.completer.replies = [
        reply_tools(make_call("clock.now", {})),
        # Final call returns empty text
        reply_text(""),
    ]

    limits = LimitSettings(max_model_calls=2)
    runner, row = await env.make_runner(goal="Fallback task", limits=limits)
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE
    assert "I stopped because the budget for this task ran out" in final_row.answer
    assert "1 step(s) finished" in final_row.answer


# ---- LOOP-16: State transitions without RUNNING -> RUNNING -------------------

async def test_loop_16_state_transitions_no_running_to_running(env: LoopEnv) -> None:
    """Task transitions PLANNING -> RUNNING on first tool call; never transitions RUNNING -> RUNNING."""
    env.add_tool("clock.now", ToolSpec(Risk.R0, schema={"type": "object"}))

    env.completer.replies = [
        reply_tools(make_call("clock.now", {})),
        reply_tools(make_call("clock.now", {})),
        reply_text("Finished after two tool turns."),
    ]

    runner, row = await env.make_runner(goal="Transitions task")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE

    events = env.db.reader.execute(
        "SELECT payload FROM events WHERE task_id=? AND kind='state' ORDER BY seq", (row.id,)
    ).fetchall()
    states = [json.loads(e[0])["state"] for e in events]
    # States sequence must not have consecutive RUNNING
    for i in range(len(states) - 1):
        assert not (states[i] == "RUNNING" and states[i + 1] == "RUNNING")
    assert "RUNNING" in states
    assert states[-1] == "DONE"


# ---- LOOP-17: Cancellation mid-turn ------------------------------------------

async def test_loop_17_cancel_mid_turn(env: LoopEnv) -> None:
    """Cancelling a task while a step runs halts loop promptly in CANCELLED state."""
    env.add_tool("probe.slow", ToolSpec(Risk.R0, schema={"type": "object"}), delay=5.0)

    env.completer.replies = [
        reply_tools(make_call("probe.slow", {})),
        reply_text("Never reached"),
    ]

    runner, row = await env.make_runner(goal="Cancel task")

    async def cancel_after_start() -> None:
        async with asyncio.timeout(3.0):
            while env.trace.running == 0:
                await asyncio.sleep(0.01)
        runner.request_cancel("user cancelled execution")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(runner.run())
        tg.create_task(cancel_after_start())

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None
    assert final_row.state is TaskState.CANCELLED
    assert "user cancelled execution" in (final_row.error or "")


# ---- LOOP-18: Role per turn and model resolution -----------------------------

async def test_loop_18_role_model_resolution(env: LoopEnv) -> None:
    """Turn 0 uses 'plan' role, tool turns use 'act' role, budget turn uses 'write' role."""
    env.add_tool("clock.now", ToolSpec(Risk.R0, schema={"type": "object"}))

    env.completer.replies = [
        reply_tools(make_call("clock.now", {})),
        reply_text("Final"),
    ]

    limits = LimitSettings(max_model_calls=2)
    runner, row = await env.make_runner(goal="Roles task", limits=limits, pin_model="tag:special")
    await runner.run()

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None and final_row.state is TaskState.DONE

    # Turn 0 was "plan" with tag "special"
    req1 = env.completer.calls[0]
    assert req1.role == "plan"
    assert req1.tag == "special"

    # Turn 1 was "write" because max_model_calls=2 made remaining_calls=1
    req2 = env.completer.calls[1]
    assert req2.role == "write"


# ---- LOOP-19: Allowlist enforced at execution --------------------------------

async def test_loop_19_allowlist_enforced_at_execution(env: LoopEnv) -> None:
    """Tools outside allowlist are rejected with OBS_UNAVAILABLE even if present in catalog."""
    env.add_tool("clock.now", ToolSpec(Risk.R0, schema={"type": "object"}))
    disallowed = env.add_tool("forbidden.tool", ToolSpec(Risk.R0, schema={"type": "object"}))

    # Build AgentLoop directly with allowlist
    task_id = new_id()
    now = env.clock()
    def create_task_19(con: sqlite3.Connection) -> tasks.TaskRow:
        if not conversations.get_conversation(con, "conv_1"):
            conversations.create_conversation(con, "conv_1", "Test Conversation", now)
        return tasks.create_task(
            con, id=task_id, goal="Allowlist test", mode=Mode.OPEN.value,
            label=Label.PUBLIC, tainted=False, now=now, conversation_id="conv_1",
        )
    await env.db.write(create_task_19)
    rec = TaskRecord(env.db, env.bus, env.clock, task_id, TaskCtx(Label.PUBLIC, False, Mode.OPEN), TaskState.PENDING)
    await rec.state(TaskState.PLANNING)
    steps = StepExecutor(rec, env.approvals, env.grants, lambda: env.scope, LimitSettings, None, None, Brief("goal"))

    env.completer.replies = [
        # Model tries calling forbidden tool
        reply_tools(make_call("forbidden.tool", {})),
        reply_text("Forbidden was not allowed, so answering directly."),
    ]

    loop = AgentLoop(
        rec=rec,
        completer=env.completer,
        steps=steps,
        tools=lambda: env.tools,
        scope=lambda: env.scope,
        file_roots=lambda: (str(env.root),),
        limits=LimitSettings,
        engine_settings=EngineSettings,
        db=env.db,
        goal="Allowlist test",
        conversation_id="conv_1",
        tool_allowlist=frozenset({"clock.now"}),
    )

    answer = await loop.run()
    assert "Forbidden was not allowed" in answer
    # forbidden tool was never executed
    assert len(disallowed._trace.log) == 0

    req2 = env.completer.calls[1]
    tool_msg = req2.messages[-1]
    assert "RESULT t1c1 forbidden.tool unavailable: there is no tool with that name" in tool_msg.content


# ---- LOOP-20: Model permission approval preserved and resumed ----------------

async def test_loop_20_model_permission_approval_resumed(env: LoopEnv) -> None:
    """Approval for model permission transitions to APPROVAL and resumes to RUNNING/PLANNING."""
    env.add_tool(
        "personal.read",
        ToolSpec(Risk.R0, reads_label=Label.PERSONAL, schema={"type": "object"}),
        result_text="Secret personal information",
    )

    env.completer.replies = [
        NeedsGrant(["scripted"], int(Label.PERSONAL)),
        reply_tools(make_call("personal.read", {})),
        reply_text("I read your personal information."),
    ]

    runner, row = await env.make_runner(goal="Read personal", mode=Mode.OPEN)

    async def approve_model_permission() -> None:
        async with asyncio.timeout(3.0):
            while not (pending := env.approvals.pending()):
                await asyncio.sleep(0.01)
        appr = pending[0]
        assert "scripted" in appr.summary or "personal" in appr.summary
        await env.approvals.decide(appr.id, approve=True, payload_hash=appr.payload_hash)

    async with asyncio.TaskGroup() as tg:
        tg.create_task(runner.run())
        tg.create_task(approve_model_permission())

    final_row = tasks.get_task(env.db.reader, row.id)
    assert final_row is not None
    assert final_row.state is TaskState.DONE
    assert "personal information" in final_row.answer
