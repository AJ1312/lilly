"""Hash-chained, append-only event log. Each event commits to the one before it."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from lilly.domain.errors import ValidationFailed
from lilly.store.connection import tx

GENESIS = "0" * 64
MAX_PAYLOAD = 65_536


@dataclass(frozen=True, slots=True)
class EventRow:
    task_id: str
    seq: int
    kind: str
    payload: dict[str, Any]
    prov: str
    ts: float
    hash: str


def _hash(prev: str, seq: int, kind: str, prov: str, body: str) -> str:
    return hashlib.sha256(f"{prev}|{seq}|{kind}|{prov}|{body}".encode()).hexdigest()


def append_event(con: sqlite3.Connection, task_id: str, kind: str, payload: dict[str, Any],
                 prov: str, now: float) -> EventRow:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    if len(body) > MAX_PAYLOAD:
        raise ValidationFailed("event payload too large")
    with tx(con):
        row = con.execute("SELECT seq, hash FROM events WHERE task_id=? ORDER BY seq DESC LIMIT 1",
                          (task_id,)).fetchone()
        seq, prev = (row[0] + 1, row[1]) if row else (1, GENESIS)
        digest = _hash(prev, seq, kind, prov, body)
        con.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?)",
                    (task_id, seq, kind, body, prov, now, prev, digest))
    return EventRow(task_id, seq, kind, json.loads(body), prov, now, digest)


def list_events(con: sqlite3.Connection, task_id: str, after_seq: int = 0, limit: int = 500) -> list[EventRow]:
    """Keyset pagination, so a page costs the same however long the history is."""
    rows = con.execute(
        "SELECT task_id, seq, kind, payload, prov, ts, hash FROM events "
        "WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?", (task_id, after_seq, max(0, limit))).fetchall()
    return [EventRow(r[0], r[1], r[2], json.loads(r[3]), r[4], float(r[5]), r[6]) for r in rows]


def latest(con: sqlite3.Connection, task_id: str, kind: str) -> EventRow | None:
    """The newest event of one kind, or None."""
    r = con.execute("SELECT task_id, seq, kind, payload, prov, ts, hash FROM events "
                    "WHERE task_id=? AND kind=? ORDER BY seq DESC LIMIT 1", (task_id, kind)).fetchone()
    return EventRow(r[0], r[1], r[2], json.loads(r[3]), r[4], float(r[5]), r[6]) if r else None


def verify_chain(con: sqlite3.Connection, task_id: str) -> bool:
    prev = GENESIS
    for seq, kind, body, prov, p, h in con.execute(
            "SELECT seq, kind, payload, prov, prev, hash FROM events WHERE task_id=? ORDER BY seq", (task_id,)):
        if p != prev or h != _hash(prev, seq, kind, prov, body):
            return False
        prev = h
    return True
