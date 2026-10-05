"""devbox.run: one shell command inside the devbox, with its output streamed as it appears."""
from __future__ import annotations

from collections.abc import Mapping

from lilly.domain.devbox import MAX_COMMAND_CHARS
from lilly.domain.labels import Label
from lilly.domain.ports import ToolContext, ToolResult
from lilly.tools.base import Tool, str_arg
from lilly.tools.devbox.manager import DevboxManager


class DevboxRunTool(Tool):
    name = "devbox.run"

    def __init__(self, manager: DevboxManager) -> None:
        self._m = manager

    def warm(self) -> None:
        self._m.warm()

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        command = str_arg(args, "command", max_len=MAX_COMMAND_CHARS)
        where = str_arg(args, "dir", max_len=200, required=False).strip()
        result = await self._m.run(where, command, ctx.on_text)
        head = ("timed out and was stopped; the devbox was reset (files in the shared folder are kept)" if result.timed_out
                else f"exit code {result.exit_code}")
        note = "\n(the start of a long output was dropped)" if result.truncated else ""
        # What the box prints can come from files in the shared folder, so it is outside text and may be private.
        return ToolResult(f"{head}{note}\n{result.output}", Label.PERSONAL, True)
