"""Daily model usage, kept across restarts so a restart never resets a free-tier quota."""
from __future__ import annotations

import sqlite3


def load_usage(con: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """model -> (day ordinal, calls used that day)."""
    return {m: (int(d), int(c)) for m, d, c in con.execute("SELECT model, day, count FROM quota_usage")}


def save_usage(con: sqlite3.Connection, usage: dict[str, tuple[int, int]]) -> None:
    con.executemany(
        "INSERT INTO quota_usage(model, day, count) VALUES(?,?,?) "
        "ON CONFLICT(model) DO UPDATE SET day=excluded.day, count=excluded.count",
        [(m, d, c) for m, (d, c) in usage.items()])
