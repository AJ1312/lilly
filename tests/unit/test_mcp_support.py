"""Shared helpers for the MCP tests: a config for the fake server, approvals built from what it lists, and checks
that nothing is left running."""
from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path

import psutil

from lilly.domain.labels import Risk
from lilly.domain.mcp import McpApproval, McpServerConfig, McpToolInfo
from lilly.domain.ports import ToolContext
from lilly.tools.mcp.client import McpClient

SERVER = str(Path(__file__).resolve().parents[1] / "fake_mcp_server.py")


def cfg(*flags: str, name: str = "fake", **kw: object) -> McpServerConfig:
    return McpServerConfig(name=name, command=sys.executable, args=(SERVER, *flags), **kw)  # type: ignore[arg-type]


def no_secret(ref: str) -> str | None:
    return None


async def listed(config: McpServerConfig) -> tuple[McpToolInfo, ...]:
    client = McpClient(config, no_secret)
    await client.start()
    try:
        return await client.list_tools()
    finally:
        await client.close()


async def approve(config: McpServerConfig, *, risk: Risk = Risk.R0, only: tuple[str, ...] | None = None,
                  reviewed_with: McpServerConfig | None = None) -> McpApproval:
    """What the owner would approve after reviewing `reviewed_with` (default: the same server)."""
    tools = await listed(reviewed_with or config)
    return McpApproval(config.name, tools, {t.name: risk for t in tools if only is None or t.name in only})


def ctx(*, deadline_s: float = 30.0, cancelled: Callable[[], bool] = lambda: False) -> ToolContext:
    return ToolContext("task", "step", deadline_s, cancelled)


async def until(pred: Callable[[], bool], timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not pred():
            await asyncio.sleep(0.01)


def child_processes() -> list[psutil.Process]:
    return psutil.Process().children(recursive=True)


def is_dead(pid: int) -> bool:
    if not psutil.pid_exists(pid):
        return True
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


async def assert_nothing_running() -> None:
    await until(lambda: not child_processes(), 3.0)


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds

