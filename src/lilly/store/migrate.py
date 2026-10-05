"""Migration runner for SQLite schema."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from lilly.domain.errors import ValidationFailed

_MIGRATION_RE = re.compile(r"^(\d{4})_[a-zA-Z0-9_]+\.sql$")


def _get_migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def _discover(mdir: Path) -> list[tuple[int, Path]]:
    """The numbered migration files in order. Refuses gaps, repeats and misnamed files."""
    if not mdir.exists() or not mdir.is_dir():
        raise ValidationFailed(f"Migrations directory does not exist: {mdir}")
    files: list[tuple[int, Path]] = []
    seen_versions: set[int] = set()
    for item in mdir.iterdir():
        if item.name.startswith("."):
            continue
        if not item.is_file():
            raise ValidationFailed(f"Unexpected directory in migrations: {item.name}")
        match = _MIGRATION_RE.match(item.name)
        if not match:
            raise ValidationFailed(f"Misnamed migration file: {item.name}")
        v = int(match.group(1))
        if v in seen_versions:
            raise ValidationFailed(f"Duplicate migration version: {v:04d}")
        seen_versions.add(v)
        files.append((v, item))
    files.sort(key=lambda x: x[0])
    actual = [v for v, _ in files]
    if actual != list(range(1, len(files) + 1)):
        raise ValidationFailed(f"Migration gap or invalid numbering: {actual} != {list(range(1, len(files) + 1))}")
    return files


def schema_version(con: sqlite3.Connection) -> int:
    row = con.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def latest_version(migrations_dir: Path | str | None = None) -> int:
    """The newest schema version this code knows."""
    files = _discover(Path(migrations_dir) if migrations_dir is not None else _get_migrations_dir())
    return files[-1][0] if files else 0


def migrate(con: sqlite3.Connection, migrations_dir: Path | str | None = None) -> int:
    """Apply numbered .sql files in order, each in one transaction.

    The version is tracked via PRAGMA user_version. Refuses gaps, repeats,
    misnamed files, and databases newer than the code. A failing file is rolled
    back and leaves the database at the last good version.
    """
    files = _discover(Path(migrations_dir) if migrations_dir is not None else _get_migrations_dir())
    max_code_version = files[-1][0] if files else 0
    current_version = schema_version(con)
    if current_version > max_code_version:
        raise ValidationFailed(
            f"Database version ({current_version}) is newer than code ({max_code_version})"
        )
    for version, file_path in files:
        if version <= current_version:
            continue
        sql_content = file_path.read_text(encoding="utf-8")
        script = f"BEGIN IMMEDIATE;\n{sql_content}\nPRAGMA user_version = {version};\nCOMMIT;\n"
        try:
            con.executescript(script)
        except Exception:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        current_version = version
    return current_version
