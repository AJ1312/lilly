"""The single-writer thread: backpressure, atomicity, closing and restart behaviour."""
from __future__ import annotations

import concurrent.futures
import sqlite3
import stat
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from lilly.domain.errors import WriterBusy
from lilly.store import writer as writer_mod
from lilly.store.connection import open_reader, tx
from lilly.store.writer import Writer

WAIT = 10.0


class Boom(Exception):
    pass


class HardStop(BaseException):
    """Not an Exception subclass: must still be delivered to the caller and not kill the writer."""


@pytest.fixture
def writer(tmp_path: Path) -> Iterator[Writer]:
    w = Writer(tmp_path / "w.db")
    try:
        yield w
    finally:
        w.close()


def _count(path: Path, table: str = "memory") -> int:
    con = open_reader(path)
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        con.close()


def _blocker() -> tuple[threading.Event, threading.Event, object]:
    """A job that signals when it started and then waits until released."""
    started, release = threading.Event(), threading.Event()

    def job(con: sqlite3.Connection) -> str:
        started.set()
        assert release.wait(WAIT)
        return "unblocked"

    return started, release, job


def _insert(text: str):  # type: ignore[no-untyped-def]
    def job(con: sqlite3.Connection) -> int:
        cur = con.execute("INSERT INTO memory(text, label, source, created_at) VALUES(?,0,'user',1.0)", (text,))
        return int(cur.lastrowid or 0)

    return job


def test_submit_returns_the_function_result_and_commits(writer: Writer, tmp_path: Path) -> None:
    rowid = writer.submit(_insert("hello")).result(WAIT)
    assert rowid >= 1
    assert _count(tmp_path / "w.db") == 1


def test_jobs_run_in_order_on_one_dedicated_thread(writer: Writer) -> None:
    seen: list[tuple[int, str]] = []

    def job(i: int):  # type: ignore[no-untyped-def]
        def run(con: sqlite3.Connection) -> int:
            seen.append((i, threading.current_thread().name))
            return i

        return run

    futs = [writer.submit(job(i)) for i in range(20)]
    assert [f.result(WAIT) for f in futs] == list(range(20))
    assert [i for i, _ in seen] == list(range(20))
    assert {name for _, name in seen} == {"lilly-db-writer"}
    assert threading.current_thread().name != "lilly-db-writer"


def test_a_failing_job_rolls_back_everything_it_did(writer: Writer, tmp_path: Path) -> None:
    def partial(con: sqlite3.Connection) -> None:
        con.execute("INSERT INTO memory(text, label, source, created_at) VALUES('a',0,'user',1.0)")
        con.execute("INSERT INTO memory(text, label, source, created_at) VALUES('b',0,'user',1.0)")
        raise Boom("halfway")

    fut = writer.submit(partial)
    with pytest.raises(Boom, match="halfway"):
        fut.result(WAIT)
    assert _count(tmp_path / "w.db") == 0
    # The writer survives and the next job is unaffected by the failed one.
    writer.submit(_insert("after")).result(WAIT)
    assert _count(tmp_path / "w.db") == 1


def test_a_sql_error_midway_leaves_no_partial_change(writer: Writer, tmp_path: Path) -> None:
    def job(con: sqlite3.Connection) -> None:
        con.execute("INSERT INTO memory(text, label, source, created_at) VALUES('ok',0,'user',1.0)")
        con.execute("INSERT INTO memory(text, label, source, created_at) VALUES(NULL,0,'user',1.0)")  # NOT NULL

    with pytest.raises(sqlite3.IntegrityError):
        writer.submit(job).result(WAIT)
    assert _count(tmp_path / "w.db") == 0


def test_base_exceptions_are_delivered_and_do_not_kill_the_writer(writer: Writer, tmp_path: Path) -> None:
    def job(con: sqlite3.Connection) -> None:
        con.execute("INSERT INTO memory(text, label, source, created_at) VALUES('x',0,'user',1.0)")
        raise HardStop

    with pytest.raises(HardStop):
        writer.submit(job).result(WAIT)
    assert _count(tmp_path / "w.db") == 0
    assert writer.submit(_insert("y")).result(WAIT) >= 1


