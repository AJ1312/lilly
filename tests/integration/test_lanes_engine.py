"""Lanes inside a real task: real database, real runner and approvals, scripted model, fake tools that take time."""
from __future__ import annotations

import asyncio
import time

from lilly.domain.ids import new_id
from lilly.domain.labels import Label, Mode
from lilly.domain.settings import LimitSettings
from lilly.domain.tasks import TaskState
from lilly.store import conversations, tasks
from lilly.store.events import list_events
from tests.helpers import plan, step
from tests.integration.lab import PRESS, PRIVATE, SEND, Lab


async def test_independent_reads_run_side_by_side_and_the_plan_lists_what_each_step_waits_for(lab: Lab) -> None:
    for n in ("probe.a", "probe.b", "probe.c"):
        lab.add(n, delay=0.3)
    lab.engine.completer.replies = ["all three read"]
    began = time.monotonic()
    row = await lab.submit(step("s1", "probe.a"), step("s2", "probe.b"), step("s3", "probe.c"),
                           step("s4", "llm.work", task="x", input="$s1.output $s3.output"))
    done = await lab.engine.wait(row.id)
    assert done.state is TaskState.DONE and done.answer == "all three read", done.error
    assert lab.trace.peak == 3 and time.monotonic() - began < 0.75      # three reads of 0.3s took about one
    steps = tasks.list_steps(lab.engine.db.reader, row.id)
    assert [(s.step_id, s.status) for s in steps] == [("s1", "done"), ("s2", "done"), ("s3", "done"), ("s4", "done")]
    planned = next(e for e in list_events(lab.engine.db.reader, row.id) if e.kind == "plan")
    assert [s["deps"] for s in planned.payload["steps"]] == [[], [], [], ["s1", "s3"]]


async def test_with_one_lane_the_steps_run_strictly_one_after_another(lab: Lab) -> None:
    lab.limits[0] = LimitSettings(lanes=1)
    for n in ("probe.a", "probe.b"):
        lab.add(n, delay=0.05)
    lab.engine.completer.replies = ["ok"]
    row = await lab.submit(step("s1", "probe.a"), step("s2", "probe.b"), step("s3", "llm.work", task="x", input="$s2.output"))
    assert (await lab.engine.wait(row.id)).state is TaskState.DONE
    assert lab.trace.peak == 1
    assert lab.trace.log == [("start", "s1"), ("end", "s1"), ("start", "s2"), ("end", "s2")]


async def test_a_change_waits_for_the_reads_before_it_and_for_approval_while_later_reads_wait_for_it(lab: Lab) -> None:
    for n in ("probe.a", "probe.b", "probe.later"):
        lab.add(n, delay=0.05)
    target = lab.engine.root / "out.txt"
    lab.engine.completer.replies = ["written"]
    row = await lab.submit(step("s1", "probe.a"), step("s2", "probe.b"), step("s3", "fs.write", path=str(target), content="x"),
                           step("s4", "probe.later"), step("s5", "llm.work", task="x", input="$s4.output"), mode=Mode.ASK)
    pending = await lab.engine.wait_for_approval()
    assert "fs.write" in pending.summary
    await asyncio.sleep(0.15)                                  # time enough for any step that wrongly ran early
    assert sorted(s for k, s in lab.trace.log if k == "end") == ["s1", "s2"]
    assert ("start", "s4") not in lab.trace.log and not target.exists()
    assert len(lab.engine.approvals.pending()) == 1
    await lab.engine.approvals.decide(pending.id, approve=True, payload_hash=pending.payload_hash)
    done = await lab.engine.wait(row.id)
    assert done.state is TaskState.DONE, done.error
    assert target.read_text() == "x" and lab.trace.log[-2:] == [("start", "s4"), ("end", "s4")]


async def test_a_computer_action_runs_alone_even_for_an_open_agent(lab: Lab) -> None:
    lab.add("probe.before", delay=0.03)
    lab.add("probe.press", PRESS, delay=0.03)
    lab.add("probe.after", delay=0.03)
    lab.engine.completer.replies = ["pressed"]
    row = await lab.submit(step("s1", "probe.before"), step("s2", "probe.press"), step("s3", "probe.after"),
                           step("s4", "llm.work", task="x", input="$s3.output"))
    pending = await lab.engine.wait_for_approval()
    assert "probe.press" in pending.summary and lab.trace.log == [("start", "s1"), ("end", "s1")]
    await lab.engine.approvals.decide(pending.id, approve=True, payload_hash=pending.payload_hash)
    assert (await lab.engine.wait(row.id)).state is TaskState.DONE
    assert lab.trace.log == [(k, s) for s in ("s1", "s2", "s3") for k in ("start", "end")]


