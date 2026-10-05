"""agent.plan and agent.ask control tools."""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from lilly.domain.clock import Clock
from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Label
from lilly.domain.ports import ToolContext, ToolResult
from lilly.store.db import Database
from lilly.store.events import append_event
from lilly.tools.base import Tool, str_arg

VALID_TODO_STATUSES = frozenset({"todo", "doing", "done", "blocked"})


class AgentPlanTool(Tool):
    """Write or update your to-do list."""

    name = "agent.plan"

    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        raw_todos = args.get("todos")
        if not isinstance(raw_todos, list):
            raise ValidationFailed("todos must be a list")
        if len(raw_todos) > 12:
            raise ValidationFailed("at most 12 to-do items")

        normalized: list[dict[str, str]] = []
        for item in raw_todos:
            if isinstance(item, str):
                text = item.strip()
                status = "todo"
            elif isinstance(item, dict):
                raw_text = item.get("text")
                if not isinstance(raw_text, str):
                    raise ValidationFailed("todo item missing text")
                text = raw_text.strip()
                status = str(item.get("status", "todo")).strip().lower()
                if status not in VALID_TODO_STATUSES:
                    status = "todo"
            else:
                raise ValidationFailed("each todo item must be text or an object")

            if not text:
                continue
            if len(text) > 120:
                raise ValidationFailed("to-do item exceeds 120 characters")
            normalized.append({"text": text, "status": status})

        now = self._clock()
        await self._db.write(lambda con: append_event(con, ctx.task_id, "plan", {"todos": normalized}, "tool", now))
        return ToolResult(output=f"Plan updated ({len(normalized)} items).", label=Label.PUBLIC, untrusted=False)


class AgentAskTool(Tool):
    """Ask the user one short question and wait for the answer."""

    name = "agent.ask"

    def __init__(self, ask_fn: Callable[[str, str, str, list[str] | None], Awaitable[str]] | None = None) -> None:
        self._ask_fn = ask_fn

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        question = str_arg(args, "question")
        choices: list[str] | None = None
        raw_choices = args.get("choices")
        if isinstance(raw_choices, list):
            choices = [str(c) for c in raw_choices[:5]]

        if self._ask_fn is not None:
            answer = await self._ask_fn(ctx.task_id, ctx.step_id, question, choices)
        elif ctx.ask is not None:
            answer = await ctx.ask(question, choices)
        else:
            raise ToolError("asking the user is not supported in this context")

        return ToolResult(output=f"The user answered: {answer}", label=Label.PUBLIC, untrusted=False)


class AgentDelegateTool(Tool):
    """Hand a self-contained job to another agent in the user's crew and get back its answer."""

    name = "agent.delegate"

    def __init__(
        self,
        delegate_fn: Callable[[str, str, ToolContext], Awaitable[ToolResult]] | None = None,
    ) -> None:
        self._delegate_fn = delegate_fn

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        agent_name = str_arg(args, "agent")
        task_instruction = str_arg(args, "task")
        if self._delegate_fn is None:
            raise ToolError("delegation is not available in this context")
        return await self._delegate_fn(agent_name, task_instruction, ctx)

