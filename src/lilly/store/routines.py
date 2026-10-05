"""Routines: saved requests with a schedule, and a record of how the last run went."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import tzinfo
from typing import Any

from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.schedule import Schedule, next_run, parse_schedule, schedule_to_dict

MAX_ROUTINES = 20
MAX_FAILURES = 5
_COLS = ("id, name, goal, agent_id, schedule_json, enabled, next_run, last_run, last_task_id, last_state, "
         "last_error, failures, pause_reason, created_at")


@dataclass(frozen=True, slots=True)
class RoutineRow:
    id: str
    name: str
    goal: str
    agent_id: str | None
    schedule: Schedule
    enabled: bool
    next_run: float | None
    last_run: float | None
    last_task_id: str | None
    last_state: str | None
    last_error: str | None
    failures: int
    pause_reason: str | None
    created_at: float


def _row(r: tuple[Any, ...]) -> RoutineRow:
    return RoutineRow(str(r[0]), str(r[1]), str(r[2]), r[3], parse_schedule(json.loads(r[4])), bool(r[5]), r[6],
                      r[7], r[8], r[9], r[10], int(r[11]), r[12], float(r[13]))


def _check(name: str, goal: str) -> tuple[str, str]:
    name, goal = name.strip(), goal.strip()
    if not 1 <= len(name) <= 80 or not 1 <= len(goal) <= 4000:
        raise ValidationFailed("a routine needs a name (up to 80 characters) and a request (up to 4000)")
    return name, goal


def create_routine(con: sqlite3.Connection, id: str, name: str, goal: str, agent_id: str | None,
                   schedule: Schedule, now: float, tz: tzinfo | None = None) -> RoutineRow:
    name, goal = _check(name, goal)
    if con.execute("SELECT COUNT(*) FROM routines").fetchone()[0] >= MAX_ROUTINES:
        raise ValidationFailed(f"you can have up to {MAX_ROUTINES} routines; delete one first")
    con.execute(f"INSERT INTO routines({_COLS}) VALUES(?,?,?,?,?,1,?,NULL,NULL,NULL,NULL,0,NULL,?)",
                (id, name, goal, agent_id, json.dumps(schedule_to_dict(schedule)), next_run(schedule, now, tz), now))
    row = get_routine(con, id)
    assert row is not None
    return row


def get_routine(con: sqlite3.Connection, routine_id: str) -> RoutineRow | None:
    r = con.execute(f"SELECT {_COLS} FROM routines WHERE id=?", (routine_id,)).fetchone()
    return _row(r) if r else None


def list_routines(con: sqlite3.Connection) -> list[RoutineRow]:
    return [_row(r) for r in con.execute(f"SELECT {_COLS} FROM routines ORDER BY created_at")]


def due_routines(con: sqlite3.Connection, now: float) -> list[RoutineRow]:
    return [_row(r) for r in con.execute(
        f"SELECT {_COLS} FROM routines WHERE enabled=1 AND next_run IS NOT NULL AND next_run<=? ORDER BY next_run",
        (now,))]


def next_due(con: sqlite3.Connection) -> float | None:
    """When the earliest enabled routine is next due, or None when none is scheduled."""
    row = con.execute("SELECT MIN(next_run) FROM routines WHERE enabled=1 AND next_run IS NOT NULL").fetchone()
    return None if row is None or row[0] is None else float(row[0])


def unsettled_routines(con: sqlite3.Connection) -> list[RoutineRow]:
    """Routines whose last run has not been recorded as finished yet."""
    return [_row(r) for r in con.execute(f"SELECT {_COLS} FROM routines WHERE last_state='running'")]


def update_routine(con: sqlite3.Connection, routine_id: str, now: float, *, name: str | None = None,
                   goal: str | None = None, agent_id: str | None = None, clear_agent: bool = False,
                   schedule: Schedule | None = None, tz: tzinfo | None = None) -> RoutineRow:
    cur = get_routine(con, routine_id)
    if cur is None:
        raise NotFound(routine_id)
    new_name, new_goal = _check(cur.name if name is None else name, cur.goal if goal is None else goal)
    new_agent = None if clear_agent else (cur.agent_id if agent_id is None else agent_id)
    sched = cur.schedule if schedule is None else schedule
    nxt = next_run(sched, now, tz) if (schedule is not None and cur.enabled) else cur.next_run
    con.execute("UPDATE routines SET name=?, goal=?, agent_id=?, schedule_json=?, next_run=? WHERE id=?",
                (new_name, new_goal, new_agent, json.dumps(schedule_to_dict(sched)), nxt, routine_id))
    row = get_routine(con, routine_id)
    assert row is not None
    return row


def set_enabled(con: sqlite3.Connection, routine_id: str, enabled: bool, now: float, tz: tzinfo | None = None) -> RoutineRow:
    cur = get_routine(con, routine_id)
    if cur is None:
        raise NotFound(routine_id)
    if enabled:  # resuming clears the pause and counts from now, so a long pause never causes a burst
        con.execute("UPDATE routines SET enabled=1, failures=0, pause_reason=NULL, next_run=? WHERE id=?",
                    (next_run(cur.schedule, now, tz), routine_id))
    else:
        con.execute("UPDATE routines SET enabled=0, next_run=NULL, pause_reason=? WHERE id=?",
                    ("paused by you", routine_id))
    row = get_routine(con, routine_id)
    assert row is not None
    return row


def record_start(con: sqlite3.Connection, routine_id: str, task_id: str, now: float, nxt: float | None) -> None:
    con.execute("UPDATE routines SET last_run=?, last_task_id=?, last_state='running', last_error=NULL, next_run=? "
                "WHERE id=?", (now, task_id, nxt, routine_id))


def record_skip(con: sqlite3.Connection, routine_id: str, nxt: float | None) -> None:
    con.execute("UPDATE routines SET next_run=? WHERE id=?", (nxt, routine_id))


def record_finish(con: sqlite3.Connection, routine_id: str, state: str, error: str | None) -> None:
    """Record a finished run. Failures in a row pause the routine; any success resets the count."""
    cur = get_routine(con, routine_id)
    if cur is None:
        return
    failures = cur.failures + 1 if state == "failed" else (0 if state == "done" else cur.failures)
    pause = failures >= MAX_FAILURES
    con.execute("UPDATE routines SET last_state=?, last_error=?, failures=?, enabled=?, next_run=?, pause_reason=? "
                "WHERE id=?", (state, error, failures, 0 if pause else int(cur.enabled),
                               None if pause else cur.next_run,
                               f"paused after {MAX_FAILURES} failures in a row" if pause else cur.pause_reason,
                               routine_id))


def record_refused(con: sqlite3.Connection, routine_id: str, now: float, reason: str) -> None:
    """The run could not even start (the agent or skill is gone). That will not fix itself, so pause."""
    con.execute("UPDATE routines SET last_run=?, last_state='failed', last_error=?, enabled=0, next_run=NULL, "
                "pause_reason=? WHERE id=?", (now, reason, f"paused: {reason}", routine_id))


def delete_routine(con: sqlite3.Connection, routine_id: str) -> None:
    if con.execute("DELETE FROM routines WHERE id=?", (routine_id,)).rowcount == 0:
        raise NotFound(routine_id)


def pause_all(con: sqlite3.Connection, reason: str) -> int:
    """Used by the kill switch: nothing starts on its own until the user turns routines back on."""
    return con.execute("UPDATE routines SET enabled=0, next_run=NULL, pause_reason=? WHERE enabled=1",
                       (reason,)).rowcount
