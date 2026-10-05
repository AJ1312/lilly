"""Housekeeping sleeps until something needs it, and wakes at once when a routine or a task changes."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest

from lilly.app import runtime as runtime_module
from lilly.app.paths import init_paths
from lilly.app.runtime import Runtime
from tests.helpers import MemoryKeyStore

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def rt(tmp_path: Path):
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    runtime = await Runtime.create(init_paths(tmp_path), client=client, keys=MemoryKeyStore())
    yield runtime
    await runtime.close()
    await client.aclose()


async def timed(rt: Runtime) -> float:
    start = time.monotonic()
    await rt._sleep_until_needed()
    return time.monotonic() - start


async def test_with_nothing_scheduled_it_sleeps_for_the_long_interval_not_the_short_one(
        rt: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_module, "IDLE_SLEEP_S", 0.3)
    monkeypatch.setattr(runtime_module, "TICK_S", 0.01)
    assert await timed(rt) >= 0.25


async def test_a_change_to_the_routines_wakes_it_at_once(rt: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_module, "IDLE_SLEEP_S", 5.0)
    sleeper = asyncio.create_task(timed(rt))
    await asyncio.sleep(0.05)
    rt.routines_changed()
    assert await sleeper < 1.0


async def test_while_a_task_is_running_it_keeps_the_short_interval(rt: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_module, "IDLE_SLEEP_S", 5.0)
    monkeypatch.setattr(runtime_module, "TICK_S", 0.05)
    monkeypatch.setattr(type(rt.orchestrator), "active_count", property(lambda self: 1))
    assert await timed(rt) < 1.0


async def test_a_database_error_while_planning_the_sleep_does_not_end_housekeeping(
        rt: Runtime, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    def broken() -> float | None:
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(rt.scheduler, "next_due", broken)
    monkeypatch.setattr(runtime_module, "TICK_S", 0.05)
    assert await timed(rt) < 1.0                       # fell back to the short interval instead of raising
