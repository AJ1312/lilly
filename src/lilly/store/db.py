"""The Database facade: one writer thread for writes, a read-only connection for reads."""
from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from lilly.store.connection import open_reader
from lilly.store.writer import Writer

T = TypeVar("T")


class Database:
    """Write through the single writer thread, read on the loop thread's read-only connection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self._writer = Writer(self.path)  # creates the file and migrates before the reader opens
        self.reader = open_reader(self.path)

    async def write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Run `fn(con)` in one transaction on the writer thread. Raises WriterBusy under backpressure."""
        return await asyncio.wrap_future(self._writer.submit(fn))

    def close(self) -> None:
        self._writer.close()
        with contextlib.suppress(sqlite3.Error):
            self.reader.close()

    def __del__(self) -> None:
        # Close databases created by short-lived callers that have no lifecycle hook.
        with contextlib.suppress(Exception):
            self.close()
