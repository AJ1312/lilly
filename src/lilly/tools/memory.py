"""memory.search and memory.write over the long-term memory table."""
from __future__ import annotations

import json
from collections.abc import Mapping

from lilly.domain.clock import Clock
from lilly.domain.errors import ValidationFailed
from lilly.domain.labels import Label
from lilly.domain.ports import ToolContext, ToolResult
from lilly.store.db import Database
from lilly.store.memory import MAX_TEXT, add_memory_if_new, search_memory
from lilly.tools.base import Tool, str_arg


class MemorySearchTool(Tool):
    name = "memory.search"

    def __init__(self, db: Database) -> None:
        self._db = db

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        hits = search_memory(self._db.reader, str_arg(args, "query", max_len=300), max_label=Label.PERSONAL)
        label = max((h.label for h in hits), default=Label.PUBLIC)
        return ToolResult(json.dumps([{"id": h.id, "text": h.text} for h in hits], indent=1), label, False)


class MemoryWriteTool(Tool):
    name = "memory.write"

    def __init__(self, db: Database, clock: Clock) -> None:
        self._db, self._clock = db, clock

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        text = str_arg(args, "text", max_len=MAX_TEXT).strip()
        if not text:
            raise ValidationFailed("nothing to remember")
        raw_tags = args.get("tags", ())
        row = await self._db.write(lambda con: add_memory_if_new(con, text, self._clock(), source="agent", tags=raw_tags))
        if row is None:
            return ToolResult("Already remembered.", Label.PUBLIC, False)
        return ToolResult(f"Remembered (#{row.id}).", Label.PUBLIC, False)