def test_tx_inside_a_job_joins_the_writers_transaction(writer: Writer, tmp_path: Path) -> None:
    def job(con: sqlite3.Connection) -> None:
        with tx(con):
            con.execute("INSERT INTO memory(text, label, source, created_at) VALUES('n',0,'user',1.0)")
        raise Boom  # the outer transaction is still open, so the "committed" inner block rolls back too

    with pytest.raises(Boom):
        writer.submit(job).result(WAIT)
    assert _count(tmp_path / "w.db") == 0


def test_a_job_that_commits_itself_is_not_committed_twice(writer: Writer, tmp_path: Path) -> None:
    def job(con: sqlite3.Connection) -> str:
        con.execute("INSERT INTO memory(text, label, source, created_at) VALUES('c',0,'user',1.0)")
        con.execute("COMMIT")
        return "done"

    assert writer.submit(job).result(WAIT) == "done"
    assert _count(tmp_path / "w.db") == 1


def test_uncommitted_work_is_invisible_to_readers_until_the_job_ends(writer: Writer, tmp_path: Path) -> None:
    inserted, release = threading.Event(), threading.Event()

    def job(con: sqlite3.Connection) -> None:
        con.execute("INSERT INTO memory(text, label, source, created_at) VALUES('wip',0,'user',1.0)")
        inserted.set()
        assert release.wait(WAIT)

    fut = writer.submit(job)
    assert inserted.wait(WAIT)
    try:
        assert _count(tmp_path / "w.db") == 0
    finally:
        release.set()
    fut.result(WAIT)
    assert _count(tmp_path / "w.db") == 1


