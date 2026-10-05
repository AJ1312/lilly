"""The manager: lazy start, approval checks, rug-pull defence, restarts, idle stop, configuration changes."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from lilly.domain.errors import ToolError, ValidationFailed
from lilly.domain.labels import Risk
from lilly.domain.mcp import MAX_RESTARTS, McpApproval, exposed_name, fingerprint
from lilly.tools.mcp.manager import CHANGED, McpManager
from tests.unit.test_mcp_support import FakeClock, approve, assert_nothing_running, cfg, child_processes, listed, until


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    before = asyncio.all_tasks()
    yield
    await assert_nothing_running()
    assert asyncio.all_tasks() <= before | {asyncio.current_task()}


@pytest.fixture
async def manager() -> AsyncIterator[McpManager]:
    m = McpManager(lambda ref: None, call_timeout=0.8, start_timeout=5.0)
    yield m
    await m.aclose()


async def text(m: McpManager, tool: str, **args: object) -> str:
    return str((await m.call("fake", tool, args, None)).content[0]["text"])


async def setup(m: McpManager, *flags: str, reviewed_with: tuple[str, ...] | None = None, **kw: object) -> None:
    config = cfg(*flags, **kw)
    review = cfg(*reviewed_with) if reviewed_with is not None else None
    await m.configure([config], {"fake": await approve(config, reviewed_with=review)})


async def test_tools_lists_only_approved_tools_of_enabled_servers_and_starts_nothing(manager: McpManager) -> None:
    config = cfg()
    approval = await approve(config, only=("echo", "env"))
    await manager.configure([config, cfg(name="off", enabled=False)], {"fake": approval, "off": approval})
    assert set(manager.tools()) == {"mcp.fake.echo", "mcp.fake.env"}
    assert manager.status()[0].state == "stopped" and not child_processes()


async def test_tools_ignores_approved_names_the_review_never_showed(manager: McpManager) -> None:
    config = cfg()
    tools = await listed(config)
    approval = McpApproval("fake", tools, {"echo": Risk.R0, "invented": Risk.R0})
    await manager.configure([config], {"fake": approval})
    assert set(manager.tools()) == {exposed_name("fake", "echo")}


async def test_discover_lists_tools_without_an_approval(manager: McpManager) -> None:
    await manager.configure([cfg()], {})
    found = await manager.discover("fake")
    assert "echo" in {t.name for t in found.tools} and found.fingerprint == fingerprint(found.tools)
    assert manager.status()[0].tool_count == len(found.tools)


async def test_first_call_starts_the_server_lazily_and_status_follows(manager: McpManager) -> None:
    await setup(manager)
    assert manager.status()[0].idle_s is None
    assert await text(manager, "echo", text="hi") == "hi"
    status = manager.status()[0]
    assert (status.state, status.restarts, status.error) == ("running", 0, "") and status.idle_s is not None


async def test_tools_changed_since_approval_is_detected_on_the_first_call(manager: McpManager) -> None:
    await setup(manager, "v2", reviewed_with=())
    with pytest.raises(ToolError) as info:
        await text(manager, "echo", text="x")
    assert str(info.value) == CHANGED
    assert manager.status()[0].state == "changed"
    assert not child_processes()  # the changed server is stopped, nothing was executed
    with pytest.raises(ToolError, match="changed since you approved"):
        await text(manager, "echo", text="x")


async def test_list_changed_while_running_is_detected_before_the_next_call(manager: McpManager) -> None:
    await setup(manager, "change_after=1", reviewed_with=())
    assert await text(manager, "echo", text="first") == "first"
    await asyncio.sleep(0.2)  # the notification arrives
    with pytest.raises(ToolError, match="changed since you approved"):
        await text(manager, "echo", text="second")
    assert manager.status()[0].state == "changed"


async def test_reapproving_after_a_change_works(manager: McpManager) -> None:
    config = cfg("v2")
    await manager.configure([config], {"fake": await approve(cfg())})
    with pytest.raises(ToolError):
        await text(manager, "echo", text="x")
    await manager.configure([config], {"fake": await approve(config)})
    assert manager.status()[0].state == "stopped"
    assert await text(manager, "echo", text="ok") == "ok"


async def test_a_tool_that_is_not_approved_is_refused(manager: McpManager) -> None:
    config = cfg()
    await manager.configure([config], {"fake": await approve(config, only=("echo",))})
    with pytest.raises(ToolError, match="changed since you approved"):
        await text(manager, "env", name="PATH")
    assert not child_processes()


async def test_a_server_without_approval_cannot_be_called(manager: McpManager) -> None:
    await manager.configure([cfg()], {})
    with pytest.raises(ToolError):
        await text(manager, "echo", text="x")
    with pytest.raises(ToolError, match="not available"):
        await manager.call("nobody", "echo", {}, None)


async def test_crash_mid_call_is_a_tool_error_and_the_next_call_restarts(manager: McpManager) -> None:
    await setup(manager)
    await text(manager, "echo", text="up")
    with pytest.raises(ToolError):
        await text(manager, "crash")
    assert manager.status()[0].restarts == 1
    assert await text(manager, "echo", text="again") == "again"
    assert manager.status()[0].state == "running"


async def test_after_max_restarts_the_server_is_failed_until_reconfigured(manager: McpManager) -> None:
    await setup(manager)
    for _ in range(MAX_RESTARTS + 1):
        with pytest.raises(ToolError):
            await text(manager, "crash")
    status = manager.status()[0]
    assert status.state == "failed" and status.restarts == MAX_RESTARTS + 1
    with pytest.raises(ToolError, match="failed too often"):
        await text(manager, "echo", text="x")
    assert not child_processes()
    await setup(manager)
    assert manager.status()[0].state == "stopped" and manager.status()[0].restarts == 0
    assert await text(manager, "echo", text="back") == "back"


async def test_start_failures_count_and_end_in_failed(manager: McpManager) -> None:
    config = cfg("crash_start")
    await manager.configure([config], {"fake": McpApproval("fake", (), {})})
    manager._servers["fake"].approval = await approve(cfg())
    for _ in range(MAX_RESTARTS + 1):
        with pytest.raises(ToolError):
            await text(manager, "echo", text="x")
    assert manager.status()[0].state == "failed"


async def test_a_missing_secret_fails_the_call_but_can_be_fixed_without_reconfiguring() -> None:
    secrets: dict[str, str] = {}
    m = McpManager(secrets.get, call_timeout=0.8)
    config = cfg(secret_env={"MY_TOKEN": "ref"})
    try:
        await m.configure([config], {"fake": await approve(cfg())})
        with pytest.raises(ToolError, match="MY_TOKEN"):
            await text(m, "echo", text="x")
        assert m.status()[0].state == "failed" and m.status()[0].restarts == 0
        secrets["ref"] = "value"
        assert await text(m, "echo", text="x") == "x"
    finally:
        await m.aclose()


async def test_hanging_tool_times_out_then_the_server_restarts_cleanly(manager: McpManager) -> None:
    await setup(manager)
    with pytest.raises(ToolError, match="did not answer"):
        await text(manager, "hang")
    assert not child_processes()
    assert await text(manager, "echo", text="alive") == "alive"


async def test_idle_server_is_stopped_with_an_injected_clock() -> None:
    clock, tick, delays = FakeClock(), asyncio.Event(), []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)
        await tick.wait()
        tick.clear()

    m = McpManager(lambda ref: None, monotonic=clock, sleep=sleep)
    config = cfg(idle_stop_s=30.0)
    await m.configure([config], {"fake": await approve(config)})
    try:
        await text(m, "echo", text="x")
        await until(lambda: bool(delays))
        assert delays == [30.0]  # one sleep, straight to the deadline: no polling
        assert m.status()[0].state == "running"
        clock.advance(31)
        tick.set()
        await until(lambda: m.status()[0].state == "stopped")
        await assert_nothing_running()
        assert await text(m, "echo", text="restarted") == "restarted"  # lazily started again, not a failure
        assert m.status()[0].restarts == 0
    finally:
        await m.aclose()


async def test_use_extends_the_idle_deadline() -> None:
    clock, tick, delays = FakeClock(), asyncio.Event(), []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)
        await tick.wait()
        tick.clear()

    m = McpManager(lambda ref: None, monotonic=clock, sleep=sleep)
    config = cfg(idle_stop_s=30.0)
    await m.configure([config], {"fake": await approve(config)})
    try:
        await text(m, "echo", text="x")
        await until(lambda: len(delays) == 1)
        clock.advance(20)
        await text(m, "echo", text="y")
        await until(lambda: len(delays) == 2)
        assert delays[-1] == 30.0
        clock.advance(20)  # 40s since the first call but only 20 since the last
        tick.set()
        await asyncio.sleep(0.2)
        assert m.status()[0].state == "running"
    finally:
        await m.aclose()


async def test_configure_keeps_unchanged_servers_running_and_stops_changed_removed_or_disabled(manager: McpManager) -> None:
    a, b, c = cfg(name="a"), cfg(name="b"), cfg(name="c")
    approvals = {n: await approve(cfg(name=n)) for n in "abc"}
    await manager.configure([a, b, c], approvals)
    for n in "abc":
        await manager.call(n, "echo", {"text": "x"}, None)
    assert len(child_processes()) == 3
    pids = {p.pid for p in child_processes()}
    await manager.configure([a, cfg("v2", name="b"), cfg(name="c", enabled=False)], approvals)
    survivors = {p.pid for p in child_processes()}
    assert len(survivors) == 1 and survivors <= pids
    states = {s.name: s.state for s in manager.status()}
    assert states["a"] == "running" and states["b"] == "stopped"
    await manager.configure([a], approvals)
    assert [s.name for s in manager.status()] == ["a"] and len(child_processes()) == 1


async def test_invalid_configuration_is_rejected_and_changes_nothing(manager: McpManager) -> None:
    await setup(manager)
    with pytest.raises(ValidationFailed):
        await manager.configure([cfg(), cfg(name="Bad Name")], {})
    with pytest.raises(ToolError, match="same name"):
        await manager.configure([cfg(), cfg()], {})
    assert [s.name for s in manager.status()] == ["fake"]


async def test_concurrent_calls_through_the_manager_stay_within_four(manager: McpManager) -> None:
    await setup(manager)
    results = await asyncio.gather(*(manager.call("fake", "slow", {"seconds": 0.2}, 5.0) for _ in range(8)))
    assert max(int(str(r.content[0]["text"]).split("max=")[1]) for r in results) <= 4


async def test_aclose_stops_everything_and_refuses_further_calls(tmp_path: Path) -> None:
    m = McpManager(lambda ref: None)
    await m.configure([cfg()], {"fake": await approve(cfg())})
    await text(m, "echo", text="x")
    await m.aclose()
    await m.aclose()
    assert not child_processes()
    with pytest.raises(ToolError, match="not available"):
        await text(m, "echo", text="x")


async def test_a_server_that_crashes_now_and_then_is_not_marked_failed(manager: McpManager) -> None:
    await setup(manager)
    for _ in range(MAX_RESTARTS + 3):
        for _ in range(2):
            await text(manager, "echo", text="hi")        # healthy calls between the crashes
        with pytest.raises(ToolError):
            await manager.call("fake", "crash", {}, None)
        assert manager.status()[0].state != "failed"
    assert await text(manager, "echo", text="still here") == "still here"


async def test_overlapping_configure_calls_end_in_the_state_of_the_last_one() -> None:
    m = McpManager(lambda ref: None)
    try:
        y, x = cfg(name="y"), cfg(name="x")
        approval = await approve(y)
        await m.configure([x, y], {"y": approval})
        slow_stop = m._servers["x"].lock
        await slow_stop.acquire()                                  # stands in for a server that is slow to stop
        first = asyncio.create_task(m.configure([y], {"y": approval}))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(m.configure([y], {}))         # the owner revoked y's approval meanwhile
        await asyncio.sleep(0.05)
        slow_stop.release()
        await asyncio.gather(first, second)
        assert m.tools() == {}                                      # the older change did not undo the newer one
    finally:
        await m.aclose()
