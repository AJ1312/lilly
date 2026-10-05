"""Linked chat accounts and the update offset of each chat platform."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from lilly.store.connection import tx


@dataclass(frozen=True, slots=True)
class Identity:
    platform: str
    user_id: int
    chat_id: int
    label: str
    paired_at: float


def add_identity(con: sqlite3.Connection, platform: str, user_id: int, chat_id: int, label: str, now: float) -> None:
    with tx(con):
        con.execute("INSERT INTO bridge_identities(platform, user_id, chat_id, label, paired_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(platform, user_id) DO UPDATE SET chat_id=excluded.chat_id, label=excluded.label",
                    (platform, user_id, chat_id, label[:80], now))


def identity(con: sqlite3.Connection, platform: str, user_id: int) -> Identity | None:
    r = con.execute("SELECT platform, user_id, chat_id, label, paired_at FROM bridge_identities "
                    "WHERE platform=? AND user_id=?", (platform, user_id)).fetchone()
    return Identity(r[0], r[1], r[2], r[3], float(r[4])) if r else None


def list_identities(con: sqlite3.Connection, platform: str) -> list[Identity]:
    return [Identity(r[0], r[1], r[2], r[3], float(r[4])) for r in con.execute(
        "SELECT platform, user_id, chat_id, label, paired_at FROM bridge_identities WHERE platform=? "
        "ORDER BY paired_at", (platform,))]


def remove_identity(con: sqlite3.Connection, platform: str, user_id: int) -> bool:
    with tx(con):
        return con.execute("DELETE FROM bridge_identities WHERE platform=? AND user_id=?",
                           (platform, user_id)).rowcount > 0


def last_update(con: sqlite3.Connection, platform: str) -> int:
    r = con.execute("SELECT last_update_id FROM bridge_offsets WHERE platform=?", (platform,)).fetchone()
    return int(r[0]) if r else 0


def set_last_update(con: sqlite3.Connection, platform: str, update_id: int) -> None:
    with tx(con):
        con.execute("INSERT INTO bridge_offsets(platform, last_update_id) VALUES(?,?) "
                    "ON CONFLICT(platform) DO UPDATE SET last_update_id=MAX(last_update_id, excluded.last_update_id)",
                    (platform, update_id))


def reset_last_update(con: sqlite3.Connection, platform: str) -> None:
    """Forget the offset: a different bot numbers its updates from its own start."""
    with tx(con):
        con.execute("DELETE FROM bridge_offsets WHERE platform=?", (platform,))
