"""Taking something away from an agent, or deleting it, stops its unfinished tasks at once, even a step in progress."""
from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from lilly.domain.labels import Risk
from lilly.domain.tasks import TaskState
from lilly.domain.tools_registry import ToolSpec
from lilly.engine.orchestrator import AGENT_CHANGED, AGENT_DELETED, SubmitRequest
from lilly.store import agents as agent_store
from lilly.store import tasks
from tests.conftest import Engine
from tests.helpers import plan, step
from tests.integration.conftest import Api
from tests.integration.lab import READ, Lab, Probe, Trace

ALL_ON: dict[str, Any] = {"mode": 2, "research_allowed": True, "memory_allowed": True, "files_allowed": True,
                          "computer_allowed": True, "chat_allowed": True}


async def _running(api: Api, delay: float, agent: dict[str, Any]) -> tuple[Trace, str]:
    """Start a task of `agent` whose first step is a slow tool, and wait until that step is running."""
    trace = Trace()
    api.runtime.tools["web.search"] = Probe("web.search", READ, trace, delay=delay)
    api.provider.replies = [plan(step("s1", "web.search", query="x"), step("s2", "llm.work", task="t", input="$s1.output")),
                            "all done"]
    made = await api.send("POST", "/api/tasks", {"goal": "look", "agent_id": agent["id"]})
    task_id = str(made.json()["task"]["id"])
    async with asyncio.timeout(5):
        while trace.running == 0:
            await asyncio.sleep(0.01)
    return trace, task_id


async def _agent(api: Api, **kw: Any) -> dict[str, Any]:
    made = await api.send("POST", "/api/agents", {"name": "Fox", **ALL_ON, **kw})
    return dict(made.json()["agent"])


@pytest.mark.parametrize("change", [
    {"research_allowed": False}, {"memory_allowed": False}, {"files_allowed": False}, {"computer_allowed": False},
    {"chat_allowed": False}, {"mode": 1}, {"mode": 0}])
async def test_narrowing_an_agent_cancels_its_running_task_and_the_running_step(api: Api, change: dict[str, Any]) -> None:
    await api.sign_in()
    agent = await _agent(api)
    trace, task_id = await _running(api, 30.0, agent)
    started = time.monotonic()
    assert (await api.send("PATCH", f"/api/agents/{agent['id']}", change)).status_code == 200
    done = (await api.finished(task_id, timeout=3.0))["task"]
    assert done["state"] == "CANCELLED" and done["error"] == AGENT_CHANGED
    assert "permissions were changed" in done["error"]
    assert trace.cancelled == ["s1"] and trace.running == 0     # the step itself was stopped, not left to finish
    assert time.monotonic() - started < 2.0


async def test_widening_and_other_edits_leave_the_task_running(api: Api) -> None:
    await api.sign_in()
    agent = await _agent(api, mode=1, files_allowed=False, chat_allowed=False)
    trace, task_id = await _running(api, 0.4, agent)
    for change in ({"files_allowed": True}, {"mode": 2}, {"chat_allowed": True}, {"name": "Renamed"},
                   {"instructions": "be brief"}, {"skills": "# Skills"}, {"pet": "otto"}, {"look": {"hue": 9}}, {"model": ""}):
        assert (await api.send("PATCH", f"/api/agents/{agent['id']}", change)).status_code == 200
    done = (await api.finished(task_id))["task"]
    assert done["state"] == "DONE" and done["answer"] == "all done"
    assert trace.cancelled == []


async def test_deleting_an_agent_cancels_its_task(api: Api) -> None:
    await api.sign_in()
    agent = await _agent(api)
    trace, task_id = await _running(api, 30.0, agent)
    assert (await api.send("DELETE", f"/api/agents/{agent['id']}")).status_code == 200
    done = (await api.finished(task_id, timeout=3.0))["task"]
    assert done["state"] == "CANCELLED" and done["error"] == AGENT_DELETED
    assert trace.cancelled == ["s1"]


