"""Laya assist inside real tasks: a doubted step asks first, a finished reply is checked in the background,
and nothing a decider says can make anything easier."""
from __future__ import annotations

import asyncio
import itertools
import logging
from dataclasses import dataclass, field, replace

import pytest

from lilly.domain.decisions import (
    DIRECT,
    DRIFTS,
    FITS,
    FOLLOWS,
    NEEDS_TOOLS,
    OFF,
    Answer,
    ChainStep,
    Kind,
    Request,
    with_assist,
)
from lilly.domain.ids import new_id
from lilly.domain.labels import Mode, Verdict
from lilly.domain.payload import payload_hash
from lilly.domain.tasks import TaskState
from lilly.engine.orchestrator import SubmitRequest
from lilly.engine.steps import add_doubt
from lilly.store import agents as agent_store
from lilly.store import decisions, tasks
from lilly.store.events import latest
from tests.helpers import plan, step
from tests.integration.lab import READ, WRITE, Lab

GOAL = "tidy my downloads folder"
RULES = "Never touch the Taxes folder."


@dataclass
class FakeLaya:
    """Stands in for Laya: answers each question with what it was told to, records what it was asked."""

    says: dict[Kind, str | None] = field(default_factory=dict)
    name: str = "laya"
    requests: list[Request] = field(default_factory=list)
    warmed: int = 0
    delay: float = 0.0
    gate: asyncio.Event | None = None
    crash: bool = False
    cancelled: bool = False

    def warm(self) -> None:
        self.warmed += 1

    async def decide(self, request: Request) -> Answer | None:
        self.requests.append(request)
        try:
            if self.gate is not None:
                await self.gate.wait()
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.crash:
            raise RuntimeError("laya fell over")
        choice = self.says.get(request.kind)
        return Answer("laya", choice, 0.95) if choice else None


def laya(lab: Lab, kind: Kind, says: str | None, *, act: bool = True, **kw: object) -> FakeLaya:
    fake = FakeLaya({kind: says}, **kw)       # type: ignore[arg-type]
    lab.deciders["laya"] = fake
    lab.decisions[0] = with_assist(lab.decisions[0], kind, True, act)
    return fake


def quick(lab: Lab, kind: Kind, seconds: float = 0.1) -> None:
    """Shorten how long Laya has for this question, so a test about slowness stays quick."""
    mine = lab.decisions[0].for_kind(kind)
    short = replace(mine, chain=tuple(ChainStep(s.decider, s.min_confidence, seconds) for s in mine.chain))
    lab.decisions[0] = replace(lab.decisions[0], kinds={**lab.decisions[0].kinds, kind.value: short})


async def new_agent(lab: Lab, mode: Mode, instructions: str) -> str:
    agent_id = new_id()
    await lab.engine.db.write(lambda con: agent_store.create_agent(
        con, agent_id, "Tester", instructions, int(mode), lab.engine.clock(), files_allowed=True))
    return agent_id


async def change_task(lab: Lab, mode: Mode = Mode.OPEN, instructions: str = "") -> tasks.TaskRow:
    """A task whose plan is one step that changes something, then the writing of the reply."""
    tools = lab.decisions[0].for_kind(Kind.TOOLS)    # with a real goal the planner would be shown only some tools
    lab.decisions[0] = replace(lab.decisions[0], kinds={**lab.decisions[0].kinds, "tools": replace(tools, enabled=False)})
    lab.add("probe.change", WRITE)
    lab.engine.completer.replies = [plan(step("s1", "probe.change", path="/x"),
                                         step("s2", "llm.work", task="x", input="$s1.output")), "done"]
    agent = await new_agent(lab, mode, instructions)
    return await lab.engine.orchestrator.submit(SubmitRequest(GOAL, agent_id=agent))


# ---- the plan check -----------------------------------------------------------------------------------
async def test_a_change_that_laya_doubts_asks_first_even_though_policy_alone_would_allow_it(lab: Lab) -> None:
    fake = laya(lab, Kind.PLAN, OFF)
    row = await change_task(lab, instructions=RULES)
    pending = await lab.engine.wait_for_approval()
    assert "Laya doubts this step matches your request" in pending.summary
    assert tasks.get_task(lab.engine.db.reader, row.id).state is TaskState.WAITING_APPROVAL   # type: ignore[union-attr]
    assert ("start", "s1") not in lab.trace.log
    asked = [r for r in fake.requests if r.kind is Kind.PLAN]
    assert len(asked) == 1
    text = asked[0].context.text
    assert GOAL in text and RULES in text and "probe.change" in text
    assert pending.payload_hash == payload_hash(row.id, "s1", "step", {"tool": "probe.change", "args": {"path": "/x"}})
    await lab.engine.approvals.decide(pending.id, approve=True, payload_hash=pending.payload_hash)
    assert (await lab.engine.wait(row.id)).state is TaskState.DONE
    assert ("end", "s1") in lab.trace.log


