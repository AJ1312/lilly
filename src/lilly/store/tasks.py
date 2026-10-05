"""Tasks and their steps."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from lilly.domain.errors import NotFound
from lilly.domain.labels import Label
from lilly.domain.tasks import TERMINAL, TaskState, check_transition
from lilly.store.connection import tx
from lilly.store.events import append_event

_TASK_COLS = ("id, conversation_id, agent_id, state, goal, mode, label, tainted, skill, "
              "plan_json, pinned_model, answer, error, created_at, updated_at, finished_at")
_STEP_COLS = "step_id, position, tool, status, args_json, output, label, untrusted, error, started_at, finished_at"
MAX_OUTPUT = 262_144
MAX_ARGS = 16_384
_TERMINAL_SQL = "('" + "','".join(s.value for s in TERMINAL) + "')"


@dataclass(frozen=True, slots=True)
class TaskRow:
    id: str
    conversation_id: str | None
    agent_id: str | None
    state: TaskState
    goal: str
    mode: int
    label: Label
    tainted: bool
    skill: str | None
    plan_json: str | None
    pinned_model: str | None
    answer: str | None
    error: str | None
    created_at: float
    updated_at: float
    finished_at: float | None


@dataclass(frozen=True, slots=True)
class StepRow:
    step_id: str
    position: int
    tool: str
    status: str
    args_json: str
    output: str | None
    label: Label
    untrusted: bool
    error: str | None
    started_at: float | None
    finished_at: float | None


def _clip_args(args_json: str) -> str:
    """Args are stored for display. Oversized ones keep a preview and stay valid JSON."""
    if len(args_json) <= MAX_ARGS:
        return args_json
    return json.dumps({"truncated": args_json[:1000]})


def _task(r: tuple[Any, ...]) -> TaskRow:
    return TaskRow(str(r[0]), r[1], r[2], TaskState(r[3]), str(r[4]), int(r[5]),
                   Label(r[6]), bool(r[7]), r[8], r[9], r[10], r[11], r[12],
                   float(r[13]), float(r[14]), r[15])


def create_task(con: sqlite3.Connection, *, id: str, goal: str, mode: int,
                label: Label, tainted: bool, now: float, conversation_id: str | None = None,
                agent_id: str | None = None, skill: str | None = None,
                pinned_model: str | None = None) -> TaskRow:
    con.execute(
        f"INSERT INTO tasks({_TASK_COLS}) VALUES(?,?,?,?,?,?,?,?,?,NULL,?,NULL,NULL,?,?,NULL)",
        (id, conversation_id, agent_id, TaskState.PENDING.value, goal, mode, int(label),
         int(tainted), skill, pinned_model, now, now))
    task = get_task(con, id)
    assert task is not None
    return task


def get_task(con: sqlite3.Connection, task_id: str) -> TaskRow | None:
    r = con.execute(f"SELECT {_TASK_COLS} FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _task(r) if r else None


def list_tasks(con: sqlite3.Connection, *, states: tuple[TaskState, ...] | None = None,
               conversation_id: str | None = None, before: float | None = None,
               limit: int = 50) -> list[TaskRow]:
    where: list[str] = []
    args: list[Any] = []
    if states:
        where.append(f"state IN ({','.join('?' * len(states))})")
        args += [s.value for s in states]
    if conversation_id:
        where.append("conversation_id=?")
        args.append(conversation_id)
    if before is not None:
        where.append("created_at<?")
        args.append(before)
    sql = f"SELECT {_TASK_COLS} FROM tasks" + (" WHERE " + " AND ".join(where) if where else "")
    rows = con.execute(sql + " ORDER BY created_at DESC LIMIT ?", (*args, max(1, min(limit, 200)))).fetchall()
    return [_task(r) for r in rows]


def set_state(con: sqlite3.Connection, task_id: str, new: TaskState, now: float, *,
              answer: str | None = None, error: str | None = None) -> TaskRow:
    """Move a task along its lifecycle. Illegal moves raise ConflictError; finished tasks never change."""
    with tx(con):
        task = get_task(con, task_id)
        if task is None:
            raise NotFound(task_id)
        check_transition(task.state, new)
        con.execute(
            "UPDATE tasks SET state=?, updated_at=?, finished_at=?, answer=COALESCE(?, answer), "
            "error=COALESCE(?, error) WHERE id=?",
            (new.value, now, now if new in TERMINAL else None, answer, error, task_id))
    updated = get_task(con, task_id)
    assert updated is not None
    return updated


def update_context(con: sqlite3.Connection, task_id: str, *, label: Label, tainted: bool, now: float) -> None:
    """Persist the task's running label and taint. Neither can ever go down."""
    con.execute("UPDATE tasks SET label=MAX(label, ?), tainted=MAX(tainted, ?), updated_at=? WHERE id=?",
                (int(label), int(tainted), now, task_id))


