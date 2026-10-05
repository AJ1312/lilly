"""notes.write: the one way an agent writes a note. It always needs the owner's approval, never overwrites by accident,
and stores exactly the text it was given."""
from __future__ import annotations

import itertools
import json
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from lilly.domain.errors import ToolError
from lilly.domain.labels import Label, Mode, Risk, TaskCtx, Verdict
from lilly.domain.plan import tool_call
from lilly.domain.policy import PathScope, decide
from lilly.domain.ports import ToolContext
from lilly.domain.tools_registry import DEFAULT_TOOLS
from lilly.engine.outcome import clip, is_clipped
from lilly.engine.steps import APPROVAL_CHARS
from lilly.store.db import Database
from lilly.store.spaces import create_page, create_space, get_page_any, list_pages, list_spaces
from lilly.tools.notes import MAX_WRITE_CHARS, NotesReadTool, NotesSearchTool, NotesWriteTool
from tests.helpers import Clock

CTX = ToolContext("t", "s1", 5.0, lambda: False)


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    d = Database(tmp_path / "lilly.db")

    def seed(con: sqlite3.Connection) -> None:
        create_space(con, "sp1", "Work", "", 1.0)
        create_space(con, "sp2", "Home", "", 1.0)
        create_page(con, "n1", "sp1", "Plan", "first draft", 1.0)

    await d.write(seed)
    try:
        yield d
    finally:
        d.close()


@pytest.fixture
def write(db: Database) -> NotesWriteTool:
    return NotesWriteTool(db, Clock(50.0))


def page(db: Database, page_id: str):  # type: ignore[no-untyped-def]
    return get_page_any(db.reader, page_id)


# ---- policy: never allowed on its own ---------------------------------------------------------------------------
def test_notes_write_is_irreversible_and_must_be_confirmed() -> None:
    spec = DEFAULT_TOOLS["notes.write"]
    assert spec.risk is Risk.R2 and spec.confirm and spec.module == "notes" and spec.path_args == ()


@pytest.mark.parametrize("mode,tainted,label", list(itertools.product(Mode, (False, True), Label)))
def test_notes_write_is_never_allowed_on_its_own_in_any_mode(mode: Mode, tainted: bool, label: Label) -> None:
    call = tool_call("notes.write", DEFAULT_TOOLS["notes.write"], {"title": "t", "content": "c", "space": "Work"})
    verdict, _ = decide(call, TaskCtx(label=label, tainted=tainted, mode=mode), PathScope(["/tmp"]))
    assert verdict in (Verdict.NEEDS_APPROVAL, Verdict.DENY)


def test_the_most_permissive_mode_still_asks_and_says_so_plainly() -> None:
    call = tool_call("notes.write", DEFAULT_TOOLS["notes.write"], {})
    verdict, why = decide(call, TaskCtx(mode=Mode.OPEN), PathScope(["/tmp"]))
    assert verdict is Verdict.NEEDS_APPROVAL and "computer" not in why


# ---- creating ----------------------------------------------------------------------------------------------------
async def test_a_note_is_created_in_the_named_space_exactly_as_given(db: Database, write: NotesWriteTool) -> None:
    body = "  <b>bold</b> & <script>x()</script>\n\n  indented — \U0001F3B5  "
    res = await write.run({"space": "work", "title": "  Ideas ", "content": body}, CTX)
    assert res.label is Label.PUBLIC and not res.untrusted
    pages = [p for p in list_pages(db.reader, "sp1") if p.title == "Ideas"]
    assert len(pages) == 1 and pages[0].content == body and pages[0].revision == 1 and pages[0].created_at == 50.0
    assert pages[0].id in res.output and "revision 1" in res.output


async def test_the_space_can_be_given_by_id(db: Database, write: NotesWriteTool) -> None:
    await write.run({"space": "sp2", "title": "Groceries", "content": "milk"}, CTX)
    assert [p.title for p in list_pages(db.reader, "sp2")] == ["Groceries"]


@pytest.mark.parametrize("space", ["Nowhere", "sp9", "wor"])
async def test_an_unknown_space_creates_nothing(db: Database, write: NotesWriteTool, space: str) -> None:
    with pytest.raises(ToolError, match="no space"):
        await write.run({"space": space, "title": "T", "content": "c"}, CTX)
    assert not [p for s in list_spaces(db.reader) for p in list_pages(db.reader, s.id) if p.title == "T"]


async def test_two_spaces_with_one_name_must_be_told_apart_by_id(db: Database, write: NotesWriteTool) -> None:
    await db.write(lambda con: create_space(con, "sp3", "WORK", "", 2.0))
    with pytest.raises(ToolError, match="same name"):
        await write.run({"space": "work", "title": "T", "content": "c"}, CTX)
    await write.run({"space": "sp3", "title": "T", "content": "c"}, CTX)
    assert [p.title for p in list_pages(db.reader, "sp3")] == ["T"]


async def test_creating_twice_makes_two_notes_and_never_overwrites(db: Database, write: NotesWriteTool) -> None:
    for _ in range(2):
        await write.run({"space": "Work", "title": "Plan", "content": "second"}, CTX)
    plans = [p for p in list_pages(db.reader, "sp1") if p.title == "Plan"]
    assert len(plans) == 3 and sorted(p.content for p in plans) == ["first draft", "second", "second"]
    assert page(db, "n1").content == "first draft"       # type: ignore[union-attr]


