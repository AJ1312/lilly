"""All configured MCP servers: lazy start, the approval check before every first call, restarts, idle stop."""
from __future__ import annotations

import asyncio
import contextlib
import os
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lilly.domain.errors import ToolError
from lilly.domain.mcp import (
    CALL_TIMEOUT_S,
    MAX_RESTARTS,
    START_TIMEOUT_S,
    McpApproval,
    McpServerConfig,
    McpToolInfo,
    fingerprint,
    validate_server,
)
from lilly.tools.base import Tool
from lilly.tools.mcp.adapter import McpTool
from lilly.tools.mcp.client import McpClient
from lilly.tools.mcp.protocol import CallResult, McpConnectionError, McpStartRefused

CHANGED = "this server's tools changed since you approved them; review them in Settings"
UNAVAILABLE = "this MCP server is not available"
FAILED = "this server failed too often; check it in Settings"


@dataclass(frozen=True, slots=True)
class Discovery:
    tools: tuple[McpToolInfo, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ServerStatus:
    name: str
    state: str                 # stopped | starting | running | failed | changed
    error: str
    tool_count: int
    idle_s: float | None       # seconds since the last use; None when never used
    restarts: int


@dataclass(slots=True)
class _Server:
    cfg: McpServerConfig
    approval: McpApproval | None
    client: McpClient | None = None
    state: str = "stopped"
    error: str = ""
    tool_count: int = 0
    last_used: float | None = None
    restarts: int = 0
    verified: bool = False      # the tool list was compared with the approval since this client started
    sticky: bool = False        # failed or changed: refuses everything until configure() is called again
    active: int = 0             # calls and discoveries in progress
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class McpManager:
    def __init__(self, resolve_secret: Callable[[str], str | None], *, monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, base_dir: Path | None = None,
                 call_timeout: float = CALL_TIMEOUT_S, start_timeout: float = START_TIMEOUT_S,
                 parent_env: Mapping[str, str] | None = None) -> None:
        self._resolve, self._mono, self._sleep, self._base = resolve_secret, monotonic, sleep, base_dir
        self._call_timeout, self._start_timeout = call_timeout, start_timeout
        self._parent_env = parent_env if parent_env is not None else os.environ
        self._servers: dict[str, _Server] = {}
        self._watcher: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._configure_lock = asyncio.Lock()
        self._closed = False

    async def configure(self, servers: Sequence[McpServerConfig], approvals: Mapping[str, McpApproval]) -> None:
        """Apply a new configuration: stop what was removed, disabled or changed; keep what is unchanged.
        One at a time: stopping a server takes a moment, and a second change must not interleave with the first."""
        async with self._configure_lock:
            await self._configure(servers, approvals)

    async def _configure(self, servers: Sequence[McpServerConfig], approvals: Mapping[str, McpApproval]) -> None:
        configs = {validate_server(c).name: c for c in servers}
        if len(configs) != len(servers):
            raise ToolError("two servers have the same name")
        for name in list(self._servers):
            new = configs.get(name)
            if new is None or not new.enabled or new != self._servers[name].cfg:
                await self._stop(self._servers.pop(name))
        for name, cfg in configs.items():
            approval = approvals.get(name)
            srv = self._servers.get(name)
            if srv is None:
                self._servers[name] = _Server(cfg, approval, tool_count=len(approval.tools) if approval else 0)
                continue
            if srv.sticky or (srv.approval is not None and approval is not None
                              and srv.approval.fingerprint != approval.fingerprint):
                await self._stop(srv)   # a failed or changed server, or newly approved tools: start afresh
            srv.approval = approval
            srv.verified = False
        self._wake.set()

    def tools(self) -> dict[str, Tool]:
        """Adapters for the approved tools of enabled servers. Starts nothing."""
        out: dict[str, Tool] = {}
        for srv in self._servers.values():
            if not srv.cfg.enabled or srv.approval is None:
                continue
            offered = {t.name: t for t in srv.approval.tools}
            for tool, risk in srv.approval.risks.items():
                if tool in offered:
                    adapter = McpTool(self, srv.cfg, offered[tool], risk)
                    out[adapter.name] = adapter
        return out

    def status(self) -> list[ServerStatus]:
        now = self._mono()
        return [ServerStatus(s.cfg.name, s.state, s.error, s.tool_count,
                             None if s.last_used is None else max(0.0, now - s.last_used), s.restarts)
                for s in self._servers.values()]

    async def aclose(self) -> None:
        """Stop every server and the idle watcher. No process or task is left behind."""
        self._closed = True
        watcher, self._watcher = self._watcher, None
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        for srv in self._servers.values():
            await self._stop(srv)

    async def discover(self, name: str) -> Discovery:
        """Start the server if needed and list its tools, for the owner to review. Needs no approval."""
        srv = self._get(name)
        if srv.sticky and srv.state == "failed":
            raise ToolError(FAILED)
        srv.active += 1
        try:
            async with srv.lock:
                client = await self._running(srv)
                try:
                    tools = await client.list_tools()
                except ToolError as exc:
                    await self._drop(srv, client, str(exc))
                    raise
            if srv.approval is None:
                srv.tool_count = len(tools)
            return Discovery(tools, fingerprint(tools))
        finally:
            self._done(srv)

    async def call(self, server: str, tool: str, arguments: Mapping[str, Any], timeout: float | None) -> CallResult:
        """Run one approved tool. Before the first call after every start (and after list_changed) the server's
        tool list is compared with the approved one; a difference refuses the call."""
        srv = self._get(server)
        approval = srv.approval
        if approval is None or tool not in approval.risks or all(t.name != tool for t in approval.tools):
            raise ToolError(CHANGED)
        srv.active += 1
        try:
            async with srv.lock:
                client = await self._verified(srv, approval)
            try:
                result = await client.call_tool(tool, arguments, timeout)
                srv.restarts = 0     # a server that works is not on its way to being marked failed
                return result
            except McpConnectionError as exc:
                await self._drop(srv, client, str(exc))
                raise
        finally:
            self._done(srv)

    def _get(self, name: str) -> _Server:
        srv = self._servers.get(name)
        if self._closed or srv is None or not srv.cfg.enabled:
            raise ToolError(UNAVAILABLE)
        return srv

    def _done(self, srv: _Server) -> None:
        srv.active -= 1
        srv.last_used = self._mono()
        self._wake.set()

    async def _running(self, srv: _Server) -> McpClient:
        """The live client, starting one if needed. Caller holds srv.lock."""
        client = srv.client
        if client is not None and not client.alive:
            await self._drop(srv, client, client.death_reason)
            client = None
        if srv.sticky and srv.state == "failed":
            raise ToolError(FAILED)
        return client if client is not None else await self._start(srv)

    async def _verified(self, srv: _Server, approval: McpApproval) -> McpClient:
        """A live client whose tool list matches the approval. Caller holds srv.lock."""
        if srv.sticky and srv.state == "changed":
            raise ToolError(CHANGED)
        client = await self._running(srv)
        if srv.verified and not client.stale:
            return client
        try:
            tools = await client.list_tools()
        except ToolError as exc:
            await self._drop(srv, client, str(exc))
            raise
        srv.tool_count = len(tools)
        if fingerprint(tools) != approval.fingerprint:
            srv.client, srv.state, srv.sticky, srv.error = None, "changed", True, "tools changed since approval"
            await client.close()
            raise ToolError(CHANGED)
        srv.verified = True
        return client

    async def _start(self, srv: _Server) -> McpClient:
        cwd = self._base / srv.cfg.name if self._base is not None else None
        client = McpClient(srv.cfg, self._resolve, cwd=cwd, call_timeout=self._call_timeout,
                           start_timeout=self._start_timeout, parent_env=self._parent_env)
        self._set(srv, "starting")
        try:
            await client.start()
        except McpStartRefused as exc:
            srv.state, srv.error = "failed", str(exc)   # fixable without reconfiguring: not sticky
            raise
        except ToolError as exc:
            self._failure(srv, str(exc))
            raise
        except BaseException:
            self._set(srv, "stopped")
            raise
        if self._closed:
            await client.close()
            raise ToolError(UNAVAILABLE)
        srv.client, srv.error, srv.verified = client, "", False
        self._set(srv, "running")
        if self._watcher is None:
            self._watcher = asyncio.create_task(self._watch())
        self._wake.set()
        return client

    def _failure(self, srv: _Server, reason: str) -> None:
        srv.restarts += 1
        srv.error = reason[:200]
        if srv.restarts > MAX_RESTARTS:
            srv.state, srv.sticky = "failed", True
        else:
            self._set(srv, "stopped")

    @staticmethod
    def _set(srv: _Server, state: str) -> None:
        """Change the state, except that a "changed" server keeps saying so until it is reconfigured."""
        if not (srv.sticky and srv.state == "changed"):
            srv.state = state

    async def _drop(self, srv: _Server, client: McpClient, reason: str) -> None:
        """The connection broke: count it once (concurrent callers share one failure) and clean up."""
        if srv.client is client:
            srv.client, srv.verified = None, False
            self._failure(srv, reason)
        await client.close()

    async def _stop(self, srv: _Server) -> None:
        """Stop the client and reset to a clean, stopped state (also clears failed/changed)."""
        async with srv.lock:
            client, srv.client = srv.client, None
            srv.state, srv.error, srv.sticky, srv.verified, srv.restarts = "stopped", "", False, False, 0
            if client is not None:
                await client.close()

    def _expired(self, srv: _Server, now: float) -> bool:
        return srv.client is not None and srv.active == 0 and (srv.last_used or now) + srv.cfg.idle_stop_s <= now

    async def _watch(self) -> None:
        """Sleep until the nearest idle deadline, stop what has expired, repeat. Woken when something changes."""
        while True:
            self._wake.clear()
            now = self._mono()
            idle = [s for s in self._servers.values() if s.client is not None and s.active == 0]
            if any(self._expired(s, now) for s in idle):
                for srv in idle:
                    if self._expired(srv, now):
                        await self._idle_stop(srv)
                continue
            tasks: set[asyncio.Future[Any]] = {asyncio.ensure_future(self._wake.wait())}
            if idle:
                nearest = min((s.last_used or now) + s.cfg.idle_stop_s for s in idle)
                tasks.add(asyncio.ensure_future(self._sleep(nearest - now)))
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _idle_stop(self, srv: _Server) -> None:
        async with srv.lock:
            client = srv.client
            if client is None or srv.active:
                return
            srv.client, srv.verified = None, False
            if srv.state == "running":
                srv.state = "stopped"
            with contextlib.suppress(Exception):
                await client.close()
