"""The JSON-RPC client against a real stdio server (tests/fake_mcp_server.py)."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from lilly.domain.errors import ToolError
from lilly.domain.mcp import MAX_TOOL_PAGES
from lilly.tools.mcp.client import McpClient
from lilly.tools.mcp.protocol import McpConnectionError, McpTimeout
from tests.unit.test_mcp_support import assert_nothing_running, cfg, no_secret, until


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    before = asyncio.all_tasks()
    yield
    await assert_nothing_running()
    assert asyncio.all_tasks() <= before | {asyncio.current_task()}  # nothing left behind


async def started(*flags: str, **kw: float) -> McpClient:
    client = McpClient(cfg(*flags), no_secret, **kw)
    await client.start()
    return client


async def text_of(client: McpClient, tool: str, **args: object) -> str:
    result = await client.call_tool(tool, args)
    assert not result.is_error
    return str(result.content[0]["text"])


async def test_handshake_list_and_call() -> None:
    client = await started()
    try:
        names = {t.name for t in await client.list_tools()}
        assert {"echo", "huge", "hang"} <= names
        assert await text_of(client, "echo", text="hello") == "hello"
    finally:
        await client.close()


async def test_unknown_protocol_version_fails_and_leaves_nothing() -> None:
    client = McpClient(cfg("bad_version"), no_secret)
    with pytest.raises(ToolError, match="protocol version"):
        await client.start()
    assert not client.alive


async def test_pagination_collects_every_page() -> None:
    client = await started("paginate")
    try:
        assert len(await client.list_tools()) == 12
    finally:
        await client.close()


async def test_endless_pagination_is_refused_after_the_page_limit() -> None:
    client = await started("endless_pages")
    try:
        with pytest.raises(ToolError, match="pages"):
            await client.list_tools()
        assert MAX_TOOL_PAGES == 8
    finally:
        await client.close()


async def test_too_many_tools_is_refused() -> None:
    client = await started("many_tools")
    try:
        with pytest.raises(ToolError, match="too many tools"):
            await client.list_tools()
    finally:
        await client.close()


async def test_malformed_duplicate_and_badly_named_tools_are_ignored() -> None:
    client = await started("bad_tools")
    try:
        tools = {t.name: t for t in await client.list_tools()}
        assert "bad name!" not in tools and "weird" not in tools and len(tools) == 12
        assert tools["echo"].description == "Echo the text back."  # the first one wins
    finally:
        await client.close()


async def test_sampling_roots_and_elicitation_are_refused_and_ping_is_answered(tmp_path: Path) -> None:
    log = tmp_path / "answers.jsonl"
    client = McpClient(cfg("server_requests", env={"FAKE_MCP_LOG": str(log)}), no_secret)
    await client.start()
    try:
        await client.list_tools()
        await text_of(client, "echo", text="sync")
        answers = {a["id"]: a for a in map(json.loads, log.read_text().splitlines())}
        for rid in ("s1", "r1", "e1"):
            assert answers[rid]["error"]["code"] == -32601 and "result" not in answers[rid]
        assert answers["p1"] == {"jsonrpc": "2.0", "id": "p1", "result": {}}
    finally:
        await client.close()


async def test_stray_responses_and_unknown_notifications_are_ignored() -> None:
    client = await started("stray", "server_requests")
    try:
        assert len(await client.list_tools()) == 12
    finally:
        await client.close()


async def test_oversized_line_kills_the_connection() -> None:
    client = await started("long_line")
    with pytest.raises(McpConnectionError, match="too large"):
        await client.list_tools()
    assert not client.alive
    await client.close()


async def test_oversized_line_in_the_middle_of_a_call_kills_it() -> None:
    client = await started()
    with pytest.raises(McpConnectionError):
        await client.call_tool("overlong", {})
    assert not client.alive
    await client.close()


async def test_invalid_json_lines_are_dropped_and_counted() -> None:
    client = await started("bad_json=5")
    try:
        assert len(await client.list_tools()) == 12
        assert client._bad_lines == 5
        assert client.alive
    finally:
        await client.close()


async def test_too_many_invalid_lines_kill_the_connection() -> None:
    client = await started("bad_json=25")
    with pytest.raises(McpConnectionError, match="invalid"):
        await client.list_tools()
    assert not client.alive
    await client.close()


async def test_server_that_crashes_on_start_is_reported() -> None:
    client = McpClient(cfg("crash_start"), no_secret)
    with pytest.raises(ToolError):
        await client.start()
    assert not client.alive


async def test_start_timeout() -> None:
    import sys

    from lilly.domain.mcp import McpServerConfig

    sleeper = McpServerConfig("sleeper", sys.executable, ("-c", "import time; time.sleep(60)"))
    client = McpClient(sleeper, no_secret, start_timeout=0.4)
    with pytest.raises(McpTimeout):
        await client.start()
    assert not client.alive


async def test_hanging_call_times_out() -> None:
    client = await started(call_timeout=0.4)
    try:
        t0 = time.monotonic()
        with pytest.raises(McpTimeout):
            await client.call_tool("hang", {})
        assert time.monotonic() - t0 < 2
    finally:
        await client.close()


async def test_crash_mid_call_is_a_connection_error() -> None:
    client = await started()
    with pytest.raises(McpConnectionError):
        await client.call_tool("crash", {})
    assert not client.alive
    with pytest.raises(McpConnectionError):
        await client.call_tool("echo", {"text": "x"})
    await client.close()


async def test_concurrent_calls_are_allowed_but_at_most_four_run_at_once() -> None:
    client = await started()
    try:
        results = await asyncio.gather(*(client.call_tool("slow", {"seconds": 0.3}) for _ in range(8)))
        peaks = [int(str(r.content[0]["text"]).split("max=")[1]) for r in results]
        assert 2 <= max(peaks) <= 4
    finally:
        await client.close()


async def test_cancelling_calls_frees_their_slots() -> None:
    client = await started()
    try:
        tasks = [asyncio.create_task(client.call_tool("slow", {"seconds": 5})) for _ in range(4)]
        await asyncio.sleep(0.3)
        queued = asyncio.create_task(text_of(client, "echo", text="later"))
        await asyncio.sleep(0.1)
        assert not queued.done()  # all four slots are busy
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with asyncio.timeout(2):
            assert await queued == "later"
        assert client._slots._value == 4 and not client._pending
    finally:
        await client.close()


async def test_list_changed_marks_the_cached_list_stale() -> None:
    client = await started("change_after=1")
    try:
        await client.list_tools()
        assert not client.stale
        await text_of(client, "echo", text="x")
        await until(lambda: client.stale)
        assert "extra" in {t.name for t in await client.list_tools()}
        assert not client.stale
    finally:
        await client.close()


async def test_noisy_stderr_does_not_block_and_is_kept_small() -> None:
    client = await started("noisy")
    try:
        for i in range(5):
            assert await text_of(client, "echo", text=str(i)) == str(i)
        assert len(client._proc.stderr_tail()) <= 4096
    finally:
        await client.close()


async def test_close_twice_is_harmless() -> None:
    client = await started()
    await client.close()
    await client.close()
