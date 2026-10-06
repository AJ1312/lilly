from pathlib import Path

from lilly.store.db import Database


def test_database_finalizer_closes_short_lived_instances(tmp_path: Path) -> None:
    db = Database(tmp_path / "lilly.db")
    db.__del__()