# ---- editing -----------------------------------------------------------------------------------------------------
async def test_an_edit_with_the_current_revision_replaces_the_note_and_bumps_it(db: Database, write: NotesWriteTool) -> None:
    res = await write.run({"id": "n1", "base_revision": 1, "content": "second draft"}, CTX)
    row = page(db, "n1")
    assert row is not None and (row.content, row.title, row.revision, row.updated_at) == ("second draft", "Plan", 2, 50.0)
    assert "revision 2" in res.output
    await write.run({"id": "n1", "base_revision": "2", "title": "Plan B", "content": "third"}, CTX)
    assert (page(db, "n1").title, page(db, "n1").revision) == ("Plan B", 3)  # type: ignore[union-attr]


async def test_a_stale_revision_is_refused_with_advice_and_changes_nothing(db: Database, write: NotesWriteTool) -> None:
    await write.run({"id": "n1", "base_revision": 1, "content": "someone else's edit"}, CTX)
    with pytest.raises(ToolError, match="read it again"):
        await write.run({"id": "n1", "base_revision": 1, "content": "my edit"}, CTX)
    row = page(db, "n1")
    assert row is not None and (row.content, row.revision) == ("someone else's edit", 2)


@pytest.mark.parametrize("args", [{"id": "n1", "content": "x"}, {"id": "n1", "base_revision": None, "content": "x"}])
def test_an_edit_must_name_the_revision_it_was_based_on(write: NotesWriteTool, args: dict[str, object]) -> None:
    verdict, why = write.review(args, "t")
    assert verdict is Verdict.DENY and "base_revision" in why


async def test_editing_a_note_that_is_gone_is_a_plain_error(write: NotesWriteTool) -> None:
    with pytest.raises(ToolError, match="no note"):
        await write.run({"id": "ghost", "base_revision": 1, "content": "x"}, CTX)


async def test_a_revision_without_an_id_is_not_a_create(db: Database, write: NotesWriteTool) -> None:
    verdict, why = write.review({"space": "Work", "title": "T", "content": "c", "base_revision": 1}, "t")
    assert verdict is Verdict.DENY and "editing" in why


# ---- bounds, checked before anyone is asked ----------------------------------------------------------------------
@pytest.mark.parametrize("args", [
    {"title": "T", "content": "c"},                                  # no space
    {"space": "Work", "content": "c"},                               # no title
    {"space": "Work", "title": "T"},                                 # no content
    {"space": "Work", "title": "T", "content": "  "},
    {"space": "Work", "title": "T" * 161, "content": "c"},
    {"space": "Work", "title": "T", "content": "c" * (MAX_WRITE_CHARS + 1)},
    {"space": "Work", "title": 5, "content": "c"},
    {"id": "n1", "base_revision": "one", "content": "c"},
    {"id": "n1", "base_revision": True, "content": "c"},
    {"id": "n1", "base_revision": 1},
])
def test_bad_arguments_are_refused_at_review_so_nobody_approves_them(write: NotesWriteTool, args: dict[str, object]) -> None:
    assert write.review(args, "t")[0] is Verdict.DENY


def test_a_note_up_to_the_cap_is_fine_and_the_cap_fits_the_approval_card() -> None:
    ok = {"space": "Work", "title": "T" * 160, "content": "c" * MAX_WRITE_CHARS}
    assert NotesWriteTool(None, Clock()).review(ok, "t") == (Verdict.ALLOW, "ok")    # type: ignore[arg-type]
    assert not is_clipped(clip(ok, APPROVAL_CHARS))


async def test_a_failed_write_leaves_the_page_count_alone(db: Database, write: NotesWriteTool) -> None:
    before = db.reader.execute("SELECT COUNT(*), SUM(revision) FROM pages").fetchone()
    for args in ({"space": "Nowhere", "title": "T", "content": "c"}, {"id": "n1", "base_revision": 7, "content": "c"}):
        with pytest.raises(ToolError):
            await write.run(args, CTX)
    assert db.reader.execute("SELECT COUNT(*), SUM(revision) FROM pages").fetchone() == before


# ---- what the agent sees to use it -------------------------------------------------------------------------------
async def test_notes_read_shows_the_revision_and_search_shows_the_space(db: Database) -> None:
    read = await NotesReadTool(db).run({"id": "n1"}, CTX)
    assert read.output == "# Plan\nrevision: 1\n\nfirst draft"
    hits = json.loads((await NotesSearchTool(db).run({"query": "draft"}, CTX)).output)
    assert hits[0]["space"] == "Work" and hits[0]["space_id"] == "sp1" and hits[0]["id"] == "n1"


async def test_what_notes_read_shows_can_be_passed_straight_back(db: Database, write: NotesWriteTool) -> None:
    revision = int(next(line for line in (await NotesReadTool(db).run({"id": "n1"}, CTX)).output.splitlines()
                        if line.startswith("revision: ")).split(": ")[1])
    await write.run({"id": "n1", "base_revision": revision, "content": "updated"}, CTX)
    assert page(db, "n1").content == "updated"           # type: ignore[union-attr]
