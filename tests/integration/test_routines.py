"""Routines: due runs start once, never pile up, and pause when they cannot or should not continue."""
from __future__ import annotations

from datetime import UTC

import pytest

from lilly.domain.errors import ConflictError, ValidationFailed
from lilly.domain.ids import new_id
from lilly.domain.schedule import Schedule
from lilly.engine.scheduler import Scheduler
from lilly.store import routines, tasks
from tests.conftest import Engine
from tests.helpers import plan, step

pytestmark = pytest.mark.asyncio
EVERY_30 = Schedule("every", every_minutes=30)


async def make(engine: Engine, schedule: Schedule = EVERY_30, agent_id: str | None = None) -> str:
    rid, now = new_id(), engine.clock()
    await engine.db.write(lambda con: routines.create_routine(con, rid, "Brief", "Say hello", agent_id, schedule, now, UTC))
    return rid


def row(engine: Engine, rid: str) -> routines.RoutineRow:
    found = routines.get_routine(engine.db.reader, rid)
    assert found is not None
    return found


def count_tasks(engine: Engine) -> int:
    return len(tasks.list_tasks(engine.db.reader, limit=100))


async def test_nothing_runs_before_it_is_due_then_one_run_starts(engine: Engine) -> None:
    sched = Scheduler(engine.db, engine.orchestrator, engine.clock, UTC)
    rid = await make(engine)
    engine.completer.replies.append(plan(answer="Hello!"))
    await sched.tick()
    assert count_tasks(engine) == 0
    engine.clock.advance(31 * 60)
    await sched.tick()
    assert count_tasks(engine) == 1
    r = row(engine, rid)
    assert r.last_state == "running" and r.last_task_id and r.next_run and r.next_run > engine.clock()
    await engine.wait(r.last_task_id)
    await sched.tick()  # records how the run ended
    r = row(engine, rid)
    assert r.last_state == "done" and r.failures == 0 and r.enabled


async def test_a_long_absence_causes_one_catch_up_run_not_one_per_missed_slot(engine: Engine) -> None:
    sched = Scheduler(engine.db, engine.orchestrator, engine.clock, UTC)
    await make(engine)
    engine.completer.replies.extend([plan(answer="a"), plan(answer="b")])
    engine.clock.advance(10 * 3600)  # twenty slots missed
    await sched.tick()
    await sched.tick()
    assert count_tasks(engine) == 1


async def test_a_routine_does_not_start_while_its_last_run_is_still_going(engine: Engine) -> None:
    sched = Scheduler(engine.db, engine.orchestrator, engine.clock, UTC)
    agent = await engine.agent(computer_allowed=True)
    rid = await make(engine, agent_id=agent)
    engine.completer.replies.append(plan(step("s1", "computer.run", command="ls"),
                                         step("s2", "llm.work", task="report", input="$s1.output")))
    engine.clock.advance(31 * 60)
    await sched.tick()
    await engine.wait_for_approval()  # the run is waiting for the person
    engine.clock.advance(31 * 60)
    await sched.tick()
    assert count_tasks(engine) == 1  # the next slot was skipped
    with pytest.raises(ConflictError):
        await sched.run_now(rid)
    await engine.orchestrator.stop_all()
    await engine.wait(row(engine, rid).last_task_id or "")
    await sched.tick()
    assert row(engine, rid).last_state in ("done", "failed", "cancelled")


async def test_run_now_starts_a_run_and_keeps_the_schedule(engine: Engine) -> None:
    sched = Scheduler(engine.db, engine.orchestrator, engine.clock, UTC)
    rid = await make(engine)
    before = row(engine, rid).next_run
    engine.completer.replies.append(plan(answer="Hi"))
    task = await sched.run_now(rid)
    await engine.wait(task.id)
    assert row(engine, rid).next_run == before and row(engine, rid).last_task_id == task.id


async def test_a_routine_whose_agent_is_gone_is_paused_with_the_reason(engine: Engine) -> None:
    sched = Scheduler(engine.db, engine.orchestrator, engine.clock, UTC)
    rid = await make(engine, agent_id="deleted-agent")
    engine.clock.advance(31 * 60)
    await sched.tick()
    r = row(engine, rid)
    assert not r.enabled and r.next_run is None and "deleted-agent" in (r.pause_reason or "")
    assert count_tasks(engine) == 0


async def test_five_failures_in_a_row_pause_and_a_success_resets_the_count(engine: Engine) -> None:
    rid = await make(engine)
    for _ in range(4):
        await engine.db.write(lambda con: routines.record_finish(con, rid, "failed", "boom"))
    assert row(engine, rid).enabled and row(engine, rid).failures == 4
    await engine.db.write(lambda con: routines.record_finish(con, rid, "done", None))
    assert row(engine, rid).failures == 0
    for _ in range(5):
        await engine.db.write(lambda con: routines.record_finish(con, rid, "failed", "boom"))
    r = row(engine, rid)
    assert not r.enabled and r.next_run is None and "5 failures" in (r.pause_reason or "")
    await engine.db.write(lambda con: routines.set_enabled(con, rid, True, engine.clock(), UTC))
    r = row(engine, rid)
    assert r.enabled and r.failures == 0 and r.pause_reason is None and r.next_run


async def test_expired_approvals_do_not_count_as_failures(engine: Engine) -> None:
    rid = await make(engine)
    for _ in range(6):
        await engine.db.write(lambda con: routines.record_finish(con, rid, "expired", None))
    assert row(engine, rid).enabled


async def test_limit_on_routines_and_the_kill_switch(engine: Engine) -> None:
    for _ in range(routines.MAX_ROUTINES):
        await make(engine)
    with pytest.raises(ValidationFailed):
        await make(engine)
    paused = await engine.db.write(lambda con: routines.pause_all(con, "paused by Stop all"))
    assert paused == routines.MAX_ROUTINES
    assert not any(r.enabled for r in routines.list_routines(engine.db.reader))


async def test_the_scheduler_can_say_when_the_next_run_is_due(engine: Engine) -> None:
    sched = Scheduler(engine.db, engine.orchestrator, engine.clock, UTC)
    assert sched.next_due() is None
    rid = await make(engine)
    due = sched.next_due()
    assert due is not None and due > engine.clock()
    await engine.db.write(lambda con: routines.set_enabled(con, rid, False, engine.clock(), UTC))
    assert sched.next_due() is None                  # a paused routine never wakes anything