async def test_only_that_agents_tasks_are_stopped(api: Api) -> None:
    await api.sign_in()
    narrowed, other = await _agent(api), await _agent(api)
    trace = Trace()
    api.runtime.tools["web.search"] = Probe("web.search", READ, trace, delay=0.5)
    ids = []
    for who in (narrowed, other):
        api.provider.replies = [plan(step("s1", "web.search", query="x"), step("s2", "llm.work", task="t", input="$s1.output")),
                                "fine"]
        ids.append((await api.send("POST", "/api/tasks", {"goal": "look", "agent_id": who["id"]})).json()["task"]["id"])
        async with asyncio.timeout(5):                       # let this one reach its slow step before the next is planned
            while trace.running < len(ids):
                await asyncio.sleep(0.01)
    await api.send("PATCH", f"/api/agents/{narrowed['id']}", {"research_allowed": False})
    assert (await api.finished(ids[0], timeout=3.0))["task"]["state"] == "CANCELLED"
    assert (await api.finished(ids[1]))["task"]["state"] == "DONE"
    plain = (await api.send("POST", "/api/tasks", {"goal": "no agent"})).json()["task"]["id"]   # nor tasks without an agent
    await api.send("DELETE", f"/api/agents/{narrowed['id']}")
    assert (await api.finished(plain))["task"]["state"] in ("DONE", "FAILED")


async def test_a_task_waiting_for_approval_is_cancelled_and_its_approval_voided(api: Api) -> None:
    await api.sign_in()
    agent = await _agent(api, mode=1)
    api.provider.replies = [plan(step("s1", "memory.write", text="a fact"), step("s2", "llm.work", task="t", input="$s1.output"))]
    task_id = (await api.send("POST", "/api/tasks", {"goal": "remember", "agent_id": agent["id"]})).json()["task"]["id"]
    await api.approval()
    await api.send("PATCH", f"/api/agents/{agent['id']}", {"memory_allowed": False})
    assert (await api.finished(task_id, timeout=3.0))["task"]["state"] == "CANCELLED"
    assert (await api.get("/api/approvals?status=pending")).json()["approvals"] == []
    assert api.runtime.db.reader.execute("SELECT COUNT(*) FROM memory").fetchone()[0] == 0


async def test_a_task_started_while_the_agent_is_being_narrowed_is_not_missed(
        engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """The change lands between reading the agent and registering the task: the task must still be stopped."""
    agent_id = await engine.agent(files_allowed=True)
    real = tasks.create_task

    def create_then_narrow(con: Any, **kw: Any) -> tasks.TaskRow:
        row = real(con, **kw)
        agent_store.update_agent(con, agent_id, files_allowed=False)
        return row

    monkeypatch.setattr(tasks, "create_task", create_then_narrow)
    row = await engine.orchestrator.submit(SubmitRequest("go", agent_id=agent_id))
    done = await engine.wait(row.id)
    assert done.state is TaskState.CANCELLED and done.error == AGENT_CHANGED


async def test_a_tool_that_the_settings_switched_off_is_not_used_by_a_task_already_running(lab: Lab) -> None:
    """Settings apply at the next step: a module removed while step one runs is gone when step two comes."""
    lab.add("one.slow", delay=0.3)
    lab.add("two.next", ToolSpec(Risk.R0, path_args=(), serial=True))     # serial: it waits for step one
    row = await lab.submit(step("s1", "one.slow"), step("s2", "two.next"), step("s3", "llm.work", task="t", input="$s2.output"))
    async with asyncio.timeout(5):
        while lab.trace.running == 0:
            await asyncio.sleep(0.01)
    del lab.engine.tools["two.next"]                       # what apply_settings does when a module is turned off
    done = await lab.engine.wait(row.id)
    assert ("start", "s2") not in lab.trace.log
    assert done.state is TaskState.FAILED
    second = {r.step_id: r for r in tasks.list_steps(lab.engine.db.reader, row.id)}["s2"]
    assert (second.status, second.error) == ("failed", "tool unavailable")
