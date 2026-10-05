"""Schema upgrades: ordering, refusal of bad input, rollback on failure and the pre-upgrade backup."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from lilly.domain.errors import ValidationFailed
from lilly.store.connection import open_db
from lilly.store.migrate import latest_version, migrate, schema_version
from lilly.store.snapshot import backup_db


def _dir(tmp_path: Path, files: dict[str, str]) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    for name, sql in files.items():
        (d / name).write_text(sql)
    return d


@pytest.fixture
def mem() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(":memory:", isolation_level=None)
    yield con
    con.close()


def test_applies_files_in_order_and_records_the_version(tmp_path: Path, mem: sqlite3.Connection) -> None:
    d = _dir(tmp_path, {"0001_a.sql": "CREATE TABLE a(x);", "0002_b.sql": "CREATE TABLE b(x);"})
    assert migrate(mem, d) == 2 == schema_version(mem) == latest_version(d)
    assert migrate(mem, d) == 2  # running again changes nothing


@pytest.mark.parametrize("files", [
    {"0002_b.sql": "SELECT 1;"},                                   # gap
    {"0001_a.sql": "SELECT 1;", "0001_b.sql": "SELECT 1;"},         # repeat
    {"0001_a.sql": "SELECT 1;", "notes.txt": "x"},                  # misnamed
])
def test_refuses_bad_migration_sets(tmp_path: Path, mem: sqlite3.Connection, files: dict[str, str]) -> None:
    with pytest.raises(ValidationFailed):
        migrate(mem, _dir(tmp_path, files))


def test_refuses_a_database_newer_than_the_code(tmp_path: Path, mem: sqlite3.Connection) -> None:
    mem.execute("PRAGMA user_version = 9")
    with pytest.raises(ValidationFailed, match="newer"):
        migrate(mem, _dir(tmp_path, {"0001_a.sql": "SELECT 1;"}))


def test_a_failing_migration_rolls_back_and_keeps_the_last_good_version(tmp_path: Path, mem: sqlite3.Connection) -> None:
    d = _dir(tmp_path, {"0001_a.sql": "CREATE TABLE a(x); INSERT INTO a VALUES (1);",
                        "0002_bad.sql": "CREATE TABLE b(x); INSERT INTO a VALUES (2); SELECT * FROM missing_table;"})
    with pytest.raises(sqlite3.Error):
        migrate(mem, d)
    assert schema_version(mem) == 1
    assert mem.execute("SELECT count(*) FROM a").fetchone()[0] == 1
    assert mem.execute("SELECT name FROM sqlite_master WHERE name = 'b'").fetchone() is None


def test_backup_is_a_consistent_private_copy_and_each_kind_prunes_only_itself(tmp_path: Path) -> None:
    db = tmp_path / "lilly.db"
    folder = tmp_path / "backups"
    with closing(sqlite3.connect(db, isolation_level=None)) as con:
        con.execute("CREATE TABLE t(x)")
        con.execute("INSERT INTO t VALUES (42)")
        daily = backup_db(con, folder, 100.0, keep=1)
        upgrades = [backup_db(con, folder, 200.0 + i, keep=3, prefix="preupgrade", tag="-v0001") for i in range(5)]
    assert sorted(folder.glob("preupgrade-*.db")) == sorted(upgrades[-3:])
    assert daily.exists()  # a pre-upgrade copy is never pruned by the daily rotation, nor the reverse
    with closing(sqlite3.connect(upgrades[-1])) as copy:
        assert copy.execute("SELECT x FROM t").fetchone() == (42,)
    assert (upgrades[-1].stat().st_mode & 0o777) == 0o600
    assert (folder.stat().st_mode & 0o777) == 0o700


def test_open_db_backs_up_an_existing_older_database_but_not_a_fresh_one(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "data" / "lilly.db"
    open_db(db).close()
    assert not (tmp_path / "data" / "backups").exists()  # a new database has nothing worth copying
    # Pretend the code has since gained one more migration: the upgrade must copy the database first.
    monkeypatch.setattr("lilly.store.connection.latest_version", lambda: latest_version() + 1)
    monkeypatch.setattr("lilly.store.connection.migrate", lambda con: 0)
    open_db(db).close()
    copies = list((tmp_path / "data" / "backups").glob(f"preupgrade-*-v{latest_version():04d}.db"))
    assert len(copies) == 1
    with closing(sqlite3.connect(copies[0])) as copy:
        assert schema_version(copy) == latest_version()
