"""What a server process may and may not see or do: environment, shell, working directory, process group."""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from lilly.domain.errors import ToolError
from lilly.domain.mcp import McpServerConfig
from lilly.tools.mcp.client import McpClient
from lilly.tools.mcp.manager import McpManager
from lilly.tools.mcp.process import STDERR_KEEP, McpProcess, build_env
from tests.unit.test_mcp_support import approve, assert_nothing_running, cfg, is_dead, no_secret, until


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    await assert_nothing_running()


async def report(client: McpClient, tool: str, **args: object) -> dict[str, object]:
    result = await client.call_tool(tool, args)
    return dict(json.loads(str(result.content[0]["text"])))


async def test_parent_environment_does_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LILLY_TOKEN", "OPENAI_API_KEY", "HTTPS_PROXY", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "sk-fake-key")
    client = McpClient(cfg(), no_secret)
    await client.start()
    try:
        names = set((await report(client, "env", name="PATH"))["names"])  # type: ignore[call-overload]
        assert not names & {"LILLY_TOKEN", "OPENAI_API_KEY", "HTTPS_PROXY", "AWS_SECRET_ACCESS_KEY"}
        assert "PATH" in names
        assert (await report(client, "env", name="OPENAI_API_KEY"))["value"] is None
    finally:
        await client.close()


async def test_configured_variables_and_resolved_secrets_reach_only_the_child(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MY_TOKEN", raising=False)
    config = cfg(env={"PLAIN": "1"}, secret_env={"MY_TOKEN": "keys/mine"})
    client = McpClient(config, {"keys/mine": "s3cret"}.get)
    await client.start()
    try:
        assert (await report(client, "env", name="MY_TOKEN"))["value"] == "s3cret"
        assert (await report(client, "env", name="PLAIN"))["value"] == "1"
    finally:
        await client.close()
    assert "MY_TOKEN" not in os.environ


def test_build_env_only_copies_the_allowed_names() -> None:
    env = build_env(cfg(env={"A": "1"}), no_secret, {"PATH": "/bin", "HOME": "/h", "LILLY_X": "no", "API_KEY": "no"})
    assert env == {"PATH": "/bin", "HOME": "/h", "A": "1"}


async def test_missing_secret_refuses_to_start_and_names_only_the_variable() -> None:
    config = cfg(secret_env={"MY_TOKEN": "keys/very-private-ref"})
    client = McpClient(config, no_secret)
    with pytest.raises(ToolError) as info:
        await client.start()
    assert "MY_TOKEN" in str(info.value) and "very-private-ref" not in str(info.value)
    assert not client.alive


async def test_arguments_are_passed_literally_never_to_a_shell(tmp_path: Path) -> None:
    manager = McpManager(no_secret, base_dir=tmp_path)
    config = cfg("--", "; touch x", "$(touch y)", "`touch z`")
    approval = await approve(config)
    await manager.configure([config], {"fake": approval})
    try:
        out = json.loads((await manager.call("fake", "argv", {}, None)).content[0]["text"])
        assert out["argv"] == ["--", "; touch x", "$(touch y)", "`touch z`"]  # each one reached the child verbatim
        assert out["cwd"] == str(tmp_path / "fake")
        assert not [p for p in (tmp_path / "fake").iterdir()]
    finally:
        await manager.aclose()
    assert not list(tmp_path.rglob("x")) and not list(tmp_path.rglob("y")) and not list(tmp_path.rglob("z"))


async def test_default_working_directory_is_a_fresh_temporary_one_removed_on_stop() -> None:
    client = McpClient(cfg(), no_secret)
    await client.start()
    cwd = Path(str((await report(client, "argv"))["cwd"]))
    assert cwd.is_dir() and cwd.name.startswith("lilly-mcp-")
    await client.close()
    assert not cwd.exists()


async def test_command_that_does_not_exist_is_a_clean_error() -> None:
    proc = McpProcess(McpServerConfig("ghost", "/nonexistent/program"), no_secret)
    with pytest.raises(ToolError, match="could not start"):
        await proc.start()
    await proc.stop()


async def test_the_whole_process_group_is_killed(tmp_path: Path) -> None:
    config = cfg()
    manager = McpManager(no_secret)
    await manager.configure([config], {"fake": await approve(config)})
    pidfile = tmp_path / "grandchild.pid"
    await manager.call("fake", "spawn", {"pidfile": str(pidfile)}, None)
    grandchild = int(pidfile.read_text())
    assert not is_dead(grandchild)
    await manager.aclose()
    await until(lambda: is_dead(grandchild))


async def test_stopping_twice_is_harmless_and_leaves_no_zombie() -> None:
    proc = McpProcess(cfg(), no_secret)
    await proc.start()
    await proc.stop()
    await proc.stop()


async def test_stderr_is_drained_into_a_small_ring_buffer() -> None:
    proc = McpProcess(cfg("noisy"), no_secret)
    await proc.start()
    try:
        await until(lambda: len(proc.stderr_tail()) == STDERR_KEEP)
        await asyncio.sleep(0.1)
        assert len(proc.stderr_tail()) <= STDERR_KEEP
    finally:
        await proc.stop()


