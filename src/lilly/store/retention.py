"""Housekeeping: prune old finished tasks and vacuum."""
from __future__ import annotations

import sqlite3

from lilly.domain.tasks import TERMINAL
from lilly.store import decisions
from lilly.store.connection import tx

_TERMINAL_SQL = "('" + "','".join(s.value for s in TERMINAL) + "')"


def prune_tasks(con: sqlite3.Connection, retention_days: int, now: float) -> int:
    """Delete finished tasks (with their events, steps and approvals) older than the retention period.

    A one-line summary that still commits to the end of the event chain stays behind, so the fact that a
    task ran, and that its log was not altered, remains checkable. Returns the number of tasks removed.
    """
    if retention_days <= 0:
        return 0
    cutoff = now - retention_days * 86400.0
    with tx(con):
        rows = con.execute(f"SELECT id, goal, state, finished_at FROM tasks WHERE state IN {_TERMINAL_SQL} "
                           "AND finished_at IS NOT NULL AND finished_at<=?", (cutoff,)).fetchall()
        for task_id, goal, state, finished_at in rows:
            last = con.execute("SELECT seq, hash FROM events WHERE task_id=? ORDER BY seq DESC LIMIT 1",
                               (task_id,)).fetchone() or (0, "0" * 64)
            con.execute("INSERT OR REPLACE INTO task_summaries(task_id, goal, state, last_seq, last_hash, "
                        "finished_at) VALUES(?,?,?,?,?,?)", (task_id, goal[:200], state, last[0], last[1], finished_at))
            con.execute("DELETE FROM tasks WHERE id=?", (task_id,))  # events, steps, approvals cascade
        decisions.prune(con, retention_days, now)   # the decision log keeps to the same retention period
    return len(rows)


def vacuum(con: sqlite3.Connection) -> None:
    """Give freed pages back to the file."""
    con.execute("PRAGMA incremental_vacuum")
