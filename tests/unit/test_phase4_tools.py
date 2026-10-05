"""Unit tests for Phase 4 control tools: result.read, agent.plan, agent.ask."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lilly.domain.clock import Clock
from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Label, Mode
from lilly.domain.ports import ToolContext
from lilly.store.db import Database
from lilly.store.events import latest
from lilly.store.tasks import create_steps, create_task, update_step
from lilly.tools.agent import AgentAskTool, AgentPlanTool
from lilly.tools.result import ResultReadTool


def make_dummy_context(task_id: str = "t1", step_id: str = "s1", ask_fn: Any = None) -> ToolContext:
    return ToolContext(
        task_id=task_id,
        step_id=step_id,
        deadline_s=30.0,
        cancelled=lambda: False,
        label=Label.PUBLIC,
        tainted=False,
        mode=Mode.OPEN,
        pin_model=None,
        payload_hash="digest",
        on_text=None,
        ask=ask_fn,
    )


@pytest.mark.asyncio
async def test_result_read_tool(tmp_path: Path) -> None:
    db = Database(tmp_path / "lilly.db")
    tool = ResultReadTool(db)
    task_id = "task_read"

    def populate(con: Any) -> None:
        create_task(con, id=task_id, goal="test", mode=1, label=Label.PUBLIC, tainted=False, now=100.0)
        create_steps(con, task_id, [("step_1", "fs.read", "{}")])
        update_step(con, task_id, "step_1", "done", 101.0, output="0123456789ABCDEF", label=Label.PERSONAL, untrusted=True)

    await db.write(populate)
    try:
        ctx = make_dummy_context(task_id=task_id)

        # 1. Read from offset 0
        res0 = await tool.run({"step": "step_1", "offset": 0}, ctx)
        assert res0.output == "0123456789ABCDEF"
        assert res0.label == Label.PERSONAL
        assert res0.untrusted is True

        # 2. Read from offset 10
        res10 = await tool.run({"step": "step_1", "offset": 10}, ctx)
        assert res10.output == "ABCDEF"

        # 3. Nonexistent step raises ValidationFailed
        with pytest.raises(ValidationFailed, match="step 'step_nonexistent' not found"):
            await tool.run({"step": "step_nonexistent", "offset": 0}, ctx)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_agent_plan_tool(tmp_path: Path) -> None:
    db = Database(tmp_path / "lilly.db")
    clock: Clock = lambda: 1234.5
    tool = AgentPlanTool(db, clock)
    task_id = "task_plan"

    def populate(con: Any) -> None:
        create_task(con, id=task_id, goal="test", mode=1, label=Label.PUBLIC, tainted=False, now=100.0)

    await db.write(populate)
    try:
        ctx = make_dummy_context(task_id=task_id)

        # 1. Valid plan with string items and dict items
        args = {
            "todos": [
                "step one",
                {"text": "step two", "status": "doing"},
                {"text": "step three", "status": "done"},
                {"text": "step four", "status": "blocked"},
                {"text": "step five", "status": "unknown_status"},  # fallback to todo
            ]
        }
        res = await tool.run(args, ctx)
        assert "Plan updated (5 items)" in res.output

        # Verify event was recorded
        ev = latest(db.reader, task_id, "plan")
        assert ev is not None
        assert len(ev.payload["todos"]) == 5
        assert ev.payload["todos"][1] == {"text": "step two", "status": "doing"}
        assert ev.payload["todos"][4] == {"text": "step five", "status": "todo"}

        # 2. Non-list todos raises ValidationFailed
        with pytest.raises(ValidationFailed, match="todos must be a list"):
            await tool.run({"todos": "not a list"}, ctx)

        # 3. >12 items raises ValidationFailed
        with pytest.raises(ValidationFailed, match="at most 12 to-do items"):
            await tool.run({"todos": [f"item {i}" for i in range(13)]}, ctx)

        # 4. Item >120 chars raises ValidationFailed
        with pytest.raises(ValidationFailed, match="to-do item exceeds 120 characters"):
            await tool.run({"todos": ["x" * 121]}, ctx)

        # 5. Dict missing text raises ValidationFailed
        with pytest.raises(ValidationFailed, match="todo item missing text"):
            await tool.run({"todos": [{"status": "todo"}]}, ctx)

        # 6. Invalid item type raises ValidationFailed
        with pytest.raises(ValidationFailed, match="each todo item must be text or an object"):
            await tool.run({"todos": [123]}, ctx)
    finally:
        db.close()


@pytest.mark.asyncio
async def test_agent_ask_tool() -> None:
    # 1. Ask via ask_fn
    async def custom_ask_fn(t_id: str, s_id: str, q: str, choices: list[str] | None) -> str:
        assert q == "Which color?"
        assert choices == ["red", "blue"]
        return "blue"

    tool_with_fn = AgentAskTool(ask_fn=custom_ask_fn)
    ctx = make_dummy_context()
    res1 = await tool_with_fn.run({"question": "Which color?", "choices": ["red", "blue"]}, ctx)
    assert res1.output == "The user answered: blue"

    # 2. Ask via ctx.ask
    async def ctx_ask(q: str, choices: list[str] | None) -> str:
        return "yes"

    tool_without_fn = AgentAskTool()
    ctx_with_ask = make_dummy_context(ask_fn=ctx_ask)
    res2 = await tool_without_fn.run({"question": "Confirm?"}, ctx_with_ask)
    assert res2.output == "The user answered: yes"

    # 3. Ask without any handler raises ToolError
    ctx_no_ask = make_dummy_context(ask_fn=None)
    with pytest.raises(ToolError, match="asking the user is not supported"):
        await tool_without_fn.run({"question": "Hello?"}, ctx_no_ask)