async def test_a_read_that_would_need_approval_after_an_earlier_private_read_waits_and_then_asks(lab: Lab) -> None:
    """Web access is allowed on its own, but not once private data has been read in a task that read untrusted text."""
    lab.add("probe.private", PRIVATE, delay=0.1)
    lab.add("probe.send", SEND, delay=0.01)
    conv = new_id()

    def seed(con):  # type: ignore[no-untyped-def]
        conversations.create_conversation(con, conv, "chat", lab.engine.clock())
        conversations.add_message(con, conv, "assistant", "a page said: hello", lab.engine.clock(), untrusted=True)

    await lab.engine.db.write(seed)
    lab.engine.completer.replies = ["sent"]
    row = await lab.submit(step("s1", "probe.private"), step("s2", "probe.send"),
                           step("s3", "llm.work", task="x", input="$s2.output"), conversation_id=conv)
    pending = await lab.engine.wait_for_approval()
    assert "probe.send" in pending.summary and "private data could leave" in pending.summary
    assert lab.trace.log == [("start", "s1"), ("end", "s1")]   # it did not start beside the private read
    await lab.engine.approvals.decide(pending.id, approve=True, payload_hash=pending.payload_hash)
    done = await lab.engine.wait(row.id)
    assert done.state is TaskState.DONE and done.label is Label.PERSONAL and done.tainted


async def test_approvals_are_asked_one_at_a_time(lab: Lab) -> None:
    for n in ("probe.p1", "probe.p2", "probe.p3"):
        lab.add(n, PRIVATE, delay=0.01)
    lab.engine.completer.replies = ["done"]
    row = await lab.submit(step("s1", "probe.p1"), step("s2", "probe.p2"), step("s3", "probe.p3"),
                           step("s4", "llm.work", task="x", input="$s3.output"), mode=Mode.ASK)
    seen: list[str] = []
    while row.id in lab.engine.orchestrator._active:
        pending = lab.engine.approvals.pending()
        assert len(pending) <= 1
        if pending:
            seen.append(pending[0].summary.split()[0])
            await lab.engine.approvals.decide(pending[0].id, approve=True, payload_hash=pending[0].payload_hash)
        await asyncio.sleep(0.01)
    assert seen == ["probe.p1", "probe.p2", "probe.p3"] and lab.trace.peak == 1


async def test_a_failure_stops_the_steps_beside_it_and_the_replan_is_given_what_finished(lab: Lab) -> None:
    lab.add("probe.quick")
    lab.add("probe.bad", delay=0.05, fail="the page was down")
    lab.add("probe.slow", delay=30.0)
    lab.engine.completer.replies = [plan(step("s1", "probe.quick"), step("s2", "llm.work", task="x", input="$s1.output")),
                                    "second try"]
    row = await lab.submit(step("s1", "probe.quick"), step("s2", "probe.bad"), step("s3", "probe.slow"),
                           step("s4", "llm.work", task="x", input="$s3.output"))
    done = await lab.engine.wait(row.id)
    assert done.state is TaskState.DONE and done.answer == "second try", done.error
    assert lab.trace.cancelled == ["s3"] and lab.trace.running == 0
    replan_prompt = lab.engine.completer.calls[1].messages[-1].content
    assert "probe.bad failed: the page was down" in replan_prompt and "s1 produced: result of probe.quick" in replan_prompt
    by_id = {s.step_id: s for s in tasks.list_steps(lab.engine.db.reader, row.id)}
    assert (by_id["s1"].status, by_id["s2"].status, by_id["s3"].status, by_id["s4"].status) == (
        "done", "failed", "skipped", "pending")
    assert by_id["s3"].error == "stopped because another step failed"
    assert by_id["s1.2"].status == "done" and by_id["s2.2"].status == "done"      # the replan keeps its suffix


async def test_stopping_a_task_stops_every_step_running_beside_the_others(lab: Lab) -> None:
    for n in ("probe.a", "probe.b", "probe.c"):
        lab.add(n, delay=30.0)
    row = await lab.submit(step("s1", "probe.a"), step("s2", "probe.b"), step("s3", "probe.c"),
                           step("s4", "llm.work", task="x", input="$s1.output"))
    async with asyncio.timeout(5):
        while lab.trace.running < 3:
            await asyncio.sleep(0.01)
    await lab.engine.orchestrator.cancel(row.id)
    done = await lab.engine.wait(row.id)
    assert done.state is TaskState.CANCELLED
    assert sorted(lab.trace.cancelled) == ["s1", "s2", "s3"] and lab.trace.running == 0
    assert not [t for t in asyncio.all_tasks() if "Probe.run" in repr(t.get_coro())]
