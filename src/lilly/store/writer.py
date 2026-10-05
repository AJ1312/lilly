"""Single-threaded SQLite writer with bounded queue and backpressure."""
from __future__ import annotations

import concurrent.futures
import contextlib
import queue
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from lilly.domain.errors import WriterBusy
from lilly.store.connection import open_db

T = TypeVar("T")

QUEUE_CAPACITY: int = 256


class Writer:
    """Owns the single write connection to the SQLite database.

    Runs in a dedicated thread. Callers submit functions that receive the connection
    and return a concurrent.futures.Future. Rejects with WriterBusy when the queue is full.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._queue: queue.Queue[tuple[Callable[[sqlite3.Connection], Any], concurrent.futures.Future[Any]]] = (
            queue.Queue(maxsize=QUEUE_CAPACITY)
        )
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._closed = False
        self._thread: threading.Thread | None = None
        self._ready_event = threading.Event()
        self._init_error: BaseException | None = None
        self._start_thread()

    def _start_thread(self) -> None:
        self._ready_event.clear()
        self._init_error = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="lilly-db-writer")
        self._thread.start()
        self._ready_event.wait()
        if self._init_error is not None:
            raise self._init_error

    def _run(self) -> None:
        con: sqlite3.Connection | None = None
        try:
            con = open_db(self._path)
            self._ready_event.set()
        except BaseException as exc:
            self._init_error = exc
            self._ready_event.set()
            return

        try:
            while not self._stop_event.is_set():
                try:
                    fn, fut = self._queue.get(timeout=0.1)
                except queue.Empty:
                    if self._closed:    # closing: everything queued before it has been run
                        break
                    continue

                if fut.cancelled():
                    self._queue.task_done()
                    continue

                try:
                    if not con.in_transaction:
                        con.execute("BEGIN IMMEDIATE")
                    res = fn(con)
                    if con.in_transaction:
                        con.execute("COMMIT")
                    with contextlib.suppress(concurrent.futures.InvalidStateError):  # caller gave up meanwhile
                        fut.set_result(res)
                except BaseException as exc:
                    if con.in_transaction:
                        with contextlib.suppress(sqlite3.Error):
                            con.execute("ROLLBACK")
                    with contextlib.suppress(concurrent.futures.InvalidStateError):
                        fut.set_exception(exc)
                finally:
                    self._queue.task_done()
        finally:
            self._fail_queued(WriterBusy("Database writer stopped before this job ran"))
            if con is not None:
                with contextlib.suppress(sqlite3.Error):
                    con.close()

    def _fail_queued(self, error: BaseException) -> None:
        """Resolve every job still waiting in the queue with `error`, so no caller waits forever."""
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            if not item[1].done():
                with contextlib.suppress(concurrent.futures.InvalidStateError):
                    item[1].set_exception(error)
            self._queue.task_done()

    def submit(self, fn: Callable[[sqlite3.Connection], T]) -> concurrent.futures.Future[T]:
        """Submit a write job to the writer thread.

        Raises WriterBusy if the queue is full or the writer is closed.
        """
        with self._lock:
            if self._closed:
                raise WriterBusy("Database writer is closed")

            if self._thread is None or not self._thread.is_alive():
                self._fail_queued(WriterBusy("Database writer thread terminated"))
                self._start_thread()

            fut: concurrent.futures.Future[T] = concurrent.futures.Future()
            try:
                self._queue.put_nowait((fn, fut))
            except queue.Full as err:
                raise WriterBusy("Database writer queue is full") from err

            return fut

    def close(self, timeout: float = 5.0) -> None:
        """Close the writer: jobs already queued still run, then the worker thread ends. A worker that has not
        finished within `timeout` is told to stop after its current job, and whatever is left fails with WriterBusy."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            t = self._thread

        if t is not None and t.is_alive():
            t.join(timeout=timeout)
            if t.is_alive():
                self._stop_event.set()

    def __enter__(self) -> Writer:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
