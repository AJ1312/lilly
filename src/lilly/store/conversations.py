"""Conversations and their messages."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from lilly.core.retrieval import fts_query
from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.labels import Label
from lilly.store.connection import tx

MAX_TITLE = 200
MAX_CONTENT = 32_000


@dataclass(frozen=True, slots=True)
class ConversationRow:
    id: str
    space_id: str | None
    title: str
    archived: bool
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class MessageRow:
    id: int
    conversation_id: str
    task_id: str | None
    role: str
    content: str
    label: Label
    untrusted: bool
    created_at: float


_CONV = "id, space_id, title, archived, created_at, updated_at"
_MSG = "id, conversation_id, task_id, role, content, label, untrusted, created_at"


def _conv(r: tuple[Any, ...]) -> ConversationRow:
    return ConversationRow(str(r[0]), r[1], str(r[2]), bool(r[3]), float(r[4]), float(r[5]))


def _msg(r: tuple[Any, ...]) -> MessageRow:
    return MessageRow(int(r[0]), str(r[1]), r[2], str(r[3]), str(r[4]), Label(r[5]), bool(r[6]), float(r[7]))


def _title(title: str) -> str:
    title = " ".join(title.split())[:MAX_TITLE]
    if not title:
        raise ValidationFailed("title cannot be empty")
    return title


def create_conversation(con: sqlite3.Connection, id: str, title: str, now: float,
                        space_id: str | None = None) -> ConversationRow:
    con.execute("INSERT INTO conversations(id, space_id, title, created_at, updated_at) VALUES(?,?,?,?,?)",
                (id, space_id, _title(title), now, now))
    row = get_conversation(con, id)
    assert row is not None
    return row


def get_conversation(con: sqlite3.Connection, conversation_id: str) -> ConversationRow | None:
    r = con.execute(f"SELECT {_CONV} FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    return _conv(r) if r else None


def list_conversations(con: sqlite3.Connection, *, include_archived: bool = False,
                       space_id: str | None = None, limit: int = 100) -> list[ConversationRow]:
    where, args = [], []
    if not include_archived:
        where.append("archived=0")
    if space_id:
        where.append("space_id=?")
        args.append(space_id)
    sql = f"SELECT {_CONV} FROM conversations" + (" WHERE " + " AND ".join(where) if where else "")
    return [_conv(r) for r in con.execute(sql + " ORDER BY updated_at DESC LIMIT ?", (*args, limit))]


def update_conversation(con: sqlite3.Connection, conversation_id: str, now: float, *, title: str | None = None,
                        archived: bool | None = None) -> ConversationRow:
    if get_conversation(con, conversation_id) is None:
        raise NotFound(conversation_id)
    if title is not None:
        con.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                    (_title(title), now, conversation_id))
    if archived is not None:
        con.execute("UPDATE conversations SET archived=? WHERE id=?", (int(archived), conversation_id))
    row = get_conversation(con, conversation_id)
    assert row is not None
    return row


def delete_conversation(con: sqlite3.Connection, conversation_id: str) -> None:
    if con.execute("DELETE FROM conversations WHERE id=?", (conversation_id,)).rowcount == 0:
        raise NotFound(conversation_id)


def add_message(con: sqlite3.Connection, conversation_id: str, role: str, content: str, now: float, *,
                label: Label = Label.PUBLIC, untrusted: bool = False, task_id: str | None = None) -> MessageRow:
    if role not in ("user", "assistant"):
        raise ValidationFailed("role must be user or assistant")
    with tx(con):
        if get_conversation(con, conversation_id) is None:
            raise NotFound(conversation_id)
        cur = con.execute(
            "INSERT INTO messages(conversation_id, task_id, role, content, label, untrusted, created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (conversation_id, task_id, role, content[:MAX_CONTENT], int(label), int(untrusted), now))
        con.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conversation_id))
    row = con.execute(f"SELECT {_MSG} FROM messages WHERE id=?", (cur.lastrowid,)).fetchone()
    return _msg(row)


def list_messages(con: sqlite3.Connection, conversation_id: str, *, after_id: int = 0,
                  limit: int = 200) -> list[MessageRow]:
    rows = con.execute(f"SELECT {_MSG} FROM messages WHERE conversation_id=? AND id>? ORDER BY id LIMIT ?",
                       (conversation_id, after_id, limit)).fetchall()
    return [_msg(r) for r in rows]


def recent_messages(con: sqlite3.Connection, conversation_id: str, limit: int) -> list[MessageRow]:
    """The last `limit` messages, oldest first: the history a new task starts from."""
    rows = con.execute(f"SELECT {_MSG} FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
                       (conversation_id, limit)).fetchall()
    return [_msg(r) for r in reversed(rows)]


def search_conversations(con: sqlite3.Connection, query: str, limit: int = 20) -> list[ConversationRow]:
    """Conversations whose title or messages match, best match first."""
    q = fts_query(query)
    if q is None:
        return []
    rows = con.execute(
        f"SELECT {', '.join('c.' + c.strip() for c in _CONV.split(','))} FROM conversations c WHERE c.id IN ("
        "SELECT m.conversation_id FROM messages_fts f JOIN messages m ON m.id=f.rowid "
        "WHERE messages_fts MATCH ? ORDER BY bm25(messages_fts) LIMIT 200) "
        "ORDER BY c.updated_at DESC LIMIT ?", (q, limit)).fetchall()
    return [_conv(r) for r in rows]
