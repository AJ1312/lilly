"""llm.work asks for the "quick" models only for small jobs; planning never does."""
from __future__ import annotations

import pytest

from lilly.domain.ports import ToolContext
from lilly.tools.llm import QUICK_PROMPT_CHARS, LlmWorkTool
from tests.helpers import ScriptedCompleter

pytestmark = pytest.mark.asyncio


async def run(material: str) -> bool:
    completer = ScriptedCompleter(replies=["ok"])
    await LlmWorkTool(completer).run({"task": "summarise", "input": material}, ToolContext("t", "s", 30.0, lambda: False))
    return completer.calls[0].quick


async def test_a_small_job_is_marked_quick_and_a_large_one_is_not() -> None:
    assert await run("a few lines") is True
    assert await run("x" * (QUICK_PROMPT_CHARS + 1)) is False


async def test_the_planner_never_asks_for_a_quick_model() -> None:
    from lilly.domain.ports import Completed, CompletionResult
    from lilly.domain.tools_registry import DEFAULT_TOOLS
    from lilly.engine.planner import PlanInputs, generate_plan
    seen = []

    async def complete(req):  # type: ignore[no-untyped-def]
        seen.append(req.quick)
        return Completed(CompletionResult('{"reasoning":"r","answer":"hi","steps":[]}', 1, 1, "stop"), "m")

    await generate_plan(complete, PlanInputs("hello", {"llm.work": DEFAULT_TOOLS["llm.work"]}, [], "", ()))
    assert seen == [False]
