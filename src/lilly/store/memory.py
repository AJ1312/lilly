"""Long-term memory: short facts the user (or an approved agent step) asked Lilly to keep."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from lilly.core.retrieval import fts_query
from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.labels import Label

MAX_TEXT = 8000


@dataclass(frozen=True, slots=True)
class MemoryRow:
    id: int
    text: str
    label: Label
    source: str
    created_at: float


_COLS = "id, text, label, source, created_at"


def _row(r: tuple[Any, ...]) -> MemoryRow:
    return MemoryRow(int(r[0]), str(r[1]), Label(r[2]), str(r[3]), float(r[4]))


def _clean(text: str) -> str:
    text = text.strip()
    if not text or len(text) > MAX_TEXT:
        raise ValidationFailed(f"memory must be 1 to {MAX_TEXT} characters")
    return text


def add_memory(con: sqlite3.Connection, text: str, now: float, *, label: Label = Label.PERSONAL,
               source: str = "user") -> MemoryRow:
    cur = con.execute("INSERT INTO memory(text, label, source, created_at) VALUES(?,?,?,?)",
                      (_clean(text), int(label), source, now))
    row = get_memory(con, int(cur.lastrowid or 0))
    assert row is not None
    return row


def add_memory_if_new(con: sqlite3.Connection, text: str, now: float, *, source: str = "agent") -> MemoryRow | None:
    """Add a memory unless the same text is already kept. The check and the insert run in one statement on
    the single writer, so two identical requests at once store it once. Returns None when it already existed."""
    cur = con.execute("INSERT INTO memory(text, label, source, created_at) SELECT ?,?,?,? "
                      "WHERE NOT EXISTS (SELECT 1 FROM memory WHERE text=?)",
                      (_clean(text), int(Label.PERSONAL), source, now, _clean(text)))
    return get_memory(con, int(cur.lastrowid or 0)) if cur.rowcount else None


def get_memory(con: sqlite3.Connection, memory_id: int) -> MemoryRow | None:
    r = con.execute(f"SELECT {_COLS} FROM memory WHERE id=?", (memory_id,)).fetchone()
    return _row(r) if r else None


def list_memory(con: sqlite3.Connection, limit: int = 200) -> list[MemoryRow]:
    return [_row(r) for r in con.execute(f"SELECT {_COLS} FROM memory ORDER BY id DESC LIMIT ?", (limit,))]


def update_memory(con: sqlite3.Connection, memory_id: int, *, text: str | None = None,
                  label: Label | None = None) -> MemoryRow:
    if get_memory(con, memory_id) is None:
        raise NotFound(str(memory_id))
    if text is not None:
        con.execute("UPDATE memory SET text=? WHERE id=?", (_clean(text), memory_id))
    if label is not None:
        con.execute("UPDATE memory SET label=? WHERE id=?", (int(label), memory_id))
    row = get_memory(con, memory_id)
    assert row is not None
    return row


def delete_memory(con: sqlite3.Connection, memory_id: int) -> None:
    if con.execute("DELETE FROM memory WHERE id=?", (memory_id,)).rowcount == 0:
        raise NotFound(str(memory_id))


def search_memory(con: sqlite3.Connection, query: str, *, max_label: Label = Label.PERSONAL,
                  limit: int = 10) -> list[MemoryRow]:
    """Best matches first. Anything above `max_label` is never returned (SECRET never is)."""
    q = fts_query(query)
    if q is None:
        return []
    rows = con.execute(
        "SELECT m.id, m.text, m.label, m.source, m.created_at FROM memory_fts f JOIN memory m ON m.id=f.rowid "
        "WHERE memory_fts MATCH ? AND m.label<=? ORDER BY bm25(memory_fts) LIMIT ?",
        (q, int(max_label), limit)).fetchall()
    return [_row(r) for r in rows]
