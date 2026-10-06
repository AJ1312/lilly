"""Long-term memory: short facts the user (or an approved agent step) asked Lilly to keep."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from lilly.core.retrieval import fts_query
from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.labels import Label

MAX_TEXT = 8000
MAX_TAGS = 12
MAX_TAG = 32


@dataclass(frozen=True, slots=True)
class MemoryRow:
    id: int
    text: str
    label: Label
    source: str
    created_at: float
    tags: tuple[str, ...]


_COLS = "id, text, label, source, created_at, tags"


def _row(r: tuple[Any, ...]) -> MemoryRow:
    try:
        raw = json.loads(str(r[5]))
        tags = tuple(str(tag) for tag in raw) if isinstance(raw, list) else ()
    except (TypeError, ValueError):
        tags = ()
    return MemoryRow(int(r[0]), str(r[1]), Label(r[2]), str(r[3]), float(r[4]), tags)


def clean_tags(tags: object) -> tuple[str, ...]:
    if tags is None:
        return ()
    if not isinstance(tags, (list, tuple)):
        raise ValidationFailed("tags must be a list")
    out: list[str] = []
    for raw in tags:
        if not isinstance(raw, str):
            raise ValidationFailed("tags must be text")
        tag = " ".join(raw.strip().lower().split())
        if not tag or len(tag) > MAX_TAG:
            raise ValidationFailed(f"each tag must be 1 to {MAX_TAG} characters")
        if tag not in out:
            out.append(tag)
    if len(out) > MAX_TAGS:
        raise ValidationFailed(f"memory can have at most {MAX_TAGS} tags")
    return tuple(out)


def _clean(text: str) -> str:
    text = text.strip()
    if not text or len(text) > MAX_TEXT:
        raise ValidationFailed(f"memory must be 1 to {MAX_TEXT} characters")
    return text


def add_memory(con: sqlite3.Connection, text: str, now: float, *, label: Label = Label.PERSONAL,
               source: str = "user", tags: object = ()) -> MemoryRow:
    clean = clean_tags(tags)
    cur = con.execute("INSERT INTO memory(text, label, source, created_at, tags) VALUES(?,?,?,?,?)",
                      (_clean(text), int(label), source, now, json.dumps(clean, separators=(",", ":"))))
    row = get_memory(con, int(cur.lastrowid or 0))
    assert row is not None
    return row


def add_memory_if_new(con: sqlite3.Connection, text: str, now: float, *, source: str = "agent",
                      tags: object = ()) -> MemoryRow | None:
    """Add a memory unless the same text is already kept. The check and the insert run in one statement on
    the single writer, so two identical requests at once store it once. Returns None when it already existed."""
    clean = clean_tags(tags)
    cur = con.execute("INSERT INTO memory(text, label, source, created_at, tags) SELECT ?,?,?,?,? "
                      "WHERE NOT EXISTS (SELECT 1 FROM memory WHERE text=?)",
                      (_clean(text), int(Label.PERSONAL), source, now, json.dumps(clean, separators=(",", ":")), _clean(text)))
    return get_memory(con, int(cur.lastrowid or 0)) if cur.rowcount else None


def get_memory(con: sqlite3.Connection, memory_id: int) -> MemoryRow | None:
    r = con.execute(f"SELECT {_COLS} FROM memory WHERE id=?", (memory_id,)).fetchone()
    return _row(r) if r else None


def list_memory(con: sqlite3.Connection, limit: int = 200) -> list[MemoryRow]:
    return [_row(r) for r in con.execute(f"SELECT {_COLS} FROM memory ORDER BY id DESC LIMIT ?", (limit,))]


def update_memory(con: sqlite3.Connection, memory_id: int, *, text: str | None = None,
                  label: Label | None = None, tags: object | None = None) -> MemoryRow:
    if get_memory(con, memory_id) is None:
        raise NotFound(str(memory_id))
    if text is not None:
        con.execute("UPDATE memory SET text=? WHERE id=?", (_clean(text), memory_id))
    if label is not None:
        con.execute("UPDATE memory SET label=? WHERE id=?", (int(label), memory_id))
    if tags is not None:
        clean = clean_tags(tags)
        con.execute("UPDATE memory SET tags=? WHERE id=?", (json.dumps(clean, separators=(",", ":")), memory_id))
    row = get_memory(con, memory_id)
    assert row is not None
    return row


def delete_memory(con: sqlite3.Connection, memory_id: int) -> None:
    if con.execute("DELETE FROM memory WHERE id=?", (memory_id,)).rowcount == 0:
        raise NotFound(str(memory_id))


def search_memory(con: sqlite3.Connection, query: str, *, max_label: Label = Label.PERSONAL,
                  limit: int = 10, tag: str | None = None) -> list[MemoryRow]:
    """Best matches first. Anything above `max_label` is never returned (SECRET never is)."""
    q = fts_query(query)
    if q is None:
        return []
    rows = con.execute(
        "SELECT m.id, m.text, m.label, m.source, m.created_at, m.tags FROM memory_fts f JOIN memory m ON m.id=f.rowid "
        "WHERE memory_fts MATCH ? AND m.label<=? ORDER BY bm25(memory_fts) LIMIT ?",
        (q, int(max_label), limit)).fetchall()
    wanted = clean_tags([tag])[0] if tag else None
    return [row for row in (_row(r) for r in rows) if wanted is None or wanted in row.tags][:limit]
