"""result.read tool for reading paginated output of earlier steps."""
from __future__ import annotations

from collections.abc import Mapping

from lilly.domain.errors import ValidationFailed
from lilly.domain.ports import ToolContext, ToolResult
from lilly.store.db import Database
from lilly.store.tasks import get_step
from lilly.tools.base import Tool, int_arg, str_arg


class ResultReadTool(Tool):
    """Read more of an earlier result that was cut short."""

    name = "result.read"

    def __init__(self, db: Database) -> None:
        self._db = db

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        step_id = str_arg(args, "step")
        offset = int_arg(args, "offset", default=0, lo=0, hi=10_000_000)
        step = get_step(self._db.reader, ctx.task_id, step_id)
        if step is None:
            raise ValidationFailed(f"step '{step_id}' not found")
        full_text = step.output or ""
        sliced = full_text[offset:]
        return ToolResult(output=sliced, label=step.label, untrusted=step.untrusted)
