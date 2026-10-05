"""Daily model usage and call history, kept across restarts."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass


def load_usage(con: sqlite3.Connection) -> dict[str, tuple[int, int, int]]:
    """model -> (day ordinal, calls used that day, tokens used that day)."""
    return {
        m: (int(d), int(c), int(t))
        for m, d, c, t in con.execute("SELECT model, day, count, COALESCE(tokens, 0) FROM quota_usage")
    }


def save_usage(con: sqlite3.Connection, usage: Mapping[str, tuple[int, ...]]) -> None:
    rows = []
    for m, vals in usage.items():
        d, c = int(vals[0]), int(vals[1])
        t = int(vals[2]) if len(vals) > 2 else 0
        rows.append((m, d, c, t))
    con.executemany(
        "INSERT INTO quota_usage(model, day, count, tokens) VALUES(?,?,?,?) "
        "ON CONFLICT(model) DO UPDATE SET day=excluded.day, count=excluded.count, tokens=excluded.tokens",
        rows,
    )


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    id: str
    task_id: str | None
    turn: int | None
    role: str | None
    model: str
    started_at: float
    ms: int
    tokens_in: int
    tokens_out: int
    waited_ms: int
    outcome: str  # ok|rate_limited|error|cancelled


def record_model_call(con: sqlite3.Connection, call: ModelCallRecord) -> None:
    con.execute(
        "INSERT INTO model_calls(id, task_id, turn, role, model, started_at, ms, tokens_in, tokens_out, waited_ms, outcome) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            call.id,
            call.task_id,
            call.turn,
            call.role,
            call.model,
            call.started_at,
            call.ms,
            call.tokens_in,
            call.tokens_out,
            call.waited_ms,
            call.outcome,
        ),
    )


def get_task_calls(con: sqlite3.Connection, task_id: str) -> list[ModelCallRecord]:
    rows = con.execute(
        "SELECT id, task_id, turn, role, model, started_at, ms, tokens_in, tokens_out, waited_ms, outcome "
        "FROM model_calls WHERE task_id=? ORDER BY started_at ASC",
        (task_id,),
    ).fetchall()
    return [
        ModelCallRecord(
            id=r[0],
            task_id=r[1],
            turn=r[2],
            role=r[3],
            model=r[4],
            started_at=r[5],
            ms=r[6],
            tokens_in=r[7],
            tokens_out=r[8],
            waited_ms=r[9],
            outcome=r[10],
        )
        for r in rows
    ]
