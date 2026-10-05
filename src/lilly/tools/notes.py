"""notes.search and notes.read: the user's own notes. notes.write: an agent's proposal for a note, saved only
after the owner has approved the exact text."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from lilly.domain.clock import Clock
from lilly.domain.errors import ConflictError, NotFound, ToolError, ValidationFailed
from lilly.domain.ids import new_id
from lilly.domain.labels import Label, Verdict
from lilly.domain.ports import ToolContext, ToolResult
from lilly.domain.text import html_to_text
from lilly.store.db import Database
from lilly.store.spaces import MAX_TITLE, create_page, get_page_any, list_spaces, search_pages, update_page
from lilly.tools.base import Tool, str_arg

MAX_NOTE_CHARS = 30_000
MAX_WRITE_CHARS = 8_000      # what an agent may write in one go: short enough for the approval card to show all of it


class NotesSearchTool(Tool):
    name = "notes.search"

    def __init__(self, db: Database) -> None:
        self._db = db

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        pages = search_pages(self._db.reader, str_arg(args, "query", max_len=300), limit=8)
        spaces = {s.id: s.name for s in list_spaces(self._db.reader)}
        hits = [{"id": p.id, "title": p.title, "space": spaces.get(p.space_id, ""), "space_id": p.space_id,
                 "snippet": html_to_text(p.content)[:200]} for p in pages]
        return ToolResult(json.dumps(hits, indent=1), Label.PERSONAL if hits else Label.PUBLIC, False)


class NotesReadTool(Tool):
    name = "notes.read"

    def __init__(self, db: Database) -> None:
        self._db = db

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        page = get_page_any(self._db.reader, str_arg(args, "id", max_len=64))
        if page is None:
            raise ToolError("no note with that id")
        text = html_to_text(page.content)[:MAX_NOTE_CHARS]
        return ToolResult(f"# {page.title}\nrevision: {page.revision}\n\n{text}", Label.PERSONAL, False)


@dataclass(frozen=True, slots=True)
class _Write:
    """What a notes.write call asks for, checked. `page_id` is set when it edits a note."""
    content: str
    title: str | None
    space: str | None
    page_id: str | None
    base_revision: int | None


def _revision(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, (int, str)) or not str(raw).strip().isdigit():
        raise ValidationFailed("base_revision must be the revision number that notes.read showed")
    return int(raw)


def _parse(args: Mapping[str, object]) -> _Write:
    page_id = str_arg(args, "id", max_len=64, required=False) or None
    content = str_arg(args, "content", max_len=MAX_WRITE_CHARS)
    title = str_arg(args, "title", max_len=MAX_TITLE, required=page_id is None).strip() or None
    if page_id is None:
        if args.get("base_revision") is not None:
            raise ValidationFailed("base_revision only applies when editing a note: say which note with id")
        return _Write(content, title, str_arg(args, "space", max_len=200), None, None)
    if args.get("base_revision") is None:
        raise ValidationFailed("base_revision is required when editing: pass the revision that notes.read showed")
    return _Write(content, title, None, page_id, _revision(args["base_revision"]))


def _space_id(con: sqlite3.Connection, ref: str) -> str:
    spaces = list_spaces(con)
    if any(s.id == ref for s in spaces):
        return ref
    named = [s for s in spaces if s.name.casefold() == ref.strip().casefold()]
    if len(named) > 1:
        raise ToolError("several spaces have that same name: use the space_id that notes.search shows")
    if not named:
        raise ToolError("no space has that name or id: use a space that notes.search shows")
    return named[0].id


class NotesWriteTool(Tool):
    """Creates a note, or replaces an existing one whose revision the agent has seen. The registry makes it ask
    the owner every time, in every mode, so the approval card is the review before saving: the text is stored
    exactly as approved, as plain text."""

    name = "notes.write"

    def __init__(self, db: Database, clock: Clock) -> None:
        self._db, self._clock = db, clock

    def review(self, args: Mapping[str, object], task_id: str) -> tuple[Verdict, str]:
        try:
            _parse(args)
        except ValidationFailed as exc:   # refused before anyone is asked, so nobody approves something that cannot happen
            return Verdict.DENY, str(exc)
        return Verdict.ALLOW, "ok"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        req, now = _parse(args), self._clock()

        def save(con: sqlite3.Connection) -> tuple[str, int]:
            if req.page_id is None:
                assert req.space is not None and req.title is not None
                row = create_page(con, new_id(), _space_id(con, req.space), req.title, req.content, now)
            else:
                assert req.base_revision is not None
                page = get_page_any(con, req.page_id)
                if page is None:
                    raise NotFound(req.page_id)
                row = update_page(con, page.space_id, page.id, req.base_revision, now, title=req.title, content=req.content)
            return row.id, row.revision

        try:
            page_id, revision = await self._db.write(save)
        except NotFound:
            raise ToolError("no note with that id") from None
        except ConflictError:
            raise ToolError("that note changed since you read it: read it again with notes.read, "
                            "then write using its new revision") from None
        return ToolResult(f"Saved note {page_id} (revision {revision}).", Label.PUBLIC, False)
