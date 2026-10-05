"""Store and retrieve file undo snapshots for fs.edit, fs.write, and fs.apply_moves."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from lilly.domain.ids import new_id

_COLS = "id, task_id, step_id, path, original_content, before_hash, after_hash, created_at"


@dataclass(frozen=True, slots=True)
class UndoRecord:
    id: str
    task_id: str
    step_id: str
    path: str
    original_content: str
    before_hash: str
    after_hash: str
    created_at: float


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def record_undo(
    con: sqlite3.Connection,
    *,
    task_id: str,
    step_id: str,
    path: str,
    original_content: str,
    before_hash: str,
    after_hash: str,
    now: float,
) -> UndoRecord:
    record_id = new_id()
    con.execute(
        f"INSERT INTO file_undos({_COLS}) VALUES(?,?,?,?,?,?,?,?)",
        (record_id, task_id, step_id, path, original_content, before_hash, after_hash, now),
    )
    return UndoRecord(
        id=record_id,
        task_id=task_id,
        step_id=step_id,
        path=path,
        original_content=original_content,
        before_hash=before_hash,
        after_hash=after_hash,
        created_at=now,
    )


def get_undo(con: sqlite3.Connection, task_id: str, step_id: str) -> UndoRecord | None:
    row = con.execute(
        f"SELECT {_COLS} FROM file_undos WHERE task_id=? AND step_id=? ORDER BY created_at DESC LIMIT 1",
        (task_id, step_id),
    ).fetchone()
    if not row:
        return None
    return UndoRecord(
        id=str(row[0]),
        task_id=str(row[1]),
        step_id=str(row[2]),
        path=str(row[3]),
        original_content=str(row[4]),
        before_hash=str(row[5]),
        after_hash=str(row[6]),
        created_at=float(row[7]),
    )
