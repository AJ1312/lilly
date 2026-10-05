"""Approval requests. A decision is atomic, single-use and bound to the payload hash."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from lilly.domain.errors import ConflictError, NotFound

_COLS = ("id, task_id, step_id, kind, summary, payload_json, payload_hash, status, created_at, expires_at, "
         "decided_at")


@dataclass(frozen=True, slots=True)
class ApprovalRow:
    id: str
    task_id: str
    step_id: str
    kind: str          # 'step' (run a tool) or 'model' (let a model see private data)
    summary: str
    payload_json: str
    payload_hash: str
    status: str        # pending | approved | denied | expired
    created_at: float
    expires_at: float
    decided_at: float | None


def _row(r: tuple[Any, ...]) -> ApprovalRow:
    return ApprovalRow(*r)


def create_approval(con: sqlite3.Connection, *, id: str, task_id: str, step_id: str, kind: str, summary: str,
                    payload_json: str, payload_hash: str, now: float, ttl_s: float) -> ApprovalRow:
    con.execute(
        f"INSERT INTO approvals({_COLS}) VALUES(?,?,?,?,?,?,?, 'pending', ?, ?, NULL)",
        (id, task_id, step_id, kind, summary[:500], payload_json, payload_hash, now, now + ttl_s))
    row = get_approval(con, id)
    assert row is not None
    return row


def get_approval(con: sqlite3.Connection, approval_id: str) -> ApprovalRow | None:
    r = con.execute(f"SELECT {_COLS} FROM approvals WHERE id=?", (approval_id,)).fetchone()
    return _row(r) if r else None


def list_approvals(con: sqlite3.Connection, *, status: str | None = None, limit: int = 100) -> list[ApprovalRow]:
    sql = f"SELECT {_COLS} FROM approvals" + (" WHERE status=?" if status else "")
    args = (status, limit) if status else (limit,)
    return [_row(r) for r in con.execute(sql + " ORDER BY created_at DESC LIMIT ?", args)]


def decide(con: sqlite3.Connection, approval_id: str, *, approve: bool, payload_hash: str, now: float) -> ApprovalRow:
    """Record the user's decision. It must name the payload hash it saw and can be made only once.

    A decision that comes too late is not recorded: the approval is marked expired and returned as such."""
    row = get_approval(con, approval_id)
    if row is None:
        raise NotFound(approval_id)
    if row.status != "pending":
        raise ConflictError(f"approval already {row.status}")
    if row.payload_hash != payload_hash:
        raise ConflictError("approval does not match what was shown")
    if now >= row.expires_at:
        con.execute("UPDATE approvals SET status='expired', decided_at=? WHERE id=? AND status='pending'",
                    (now, approval_id))
        expired = get_approval(con, approval_id)
        assert expired is not None
        return expired
    changed = con.execute(
        "UPDATE approvals SET status=?, decided_at=? WHERE id=? AND status='pending'",
        ("approved" if approve else "denied", now, approval_id)).rowcount
    if changed != 1:
        raise ConflictError("approval was decided concurrently")
    decided = get_approval(con, approval_id)
    assert decided is not None
    return decided


def expire(con: sqlite3.Connection, approval_id: str, now: float) -> None:
    con.execute("UPDATE approvals SET status='expired', decided_at=? WHERE id=? AND status='pending'",
                (now, approval_id))


def expire_all_pending(con: sqlite3.Connection, now: float) -> int:
    """After a restart no one is waiting on any request, so none may be approved later."""
    return con.execute("UPDATE approvals SET status='expired', decided_at=? WHERE status='pending'",
                       (now,)).rowcount