async def test_declining_a_doubted_step_stops_the_task_before_the_step_runs(lab: Lab) -> None:
    laya(lab, Kind.PLAN, OFF)
    row = await change_task(lab)
    pending = await lab.engine.wait_for_approval()
    await lab.engine.approvals.decide(pending.id, approve=False, payload_hash=pending.payload_hash)
    done = await lab.engine.wait(row.id)
    assert done.state is TaskState.CANCELLED and lab.trace.log == []


@pytest.mark.parametrize("answer", [FITS, None])
async def test_a_step_that_fits_or_that_laya_cannot_judge_runs_exactly_as_before(lab: Lab, answer: str | None) -> None:
    fake = laya(lab, Kind.PLAN, answer)
    row = await change_task(lab)
    assert (await lab.engine.wait(row.id)).state is TaskState.DONE
    assert not lab.engine.approvals.pending() and ("end", "s1") in lab.trace.log
    assert len([r for r in fake.requests if r.kind is Kind.PLAN]) == 1


@pytest.mark.parametrize("failure", ["crash", "slow"])
async def test_a_laya_that_fails_or_is_too_slow_changes_nothing(lab: Lab, failure: str) -> None:
    laya(lab, Kind.PLAN, OFF, crash=failure == "crash", delay=5.0 if failure == "slow" else 0.0)
    quick(lab, Kind.PLAN)
    row = await change_task(lab)
    assert (await lab.engine.wait(row.id)).state is TaskState.DONE
    assert not lab.engine.approvals.pending()


async def test_in_watch_mode_the_answer_is_only_logged(lab: Lab) -> None:
    laya(lab, Kind.PLAN, OFF, act=False)
    row = await change_task(lab)
    assert (await lab.engine.wait(row.id)).state is TaskState.DONE
    assert not lab.engine.approvals.pending()
    logged = [r for r in decisions.recent(lab.engine.db.reader, 50) if r.kind == "plan"]
    assert [(r.decider, r.choice, r.shadow) for r in logged] == [("laya", OFF, True)]


async def test_a_step_that_only_reads_is_never_put_to_laya(lab: Lab) -> None:
    fake = laya(lab, Kind.PLAN, OFF)
    lab.add("probe.read", READ)
    lab.engine.completer.replies = ["ok"]
    row = await lab.submit(step("s1", "probe.read"), step("s2", "llm.work", task="x", input="$s1.output"))
    assert (await lab.engine.wait(row.id)).state is TaskState.DONE
    assert fake.requests == []


async def test_a_step_that_already_needs_approval_is_not_put_to_laya_and_keeps_its_own_reason(lab: Lab) -> None:
    fake = laya(lab, Kind.PLAN, OFF)
    row = await change_task(lab, mode=Mode.ASK)
    pending = await lab.engine.wait_for_approval()
    assert "Laya" not in pending.summary and fake.requests == []
    await lab.engine.approvals.decide(pending.id, approve=True, payload_hash=pending.payload_hash)
    assert (await lab.engine.wait(row.id)).state is TaskState.DONE


async def test_by_default_laya_assist_is_not_asked_at_all(lab: Lab) -> None:
    fake = FakeLaya({Kind.PLAN: OFF, Kind.REPLY: DRIFTS})
    lab.deciders["laya"] = fake
    for start in (change_task, reply_task):
        assert (await lab.engine.wait((await start(lab)).id)).state is TaskState.DONE
    await asyncio.sleep(0.05)
    assert fake.requests == [] and fake.warmed == 0
    assert {r.kind for r in decisions.recent(lab.engine.db.reader, 100)}.isdisjoint({"plan", "reply"})


async def test_laya_is_warmed_when_a_task_starts_so_it_is_ready_for_the_first_risky_step(lab: Lab) -> None:
    fake = laya(lab, Kind.PLAN, FITS)
    row = await change_task(lab)
    assert (await lab.engine.wait(row.id)).state is TaskState.DONE
    assert fake.warmed >= 1


