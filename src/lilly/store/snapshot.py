"""Consistent copies of the database file, and a check that a database is sound."""
from __future__ import annotations

import contextlib
import os
import sqlite3
from pathlib import Path

MAX_BACKUPS = 7


def integrity_ok(con: sqlite3.Connection) -> bool:
    row = con.execute("PRAGMA integrity_check").fetchone()
    return bool(row and row[0] == "ok")


def newest_backup(backup_dir: Path, prefix: str = "lilly") -> Path | None:
    """The most recent backup file that shares `prefix`, or None."""
    return max(backup_dir.glob(f"{prefix}-*.db"), key=lambda p: p.stat().st_mtime, default=None)


def backup_db(source: sqlite3.Connection, backup_dir: Path, now: float, keep: int = MAX_BACKUPS, *,
              prefix: str = "lilly", tag: str = "") -> Path:
    """Online backup (safe while the daemon is writing), all 0600. Keeps the newest `keep` files that share
    `prefix`, so the daily backups and the copies taken before a schema upgrade never prune each other."""
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = backup_dir / f"{prefix}-{int(now)}{tag}.db"
    dest = sqlite3.connect(target)
    try:
        source.backup(dest)
    finally:
        dest.close()
    os.chmod(target, 0o600)
    old = sorted(backup_dir.glob(f"{prefix}-*.db"), key=lambda p: p.stat().st_mtime)
    for stale in old[: max(0, len(old) - keep)]:
        with contextlib.suppress(OSError):
            stale.unlink()
    return target
