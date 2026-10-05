"""The step executor on its own, against a real database: every way a single step can end."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from lilly.domain.errors import NeedsGrant, NoModelAvailable, ProviderError
from lilly.domain.grants import GrantStore
from lilly.domain.labels import Label, Mode, Risk, TaskCtx
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext, ToolResult
from lilly.domain.settings import LimitSettings
from lilly.domain.tasks import TaskState
from lilly.domain.tools_registry import ToolSpec
from lilly.engine.approvals import ApprovalService
from lilly.engine.bus import EventBus
from lilly.engine.outcome import StepFailed, Stop
from lilly.engine.record import TaskRecord
from lilly.engine.steps import StepExecutor
from lilly.store import tasks
from lilly.store.db import Database
from lilly.tools import Tool
from tests.helpers import Clock

READ = ToolSpec(Risk.R0, path_args=())
WEB = ToolSpec(Risk.R0, egress=True, untrusted=True, path_args=())
WRITE = ToolSpec(Risk.R1, path_args=())
Behaviour = Callable[[], Awaitable[str]]


class Scripted(Tool):
    def __init__(self, spec: ToolSpec, behave: Behaviour) -> None:
        self.name, self._spec, self._behave = "probe.tool", spec, behave

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        return ToolResult(await self._behave(), Label.PUBLIC, False)


async def returns(text: str) -> str:
    return text


@dataclass
class Rig:
    db: Database
    approvals: ApprovalService
    rec: TaskRecord
    exe: StepExecutor

    async def run(self, spec: ToolSpec, behave: Behaviour, **args: object) -> str:
        st = {"id": "s1", "tool": "probe.tool", "args": args}
        return await self.exe.run(st, "s1", {}, {"probe.tool": Scripted(spec, behave)})

    def status(self) -> tuple[str, str | None]:
        row = tasks.list_steps(self.db.reader, "t1")[0]
        return row.status, row.error


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[Rig]:
    db, bus, clock = Database(tmp_path / "lilly.db"), EventBus(), Clock()
    approvals = ApprovalService(db, bus, clock, ttl_s=0.1)
    await db.write(lambda con: tasks.create_task(con, id="t1", goal="g", mode=1, label=Label.PUBLIC, tainted=False,
                                                 now=clock()))
    await db.write(lambda con: tasks.create_steps(con, "t1", [("s1", "probe.tool", "{}")]))
    rec = TaskRecord(db, bus, clock, "t1", TaskCtx(Label.PUBLIC, False, Mode.ASK), TaskState.PENDING)
    await rec.state(TaskState.PLANNING)
    await rec.state(TaskState.RUNNING)
    limits = LimitSettings(step_timeout_s=1)
    yield Rig(db, approvals, rec, StepExecutor(rec, approvals, GrantStore(), lambda: PathScope([]), lambda: limits, None))
    db.close()


async def test_a_tool_that_is_not_there_fails_the_step(rig: Rig) -> None:
    with pytest.raises(StepFailed, match="not available"):
        await rig.exe.run({"id": "s1", "tool": "probe.tool", "args": {}}, "s1", {}, {})
    assert rig.status() == ("failed", "tool unavailable")


async def test_an_argument_that_uses_a_missing_result_fails_the_step(rig: Rig) -> None:
    with pytest.raises(StepFailed, match="result of step s0"):
        await rig.run(READ, lambda: returns("x"), text="see $s0.output")
    assert rig.status()[0] == "failed"


async def test_an_empty_reply_is_a_failed_step_with_the_reason_recorded(rig: Rig) -> None:
    with pytest.raises(StepFailed, match="returned nothing"):
        await rig.run(READ, lambda: returns("  "))
    assert rig.status() == ("failed", "it returned nothing")


async def test_a_step_that_overruns_its_time_limit_fails_and_a_failed_web_call_still_taints_the_task(rig: Rig) -> None:
    async def forever() -> str:
        await asyncio.sleep(30)
        return "late"

    with pytest.raises(StepFailed, match="it timed out"):
        await rig.run(WEB, forever)
    assert rig.rec.ctx.tainted and rig.status() == ("failed", "it timed out")


@pytest.mark.parametrize("raised", [RuntimeError("boom at /home/me/secret"), OSError("disk gone")])
async def test_a_tool_that_crashes_fails_the_step_without_leaking_the_error(rig: Rig, raised: Exception) -> None:
    async def crash() -> str:
        raise raised

    with pytest.raises(StepFailed, match="Something went wrong inside Lilly") as failed:
        await rig.run(READ, crash)
    status, error = rig.status()
    assert status == "failed" and error is not None and "secret" not in error and "disk" not in error
    assert "secret" not in failed.value.reason


class Spy(Tool):
    """A tool that keeps the context it was given, like a thread-backed tool polling `cancelled`."""

    name = "probe.tool"
    spec = READ

    def __init__(self, behave: Behaviour) -> None:
        self.behave, self.ctx = behave, None

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        self.ctx = ctx
        assert not ctx.cancelled()
        return ToolResult(await self.behave(), Label.PUBLIC, False)


async def test_a_tool_is_told_to_stop_when_its_step_times_out_and_when_it_ends(rig: Rig) -> None:
    async def forever() -> str:
        await asyncio.sleep(30)
        return "late"

    slow = Spy(forever)
    with pytest.raises(StepFailed, match="timed out"):
        await rig.exe.run({"id": "s1", "tool": "probe.tool", "args": {}}, "s1", {}, {"probe.tool": slow})
    assert slow.ctx is not None and slow.ctx.cancelled()
    assert not rig.rec.cancelled                         # the other steps of the task are not told to stop
    quick = Spy(lambda: returns("fine"))
    await rig.exe.run({"id": "s1", "tool": "probe.tool", "args": {}}, "s1", {}, {"probe.tool": quick})
    assert quick.ctx is not None and quick.ctx.cancelled()


@pytest.mark.parametrize("raised, words", [(ProviderError(False, status=401), "API key"),
                                           (NoModelAvailable("all busy"), "all busy")])
async def test_a_model_problem_inside_a_tool_is_explained_in_plain_words(rig: Rig, raised: Exception, words: str) -> None:
    async def broken() -> str:
        raise raised

    with pytest.raises(StepFailed, match=words):
        await rig.run(READ, broken)


async def test_a_change_nobody_answers_in_time_expires_the_task_and_does_nothing(rig: Rig) -> None:
    ran = False

    async def work() -> str:
        nonlocal ran
        ran = True
        return "done"

    with pytest.raises(Stop) as stop:
        await rig.run(WRITE, work)
    assert stop.value.state is TaskState.EXPIRED and not ran
    assert rig.status() == ("skipped", "approval timed out")


async def test_a_stopped_step_is_marked_as_skipped_with_the_reason(rig: Rig) -> None:
    await rig.exe.abandon("s1")
    assert rig.status() == ("skipped", "stopped because another step failed")


async def decide_next(rig: Rig, approve: bool) -> None:
    async with asyncio.timeout(2):
        while not (pending := rig.approvals.pending()):
            await asyncio.sleep(0.005)
    await rig.approvals.decide(pending[0].id, approve=approve, payload_hash=pending[0].payload_hash, choice="m1")


async def test_a_model_permission_that_is_declined_cancels_the_task(rig: Rig) -> None:
    async def needs() -> str:
        raise NeedsGrant(["m1"], int(Label.PERSONAL))

    answer = asyncio.create_task(decide_next(rig, approve=False))
    with pytest.raises(Stop, match="declined to share") as stop:
        await rig.exe.with_model_permission(needs, "s1", TaskState.RUNNING)
    await answer
    assert stop.value.state is TaskState.CANCELLED


async def test_a_model_permission_nobody_answers_expires_the_task(rig: Rig) -> None:
    async def needs() -> str:
        raise NeedsGrant(["m1"], int(Label.PERSONAL))

    with pytest.raises(Stop, match="no data was shared") as stop:
        await rig.exe.with_model_permission(needs, "s1", TaskState.RUNNING)
    assert stop.value.state is TaskState.EXPIRED


async def test_asking_for_model_permission_gives_up_after_three_grants_that_do_not_help(rig: Rig) -> None:
    async def needs() -> str:
        raise NeedsGrant(["m1"], int(Label.PERSONAL))

    async def approve_three() -> None:
        for _ in range(3):
            await decide_next(rig, approve=True)

    answers = asyncio.create_task(approve_three())
    with pytest.raises(Stop, match="no model could be given permission"):
        await rig.exe.with_model_permission(needs, "s1", TaskState.RUNNING)
    await answers


class Writer(Tool):
    """A tool that writes its answer a little at a time, like llm.work."""

    name = "probe.tool"
    spec = READ

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        assert ctx.on_text is not None
        ctx.on_text("Hel")
        return ToolResult("Hello", Label.PUBLIC, False)


async def test_text_written_during_a_step_is_published_for_the_live_view_but_not_stored(rig: Rig) -> None:
    feed = rig.rec.bus.subscribe()
    pending = asyncio.ensure_future(anext(feed))
    await asyncio.sleep(0)                      # let the subscription register
    out = await rig.exe.run({"id": "s1", "tool": "probe.tool", "args": {}}, "s1", {}, {"probe.tool": Writer()})
    assert out == "Hello"
    async with asyncio.timeout(2):
        while True:
            message = await pending
            if message["type"] == "text":
                break
            pending = asyncio.ensure_future(anext(feed))
    assert message == {"type": "text", "task_id": "t1", "step_id": "s1", "text": "Hel"}
    kinds = {row[0] for row in rig.db.reader.execute("select kind from events where task_id = 't1'")}
    assert "text" not in kinds
    await feed.aclose()