@pytest.mark.parametrize("verdict, choice", list(itertools.product(Verdict, [FITS, OFF, None, "allow", "", "ALLOW"])))
def test_a_decider_can_make_a_step_more_careful_and_never_less(verdict: Verdict, choice: str | None) -> None:
    after, why = add_doubt(verdict, "policy said so", choice)
    assert after >= verdict
    if choice != OFF or verdict is not Verdict.ALLOW:
        assert (after, why) == (verdict, "policy said so")
    else:
        assert after is Verdict.NEEDS_APPROVAL and "Laya doubts" in why


# ---- the reply check -----------------------------------------------------------------------------------
async def reply_task(lab: Lab, instructions: str = RULES) -> tasks.TaskRow:
    lab.engine.completer.replies = [plan(answer="Here is your tidy folder.")]
    agent = await new_agent(lab, Mode.OPEN, instructions)
    return await lab.engine.orchestrator.submit(SubmitRequest(GOAL, agent_id=agent))


async def recorded(lab: Lab, task_id: str, timeout: float = 5.0):  # type: ignore[no-untyped-def]
    async with asyncio.timeout(timeout):
        while (event := latest(lab.engine.db.reader, task_id, "reply_check")) is None:
            await asyncio.sleep(0.01)
    return event


async def test_the_reply_is_checked_after_the_task_is_done_without_holding_it_back(lab: Lab) -> None:
    gate = asyncio.Event()
    fake = laya(lab, Kind.REPLY, DRIFTS, gate=gate)
    seen: list[dict[str, object]] = []

    async def listen() -> None:
        async for message in lab.engine.bus.subscribe():
            seen.append(message)

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0)
    row = await reply_task(lab)
    done = await lab.engine.wait(row.id)
    assert done.state is TaskState.DONE and done.answer == "Here is your tidy folder."   # finished first
    async with asyncio.timeout(5):
        while not fake.requests:
            await asyncio.sleep(0.01)
    assert latest(lab.engine.db.reader, row.id, "reply_check") is None                   # Laya is still thinking
    gate.set()
    event = await recorded(lab, row.id)
    assert event.payload == {"choice": DRIFTS, "confidence": 0.95, "decider": "laya"} and event.prov == "system"
    text = fake.requests[0].context.text
    assert GOAL in text and RULES in text and "Here is your tidy folder." in text
    async with asyncio.timeout(5):
        while not any(m.get("kind") == "reply_check" for m in seen):                      # the screen is told
            await asyncio.sleep(0.01)
    listener.cancel()
    assert not any(r.kind is Kind.REPLY and r.task_id != row.id for r in fake.requests)


async def test_watch_mode_logs_the_reply_check_but_records_nothing_on_the_task(lab: Lab) -> None:
    laya(lab, Kind.REPLY, FOLLOWS, act=False)
    row = await reply_task(lab)
    await lab.engine.wait(row.id)
    async with asyncio.timeout(5):
        while not [r for r in decisions.recent(lab.engine.db.reader, 50) if r.kind == "reply"]:
            await asyncio.sleep(0.01)
    assert latest(lab.engine.db.reader, row.id, "reply_check") is None


@pytest.mark.parametrize("failure", ["crash", "slow", "silent"])
async def test_a_reply_check_that_fails_times_out_or_has_no_answer_leaves_the_task_untouched(
        lab: Lab, failure: str, caplog: pytest.LogCaptureFixture) -> None:
    fake = laya(lab, Kind.REPLY, None if failure == "silent" else DRIFTS, crash=failure == "crash",
                delay=5.0 if failure == "slow" else 0.0)
    quick(lab, Kind.REPLY)
    with caplog.at_level(logging.ERROR):
        row = await reply_task(lab)
        done = await lab.engine.wait(row.id)
        async with asyncio.timeout(5):
            while not fake.requests or lab.engine.orchestrator._replies._tasks:
                await asyncio.sleep(0.01)
    assert done.state is TaskState.DONE and latest(lab.engine.db.reader, row.id, "reply_check") is None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_closing_while_a_check_is_pending_cancels_it_cleanly(lab: Lab, caplog: pytest.LogCaptureFixture) -> None:
    fake = laya(lab, Kind.REPLY, DRIFTS, gate=asyncio.Event())    # never released
    row = await reply_task(lab)
    await lab.engine.wait(row.id)
    async with asyncio.timeout(5):
        while not fake.requests:
            await asyncio.sleep(0.01)
    with caplog.at_level(logging.ERROR):
        await lab.engine.orchestrator.aclose()
    assert fake.cancelled and not lab.engine.orchestrator._replies._tasks
    assert latest(lab.engine.db.reader, row.id, "reply_check") is None
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_a_task_that_did_not_finish_has_no_reply_to_check(lab: Lab) -> None:
    fake = laya(lab, Kind.REPLY, DRIFTS)
    lab.add("probe.bad", READ, fail="it broke")
    lab.engine.completer.replies = [plan(step("s1", "probe.bad"), step("s2", "llm.work", task="x", input="$s1.output"))] * 2
    row = await lab.engine.orchestrator.submit(SubmitRequest(GOAL, agent_id=await new_agent(lab, Mode.OPEN, "")))
    assert (await lab.engine.wait(row.id)).state is TaskState.FAILED
    await asyncio.sleep(0.05)
    assert [r for r in fake.requests if r.kind is Kind.REPLY] == []