def test_queue_full_raises_writer_busy_and_accepted_jobs_still_finish(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(writer_mod, "QUEUE_CAPACITY", 3)
    w = Writer(tmp_path / "bp.db")
    try:
        started, release, block = _blocker()
        first = w.submit(block)  # type: ignore[arg-type]
        assert started.wait(WAIT)  # the worker is now busy and the queue is empty
        queued = [w.submit(_insert(f"q{i}")) for i in range(3)]
        with pytest.raises(WriterBusy, match="full"):
            w.submit(_insert("overflow"))
        with pytest.raises(WriterBusy):
            w.submit(_insert("overflow again"))
        release.set()
        assert first.result(WAIT) == "unblocked"
        for f in queued:
            f.result(WAIT)
        assert _count(tmp_path / "bp.db") == 3  # the rejected job never ran
        w.submit(_insert("room again")).result(WAIT)  # capacity is available again afterwards
        assert _count(tmp_path / "bp.db") == 4
    finally:
        w.close()


def test_default_queue_capacity_is_bounded(tmp_path: Path) -> None:
    w = Writer(tmp_path / "cap.db")
    try:
        started, release, block = _blocker()
        w.submit(block)  # type: ignore[arg-type]
        assert started.wait(WAIT)
        futs = [w.submit(lambda con: None) for _ in range(writer_mod.QUEUE_CAPACITY)]
        with pytest.raises(WriterBusy):
            w.submit(lambda con: None)
        release.set()
        for f in futs:
            f.result(WAIT)
    finally:
        w.close()


def test_a_cancelled_pending_job_is_never_run(writer: Writer, tmp_path: Path) -> None:
    started, release, block = _blocker()
    first = writer.submit(block)  # type: ignore[arg-type]
    assert started.wait(WAIT)
    doomed = writer.submit(_insert("cancelled"))
    survivor = writer.submit(_insert("kept"))
    assert doomed.cancel()
    release.set()
    first.result(WAIT)
    survivor.result(WAIT)
    assert doomed.cancelled()
    con = open_reader(tmp_path / "w.db")
    try:
        assert [r[0] for r in con.execute("SELECT text FROM memory")] == ["kept"]
    finally:
        con.close()


def test_a_caller_giving_up_while_the_job_runs_does_not_break_the_writer(writer: Writer, tmp_path: Path) -> None:
    started, release, block = _blocker()

    def job(con: sqlite3.Connection) -> str:
        con.execute("INSERT INTO memory(text, label, source, created_at) VALUES('ran',0,'user',1.0)")
        return block(con)  # type: ignore[operator]

    fut = writer.submit(job)
    assert started.wait(WAIT)
    assert fut.cancel()  # the caller gave up (for example a timed-out request) while the job is mid-flight
    release.set()
    assert writer.submit(_insert("still alive")).result(WAIT) >= 1  # no InvalidStateError kills the worker
    assert fut.cancelled()
    assert _count(tmp_path / "w.db") == 2  # the job that had already started is not interrupted


def test_submit_after_close_is_rejected(tmp_path: Path) -> None:
    w = Writer(tmp_path / "c.db")
    w.close()
    with pytest.raises(WriterBusy, match="closed"):
        w.submit(lambda con: None)


def test_close_is_idempotent_and_stops_the_thread(tmp_path: Path) -> None:
    w = Writer(tmp_path / "c.db")
    thread = w._thread
    assert thread is not None and thread.is_alive()
    w.close()
    w.close()
    assert not thread.is_alive()


def test_close_waits_for_the_running_job_and_commits_it(tmp_path: Path) -> None:
    w = Writer(tmp_path / "c.db")
    started, release, block = _blocker()

    def job(con: sqlite3.Connection) -> str:
        con.execute("INSERT INTO memory(text, label, source, created_at) VALUES('last',0,'user',1.0)")
        return block(con)  # type: ignore[operator]

    fut = w.submit(job)
    assert started.wait(WAIT)
    closer = threading.Thread(target=w.close)
    closer.start()
    release.set()
    closer.join(WAIT)
    assert not closer.is_alive()
    assert fut.result(WAIT) == "unblocked"
    assert _count(tmp_path / "c.db") == 1


def test_close_runs_the_jobs_already_queued_before_stopping(tmp_path: Path) -> None:
    w = Writer(tmp_path / "c.db")
    started, release, block = _blocker()
    first = w.submit(block)  # type: ignore[arg-type]
    assert started.wait(WAIT)
    queued = [w.submit(_insert(f"queued {i}")) for i in range(3)]
    closer = threading.Thread(target=w.close)
    closer.start()
    release.set()
    closer.join(WAIT)
    assert not closer.is_alive()
    first.result(WAIT)
    assert [f.result(WAIT) for f in queued] and _count(tmp_path / "c.db") == 3


def test_close_returns_after_its_timeout_when_a_job_is_stuck(tmp_path: Path) -> None:
    w = Writer(tmp_path / "c.db")
    started, release, block = _blocker()
    fut = w.submit(block)  # type: ignore[arg-type]
    assert started.wait(WAIT)
    try:
        w.close(timeout=0.05)  # returns without hanging even though the job has not finished
        assert w._thread is not None and w._thread.is_alive()
    finally:
        release.set()
    assert fut.result(WAIT) == "unblocked"
    assert w._thread is not None
    w._thread.join(WAIT)
    assert not w._thread.is_alive()


def test_close_with_a_full_queue_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(writer_mod, "QUEUE_CAPACITY", 1)
    w = Writer(tmp_path / "c.db")
    started, release, block = _blocker()
    w.submit(block)  # type: ignore[arg-type]
    assert started.wait(WAIT)
    w.submit(lambda con: None)  # queue is now full, so the stop sentinel cannot be queued
    try:
        w.close(timeout=0.05)
    finally:
        release.set()
    assert w._thread is not None
    w._thread.join(WAIT)
    assert not w._thread.is_alive()


def test_jobs_queued_when_the_writer_closes_are_resolved_not_abandoned(tmp_path: Path) -> None:
    w = Writer(tmp_path / "c.db")
    started, release, block = _blocker()
    first = w.submit(block)  # type: ignore[arg-type]
    assert started.wait(WAIT)
    pending = w.submit(_insert("queued before close"))
    w.close(timeout=0.05)
    release.set()
    first.result(WAIT)
    assert w._thread is not None
    w._thread.join(WAIT)
    # Either it ran or it failed with WriterBusy, but it must not stay pending forever.
    assert pending.done()


def test_context_manager_closes_the_writer(tmp_path: Path) -> None:
    with Writer(tmp_path / "cm.db") as w:
        w.submit(_insert("in context")).result(WAIT)
        thread = w._thread
    assert thread is not None and not thread.is_alive()
    with pytest.raises(WriterBusy):
        w.submit(lambda con: None)
    assert _count(tmp_path / "cm.db") == 1


def test_constructor_failure_is_raised_and_leaves_no_thread(tmp_path: Path) -> None:
    blocker_file = tmp_path / "not-a-dir"
    blocker_file.write_text("x")
    before = {t for t in threading.enumerate() if t.name == "lilly-db-writer"}
    with pytest.raises(OSError):
        Writer(blocker_file / "db.sqlite")
    after = {t for t in threading.enumerate() if t.name == "lilly-db-writer"}
    for t in after - before:
        t.join(WAIT)
    assert not {t for t in threading.enumerate() if t.name == "lilly-db-writer"} - before


def test_database_file_is_created_private_and_migrated(writer: Writer, tmp_path: Path) -> None:
    mode = stat.S_IMODE((tmp_path / "w.db").stat().st_mode)
    assert mode & 0o077 == 0
    writer.submit(lambda con: None).result(WAIT)
    assert _count(tmp_path / "w.db", "spaces") == 0  # schema exists


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_dead_worker_is_restarted_and_its_stranded_jobs_fail_with_writer_busy(writer: Writer, tmp_path: Path) -> None:
    started, release, block = _blocker()
    first = writer.submit(block)  # type: ignore[arg-type]
    assert started.wait(WAIT)
    old_thread = writer._thread
    stranded: concurrent.futures.Future[object] = concurrent.futures.Future()
    # A malformed queue entry makes the worker thread die outside the per-job error handling.
    writer._queue.put(("not-a-callable-pair",))  # type: ignore[arg-type]
    writer._queue.put((lambda con: None, stranded))
    release.set()
    first.result(WAIT)
    assert old_thread is not None
    old_thread.join(WAIT)
    assert not old_thread.is_alive()

    fut = writer.submit(_insert("after restart"))
    assert fut.result(WAIT) >= 1
    assert writer._thread is not old_thread
    with pytest.raises(WriterBusy, match="stopped"):
        stranded.result(WAIT)
    assert _count(tmp_path / "w.db") == 1


def test_restart_does_not_resurrect_a_closed_writer(tmp_path: Path) -> None:
    w = Writer(tmp_path / "r.db")
    w.close()
    assert w._thread is not None
    assert not w._thread.is_alive()
    with pytest.raises(WriterBusy):
        w.submit(lambda con: None)
    assert not w._thread.is_alive()  # submit() on a closed writer must not start a new thread


def test_many_concurrent_submitters_are_serialised(writer: Writer, tmp_path: Path) -> None:
    errors: list[BaseException] = []
    futs: list[concurrent.futures.Future[int]] = []
    lock = threading.Lock()

    def submitter(n: int) -> None:
        try:
            for i in range(10):
                f = writer.submit(_insert(f"t{n}-{i}"))
                with lock:
                    futs.append(f)
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=submitter, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(WAIT)
    assert not errors
    ids = [f.result(WAIT) for f in futs]
    assert len(ids) == 80 and len(set(ids)) == 80
    assert _count(tmp_path / "w.db") == 80
