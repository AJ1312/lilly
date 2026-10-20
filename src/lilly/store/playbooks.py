"""Playbooks: versioned reusable workflow templates extracted from successful tasks."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from lilly.domain.errors import NotFound, ValidationFailed
from lilly.domain.tasks import ExecutionTarget

_COLS = (
    "id, name, description, task_signature, version, steps_json, parameters_json, "
    "preconditions_json, target, provenance_task_id, success_count, status, created_at, updated_at"
)


@dataclass(frozen=True, slots=True)
class PlaybookRow:
    id: str
    name: str
    description: str
    task_signature: str
    version: int
    steps: list[dict[str, Any]]
    parameters: dict[str, Any]
    preconditions: dict[str, Any]
    target: ExecutionTarget
    provenance_task_id: str | None
    success_count: int
    status: str
    created_at: float
    updated_at: float


def _row(r: tuple[Any, ...]) -> PlaybookRow:
    steps_data = json.loads(str(r[5])) if len(r) > 5 and r[5] else []
    params_data = json.loads(str(r[6])) if len(r) > 6 and r[6] else {}
    precond_data = json.loads(str(r[7])) if len(r) > 7 and r[7] else {}
    target_val = str(r[8]) if len(r) > 8 and r[8] else "host"
    try:
        target = ExecutionTarget(target_val)
    except ValueError:
        target = ExecutionTarget.HOST

    return PlaybookRow(
        id=str(r[0]),
        name=str(r[1]),
        description=str(r[2]),
        task_signature=str(r[3]),
        version=int(r[4]),
        steps=steps_data,
        parameters=params_data,
        preconditions=precond_data,
        target=target,
        provenance_task_id=str(r[9]) if r[9] is not None else None,
        success_count=int(r[10]),
        status=str(r[11]),
        created_at=float(r[12]),
        updated_at=float(r[13]),
    )


def create_playbook(
    con: sqlite3.Connection,
    *,
    id: str,
    name: str,
    task_signature: str,
    description: str = "",
    steps: list[dict[str, Any]] | None = None,
    parameters: dict[str, Any] | None = None,
    preconditions: dict[str, Any] | None = None,
    target: ExecutionTarget = ExecutionTarget.HOST,
    provenance_task_id: str | None = None,
    status: str = "active",
    now: float,
) -> PlaybookRow:
    name = name.strip()
    if not name:
        raise ValidationFailed("playbook requires a non-empty name")
    sig = task_signature.strip()
    if not sig:
        raise ValidationFailed("playbook requires a task signature")

    steps_json = json.dumps(steps or [])
    params_json = json.dumps(parameters or {})
    precond_json = json.dumps(preconditions or {})
    con.execute(
        f"INSERT INTO playbooks({_COLS}) VALUES(?,?,?,?,1,?,?,?,?,?,1,?,?,?)",
        (
            id,
            name,
            description,
            sig,
            steps_json,
            params_json,
            precond_json,
            target.value,
            provenance_task_id,
            status,
            now,
            now,
        ),
    )
    row = get_playbook(con, id)
    assert row is not None
    return row


def get_playbook(con: sqlite3.Connection, playbook_id: str) -> PlaybookRow | None:
    r = con.execute(f"SELECT {_COLS} FROM playbooks WHERE id=?", (playbook_id,)).fetchone()
    return _row(r) if r else None


def list_playbooks(
    con: sqlite3.Connection,
    *,
    target: ExecutionTarget | None = None,
    status: str = "active",
    limit: int = 50,
) -> list[PlaybookRow]:
    where: list[str] = ["status=?"]
    args: list[Any] = [status]
    if target is not None:
        where.append("target=?")
        args.append(target.value)

    sql = f"SELECT {_COLS} FROM playbooks WHERE " + " AND ".join(where) + " ORDER BY updated_at DESC LIMIT ?"
    args.append(max(1, min(limit, 100)))
    rows = con.execute(sql, args).fetchall()
    return [_row(r) for r in rows]


def find_by_signature(con: sqlite3.Connection, signature: str) -> list[PlaybookRow]:
    rows = con.execute(
        f"SELECT {_COLS} FROM playbooks WHERE task_signature=? AND status='active' ORDER BY version DESC",
        (signature.strip(),),
    ).fetchall()
    return [_row(r) for r in rows]


def increment_success(con: sqlite3.Connection, playbook_id: str, now: float) -> PlaybookRow:
    cur = get_playbook(con, playbook_id)
    if cur is None:
        raise NotFound(playbook_id)
    con.execute(
        "UPDATE playbooks SET success_count=success_count+1, updated_at=? WHERE id=?",
        (now, playbook_id),
    )
    updated = get_playbook(con, playbook_id)
    assert updated is not None
    return updated


def delete_playbook(con: sqlite3.Connection, playbook_id: str) -> None:
    if con.execute("DELETE FROM playbooks WHERE id=?", (playbook_id,)).rowcount == 0:
        raise NotFound(playbook_id)
