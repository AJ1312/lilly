"""Spaces (folders for notes, chats and agents) and the pages inside them."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from lilly.core.retrieval import fts_query
from lilly.domain.errors import ConflictError, NotFound, ValidationFailed
from lilly.store.connection import tx

MAX_SPACE_NAME = 120
MAX_TITLE = 160
MAX_CONTENT = 200_000


@dataclass(frozen=True, slots=True)
class SpaceRow:
    id: str
    name: str
    description: str
    created_at: float


@dataclass(frozen=True, slots=True)
class PageRow:
    id: str
    space_id: str
    parent_id: str | None
    title: str
    content: str
    revision: int
    created_at: float
    updated_at: float


_PAGE = "id, space_id, parent_id, title, content, revision, created_at, updated_at"


def _page(r: tuple[Any, ...]) -> PageRow:
    return PageRow(str(r[0]), str(r[1]), r[2], str(r[3]), str(r[4]), int(r[5]), float(r[6]), float(r[7]))


def _space(r: tuple[Any, ...]) -> SpaceRow:
    return SpaceRow(str(r[0]), str(r[1]), str(r[2]), float(r[3]))


def create_space(con: sqlite3.Connection, id: str, name: str, description: str, now: float) -> SpaceRow:
    name = name.strip()
    if not 1 <= len(name) <= MAX_SPACE_NAME:
        raise ValidationFailed(f"space name must be 1 to {MAX_SPACE_NAME} characters")
    con.execute("INSERT INTO spaces(id, name, description, created_at) VALUES(?,?,?,?)",
                (id, name, description.strip()[:1000], now))
    row = get_space(con, id)
    assert row is not None
    return row


def get_space(con: sqlite3.Connection, space_id: str) -> SpaceRow | None:
    r = con.execute("SELECT id, name, description, created_at FROM spaces WHERE id=?", (space_id,)).fetchone()
    return _space(r) if r else None


def list_spaces(con: sqlite3.Connection) -> list[SpaceRow]:
    return [_space(r) for r in con.execute("SELECT id, name, description, created_at FROM spaces ORDER BY created_at")]


def update_space(con: sqlite3.Connection, space_id: str, *, name: str | None = None,
                 description: str | None = None) -> SpaceRow:
    if get_space(con, space_id) is None:
        raise NotFound(space_id)
    if name is not None:
        name = name.strip()
        if not 1 <= len(name) <= MAX_SPACE_NAME:
            raise ValidationFailed(f"space name must be 1 to {MAX_SPACE_NAME} characters")
        con.execute("UPDATE spaces SET name=? WHERE id=?", (name, space_id))
    if description is not None:
        con.execute("UPDATE spaces SET description=? WHERE id=?", (description.strip()[:1000], space_id))
    row = get_space(con, space_id)
    assert row is not None
    return row


def delete_space(con: sqlite3.Connection, space_id: str) -> None:
    if con.execute("DELETE FROM spaces WHERE id=?", (space_id,)).rowcount == 0:
        raise NotFound(space_id)


def _check_parent(con: sqlite3.Connection, space_id: str, page_id: str | None, parent_id: str | None) -> None:
    """The parent must be in the same space, and a page may not become its own ancestor."""
    seen = set()
    cur = parent_id
    while cur is not None:
        if cur == page_id or cur in seen:
            raise ValidationFailed("a page cannot be nested inside itself")
        seen.add(cur)
        row = con.execute("SELECT space_id, parent_id FROM pages WHERE id=?", (cur,)).fetchone()
        if row is None or row[0] != space_id:
            raise ValidationFailed("parent page not found in this space")
        cur = row[1]


def create_page(con: sqlite3.Connection, id: str, space_id: str, title: str, content: str, now: float,
                parent_id: str | None = None) -> PageRow:
    title = title.strip()
    if not 1 <= len(title) <= MAX_TITLE or len(content) > MAX_CONTENT:
        raise ValidationFailed("page title or content out of bounds")
    if get_space(con, space_id) is None:
        raise NotFound(space_id)
    _check_parent(con, space_id, None, parent_id)
    con.execute("INSERT INTO pages(id, space_id, parent_id, title, content, revision, created_at, updated_at) "
                "VALUES(?,?,?,?,?,1,?,?)", (id, space_id, parent_id, title, content, now, now))
    row = get_page(con, space_id, id)
    assert row is not None
    return row


def get_page(con: sqlite3.Connection, space_id: str, page_id: str) -> PageRow | None:
    r = con.execute(f"SELECT {_PAGE} FROM pages WHERE id=? AND space_id=?", (page_id, space_id)).fetchone()
    return _page(r) if r else None


def get_page_any(con: sqlite3.Connection, page_id: str) -> PageRow | None:
    r = con.execute(f"SELECT {_PAGE} FROM pages WHERE id=?", (page_id,)).fetchone()
    return _page(r) if r else None


def list_pages(con: sqlite3.Connection, space_id: str) -> list[PageRow]:
    return [_page(r) for r in con.execute(
        f"SELECT {_PAGE} FROM pages WHERE space_id=? ORDER BY updated_at DESC", (space_id,))]


def update_page(con: sqlite3.Connection, space_id: str, page_id: str, expected_revision: int, now: float, *,
                title: str | None = None, content: str | None = None) -> PageRow:
    """Optimistic concurrency: a stale `expected_revision` raises ConflictError instead of overwriting."""
    with tx(con):
        page = get_page(con, space_id, page_id)
        if page is None:
            raise NotFound(page_id)
        if page.revision != expected_revision:
            raise ConflictError("page changed since you opened it")
        new_title = page.title if title is None else title.strip()
        new_content = page.content if content is None else content
        if not 1 <= len(new_title) <= MAX_TITLE or len(new_content) > MAX_CONTENT:
            raise ValidationFailed("page title or content out of bounds")
        con.execute("UPDATE pages SET title=?, content=?, revision=revision+1, updated_at=? WHERE id=?",
                    (new_title, new_content, now, page_id))
    row = get_page(con, space_id, page_id)
    assert row is not None
    return row


def delete_page(con: sqlite3.Connection, space_id: str, page_id: str) -> None:
    if con.execute("DELETE FROM pages WHERE id=? AND space_id=?", (page_id, space_id)).rowcount == 0:
        raise NotFound(page_id)


def search_pages(con: sqlite3.Connection, query: str, *, space_id: str | None = None, limit: int = 20) -> list[PageRow]:
    q = fts_query(query)
    if q is None:
        return []
    rows = con.execute(
        "SELECT p.id, p.space_id, p.parent_id, p.title, p.content, p.revision, p.created_at, p.updated_at "
        "FROM pages_fts f JOIN pages p ON p.rowid=f.rowid "
        "WHERE pages_fts MATCH ? AND (? IS NULL OR p.space_id=?) ORDER BY bm25(pages_fts) LIMIT ?",
        (q, space_id, space_id, limit)).fetchall()
    return [_page(r) for r in rows]