def set_plan(con: sqlite3.Connection, task_id: str, plan_json: str, now: float) -> None:
    con.execute("UPDATE tasks SET plan_json=?, updated_at=? WHERE id=?", (plan_json, now, task_id))


def interrupt_unfinished(con: sqlite3.Connection, now: float) -> list[str]:
    """After a restart nothing is running: fail whatever was in flight and say why. Never auto-resumes."""
    with tx(con):
        ids = [r[0] for r in con.execute(f"SELECT id FROM tasks WHERE state NOT IN {_TERMINAL_SQL}")]
        for task_id in ids:
            con.execute("UPDATE steps SET status='failed', error='interrupted', finished_at=? "
                        "WHERE task_id=? AND status IN ('pending','running','waiting')", (now, task_id))
            con.execute("UPDATE tasks SET state='FAILED', error='interrupted by a restart', updated_at=?, "
                        "finished_at=? WHERE id=?", (now, now, task_id))
            append_event(con, task_id, "state", {"state": "FAILED", "reason": "interrupted by a restart"},
                         "system", now)
    return ids


# ---- steps -------------------------------------------------------------------
def _step(r: tuple[Any, ...]) -> StepRow:
    return StepRow(str(r[0]), int(r[1]), str(r[2]), str(r[3]), str(r[4]), r[5], Label(r[6]), bool(r[7]),
                   r[8], r[9], r[10])


def create_steps(con: sqlite3.Connection, task_id: str, steps: list[tuple[str, str, str]]) -> None:
    """Record a plan's steps as pending, after any steps already recorded (a replan adds a second attempt).
    Each item is (step_id, tool, args_json)."""
    with tx(con):
        start = con.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM steps WHERE task_id=?", (task_id,)).fetchone()[0]
        con.executemany(
            "INSERT INTO steps(task_id, step_id, position, tool, status, args_json) VALUES(?,?,?,?,'pending',?)",
            [(task_id, sid, start + i, tool, _clip_args(args)) for i, (sid, tool, args) in enumerate(steps)])


def update_step(con: sqlite3.Connection, task_id: str, step_id: str, status: str, now: float, *,
                output: str | None = None, label: Label = Label.PUBLIC, untrusted: bool = False,
                error: str | None = None, args_json: str | None = None) -> None:
    started = now if status == "running" else None
    finished = now if status in ("done", "failed", "skipped") else None
    clipped = output if output is None or len(output) <= MAX_OUTPUT else output[:MAX_OUTPUT]
    con.execute(
        "UPDATE steps SET status=?, output=COALESCE(?, output), label=MAX(label, ?), "
        "untrusted=MAX(untrusted, ?), error=COALESCE(?, error), args_json=COALESCE(?, args_json), "
        "started_at=COALESCE(?, started_at), finished_at=COALESCE(?, finished_at) WHERE task_id=? AND step_id=?",
        (status, clipped, int(label), int(untrusted), error,
         _clip_args(args_json) if args_json else None, started, finished, task_id, step_id))


def list_steps(con: sqlite3.Connection, task_id: str) -> list[StepRow]:
    rows = con.execute(f"SELECT {_STEP_COLS} FROM steps WHERE task_id=? ORDER BY position", (task_id,)).fetchall()
    return [_step(r) for r in rows]
