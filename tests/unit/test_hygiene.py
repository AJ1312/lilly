"""Repository hygiene and distribution invariant tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lilly.store.db import Database

ROOT = Path(__file__).resolve().parents[2]


def test_required_distribution_files_exist() -> None:
    required = [
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "Makefile",
        "install.sh",
        "uninstall.sh",
        "Install Lilly.command",
    ]
    for filename in required:
        file_path = ROOT / filename
        assert file_path.exists(), f"Missing required distribution file: {filename}"
        assert file_path.stat().st_size > 0, f"Empty file: {filename}"


def test_no_forbidden_runtime_artifacts_tracked() -> None:
    """Ensure no local databases, WAL/SHM files, tokens, or private keys are tracked by git."""
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        pytest.skip("git not available")

    tracked_files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    forbidden_suffixes = (
        ".db",
        ".db-wal",
        ".db-shm",
        ".sqlite",
        ".sqlite3",
        "-wal",
        "-shm",
        "-journal",
        ".pem",
        ".key",
        ".p12",
        ".token",
    )

    for path_str in tracked_files:
        name = Path(path_str).name
        # Allow test fixture files if any, but forbid runtime db and secret patterns
        if path_str.startswith("tests/fixtures/"):
            continue
        assert not name.endswith(forbidden_suffixes), f"Tracked artifact with forbidden suffix: {path_str}"
        assert ":memory:" not in name, f"Tracked ':memory:' file: {path_str}"
        assert not name.startswith(".env"), f"Tracked environment file: {path_str}"


def test_database_rejects_memory_keyword(tmp_path: Path) -> None:
    """Database must reject ':memory:' to avoid creating a file named ':memory:' on disk."""
    with pytest.raises(ValueError, match="Database requires an explicit filesystem path"):
        Database(":memory:")

    with pytest.raises(ValueError, match="Database requires an explicit filesystem path"):
        Database(" :memory: ")
