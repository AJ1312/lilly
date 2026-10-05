"""SQLite connections, pragmas and the transaction helper.

Store modules are plain functions of a connection, so they run unchanged on the writer
thread, on the read-only connection and in tests.
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

from lilly.store.migrate import latest_version, migrate, schema_version
from lilly.store.snapshot import backup_db

UPGRADE_BACKUPS = 3


def _tighten(path: Path) -> None:
    for target in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if target.exists():
            with contextlib.suppress(OSError):
                os.chmod(target, 0o600)


def open_db(path: str | Path) -> sqlite3.Connection:
    """Open (creating, 0600) the read/write connection and bring the schema up to date."""
    p = Path(path).resolve()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not p.exists():
        os.close(os.open(p, os.O_CREAT | os.O_RDWR | os.O_EXCL, 0o600))
    con = sqlite3.connect(p, isolation_level=None)
    if con.execute("PRAGMA page_count").fetchone()[0] == 0:
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")  # must precede the first table
    for pragma in (
        "journal_mode=WAL",
        "synchronous=NORMAL",
        "busy_timeout=5000",
        "foreign_keys=ON",
        "journal_size_limit=67108864",
        "cache_size=-8000",
    ):
        con.execute(f"PRAGMA {pragma}")
    current = schema_version(con)
    if 0 < current < latest_version():
        # an existing database is copied before it is upgraded; the newest three copies are kept
        backup_db(con, p.parent / "backups", time.time(), keep=UPGRADE_BACKUPS, prefix="preupgrade", tag=f"-v{current:04d}")
    migrate(con)
    _tighten(p)
    return con


def open_reader(path: str | Path) -> sqlite3.Connection:
    """A read-only connection. It can never modify the database, whatever the caller does."""
    con = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True, isolation_level=None)
    try:
        for pragma in ("busy_timeout=5000", "foreign_keys=ON", "cache_size=-8000"):
            con.execute(f"PRAGMA {pragma}")
    except sqlite3.Error:
        con.close()  # a damaged file must not leave a connection behind
        raise
    return con


@contextlib.contextmanager
def tx(con: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a multi-statement change atomically. Joins the writer's transaction when there is one."""
    if con.in_transaction:
        yield con
        return
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")
