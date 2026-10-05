"""The decision log: what each decider was asked and answered, bounded in size and age."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from lilly.domain.decisions import OUTCOMES, DecisionRecord, Kind, summarise
from lilly.store.connection import tx

MAX_ROWS = 20_000
MAX_REASON = 200
MAX_ID_CHARS = 120
_COLS = "id, ts, task_id, kind, decider, choice, confidence, shadow, outcome, options, summary, reason"


@dataclass(frozen=True, slots=True)
class DecisionRow:
    id: int
    ts: float
    task_id: str | None
    kind: str
    decider: str | None
    choice: str | None
    confidence: float | None
    shadow: bool
    outcome: str
    options: int
    summary: str
    reason: str


@dataclass(frozen=True, slots=True)
class DeciderSummary:
    kind: str
    decider: str | None              # None: the rows where nobody decided
    decisions: int
    answered: int                    # rows with a choice, shadow ones included
    shadow: int
    accepted: int
    corrected: int


def _row(r: tuple[Any, ...]) -> DecisionRow:
    return DecisionRow(int(r[0]), float(r[1]), r[2], r[3], r[4], r[5], r[6], bool(r[7]), r[8], int(r[9]), r[10], r[11])


def insert(con: sqlite3.Connection, rec: DecisionRecord) -> int:
    """Store one decision, then drop the oldest rows beyond MAX_ROWS so the log can never grow without bound.
    The summary is redacted and capped again here, so no caller can store full text."""
    with tx(con):
        cur = con.execute(
            "INSERT INTO decision_log(ts, task_id, kind, decider, choice, confidence, shadow, outcome, options, "
            "summary, reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (rec.ts, rec.task_id, rec.kind.value, rec.decider, rec.choice[:MAX_ID_CHARS] if rec.choice else None,
             rec.confidence, int(rec.shadow), rec.outcome if rec.outcome in OUTCOMES else "unknown", rec.options,
             summarise(rec.summary), rec.reason[:MAX_REASON]))
        row_id = int(cur.lastrowid or 0)
        con.execute("DELETE FROM decision_log WHERE id<=?", (row_id - MAX_ROWS,))
    return row_id


def recent(con: sqlite3.Connection, limit: int = 50, kind: Kind | None = None) -> list[DecisionRow]:
    where, args = ("WHERE kind=? ", (kind.value,)) if kind else ("", ())
    rows = con.execute(f"SELECT {_COLS} FROM decision_log {where}ORDER BY id DESC LIMIT ?",
                       (*args, max(0, limit))).fetchall()
    return [_row(r) for r in rows]


def summary(con: sqlite3.Connection) -> list[DeciderSummary]:
    """Counts per question and decider. `accepted` and `corrected` come from outcomes callers recorded."""
    rows = con.execute(
        "SELECT kind, decider, COUNT(*), SUM(choice IS NOT NULL), SUM(shadow), SUM(outcome='accepted'), "
        "SUM(outcome='corrected') FROM decision_log GROUP BY kind, decider ORDER BY kind, decider").fetchall()
    return [DeciderSummary(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows]


def set_outcome(con: sqlite3.Connection, log_id: int, outcome: str) -> bool:
    """Record what happened after a decision: "accepted", "corrected" or "unknown". False when the row is gone."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
    with tx(con):
        return con.execute("UPDATE decision_log SET outcome=? WHERE id=?", (outcome, log_id)).rowcount > 0


def labelled(con: sqlite3.Connection) -> list[tuple[str, str, float, bool]]:
    """(kind, decider, confidence, was_right) for every answer whose outcome is known, for calibration."""
    rows = con.execute("SELECT kind, decider, confidence, outcome='accepted' FROM decision_log "
                       "WHERE decider IS NOT NULL AND confidence IS NOT NULL AND outcome IN ('accepted','corrected')"
                       ).fetchall()
    return [(r[0], r[1], float(r[2]), bool(r[3])) for r in rows]


def prune(con: sqlite3.Connection, days: int, now: float) -> int:
    """Delete rows older than `days` days (0 or less keeps them all), then enforce MAX_ROWS. Returns rows removed."""
    with tx(con):
        old = con.execute("DELETE FROM decision_log WHERE ts<?", (now - days * 86400.0,)).rowcount if days > 0 else 0
        over = con.execute("DELETE FROM decision_log WHERE id<=(SELECT MAX(id) FROM decision_log)-?",
                           (MAX_ROWS,)).rowcount
    return old + over