# ---- the route question: answer without the tool list ---------------------------------------------------------
async def ask(lab: Lab, goal: str = "what is the capital of France?") -> str:
    row = await lab.engine.orchestrator.submit(SubmitRequest(goal))
    return (await lab.engine.wait(row.id)).id


def outcomes(lab: Lab) -> list[str]:
    return [r.outcome for r in decisions.recent(lab.engine.db.reader, 50, Kind.ROUTE)]


async def test_a_direct_question_is_answered_by_a_quick_call_that_never_sees_the_tool_list(lab: Lab) -> None:
    lab.add("probe.read")
    fake = laya(lab, Kind.ROUTE, DIRECT)
    lab.engine.completer.replies = [plan(answer="Paris.")]
    task_id = await ask(lab)
    row = tasks.get_task(lab.engine.db.reader, task_id)
    assert row.state is TaskState.DONE and row.answer == "Paris."          # type: ignore[union-attr]
    (call,) = lab.engine.completer.calls
    assert call.quick and "probe.read" not in call.messages[1].content
    assert len([r for r in fake.requests if r.kind is Kind.ROUTE]) == 1 and outcomes(lab) == ["accepted"]


async def test_when_the_quick_model_asks_for_tools_the_normal_planner_runs_and_laya_is_marked_wrong(lab: Lab) -> None:
    lab.add("probe.read")
    laya(lab, Kind.ROUTE, DIRECT)
    lab.engine.completer.replies = [plan(), plan(step("s1", "probe.read"), step("s2", "llm.work", task="x", input="$s1.output")), "done"]
    task_id = await ask(lab, "probe read my notes")
    assert tasks.get_task(lab.engine.db.reader, task_id).state is TaskState.DONE        # type: ignore[union-attr]
    first, second = lab.engine.completer.calls[:2]
    assert first.quick and not second.quick and "probe.read" in second.messages[1].content
    assert outcomes(lab) == ["corrected"]


@pytest.mark.parametrize("says", [NEEDS_TOOLS, None])
async def test_needs_tools_or_no_answer_plans_as_before(lab: Lab, says: str | None) -> None:
    lab.add("probe.read")
    laya(lab, Kind.ROUTE, says)
    lab.engine.completer.replies = [plan(answer="Paris.")]
    task_id = await ask(lab)
    assert tasks.get_task(lab.engine.db.reader, task_id).state is TaskState.DONE         # type: ignore[union-attr]
    (call,) = lab.engine.completer.calls
    assert not call.quick and "probe.read" in call.messages[1].content


async def test_watching_only_changes_nothing_and_still_labels_laya_by_what_happened(lab: Lab) -> None:
    lab.add("probe.read")
    laya(lab, Kind.ROUTE, DIRECT, act=False)
    lab.engine.completer.replies = [plan(answer="Paris.")]
    task_id = await ask(lab)
    assert tasks.get_task(lab.engine.db.reader, task_id).state is TaskState.DONE         # type: ignore[union-attr]
    (call,) = lab.engine.completer.calls
    assert not call.quick and "probe.read" in call.messages[1].content
    assert outcomes(lab) == ["accepted"]            # the planner answered without tools too, as Laya said


async def test_a_laya_that_fails_leaves_the_task_unaffected(lab: Lab) -> None:
    laya(lab, Kind.ROUTE, DIRECT, crash=True)
    lab.engine.completer.replies = [plan(answer="Paris.")]
    task_id = await ask(lab)
    assert tasks.get_task(lab.engine.db.reader, task_id).state is TaskState.DONE         # type: ignore[union-attr]


async def test_laya_is_warmed_for_the_route_question_when_a_task_starts(lab: Lab) -> None:
    fake = laya(lab, Kind.ROUTE, NEEDS_TOOLS)
    lab.engine.completer.replies = [plan(answer="ok")]
    await ask(lab)
    assert fake.warmed >= 1
