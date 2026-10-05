"""One live connection to one MCP server: handshake, tools/list, tools/call and the server-to-client traffic."""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from lilly.domain.errors import ToolError
from lilly.domain.mcp import (
    CALL_TIMEOUT_S,
    MAX_MESSAGE_BYTES,
    MAX_TOOL_PAGES,
    MAX_TOOLS_PER_SERVER,
    PROTOCOL_VERSIONS,
    START_TIMEOUT_S,
    McpServerConfig,
    McpToolInfo,
    clean_tool,
)
from lilly.tools.mcp import protocol as p
from lilly.tools.mcp.process import McpProcess

log = logging.getLogger("lilly.mcp")
REPLY_TIMEOUT_S = 5.0   # a server that will not read our answers is cut off


class McpClient:
    """Speaks to one server. A server request is never fulfilled: only `ping` is answered, with an empty result;
    sampling, roots, elicitation and everything else get "method not supported"."""

    def __init__(self, cfg: McpServerConfig, resolve_secret: Callable[[str], str | None], *, cwd: Path | None = None,
                 call_timeout: float = CALL_TIMEOUT_S, start_timeout: float = START_TIMEOUT_S,
                 parent_env: Mapping[str, str] | None = None) -> None:
        self._name = cfg.name
        self._proc = McpProcess(cfg, resolve_secret, cwd, parent_env)
        self._call_timeout, self._start_timeout = call_timeout, start_timeout
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 1
        self._write_lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(p.MAX_IN_FLIGHT)
        self._reader: asyncio.Task[None] | None = None
        self._stdout: asyncio.StreamReader | None = None
        self._alive = False
        self._death = "the server is not running"
        self._stale = False
        self._bad_lines = 0

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def stale(self) -> bool:
        """The server said its tool list changed since we last listed it."""
        return self._stale

    @property
    def death_reason(self) -> str:
        return self._death

    async def start(self) -> None:
        """Spawn the server and complete the initialize handshake, or raise ToolError (nothing is left running)."""
        try:
            async with asyncio.timeout(self._start_timeout):
                await self._proc.start()
                self._stdout = self._proc.stdout
                self._alive = True
                self._reader = asyncio.create_task(self._read_loop())
                result = await self._request("initialize", {
                    "protocolVersion": PROTOCOL_VERSIONS[0], "capabilities": {},
                    "clientInfo": {"name": "lilly", "version": "1"}}, None)
                if not isinstance(result, dict) or result.get("protocolVersion") not in PROTOCOL_VERSIONS:
                    raise ToolError("the server speaks a protocol version Lilly does not support")
                await self._send_raw(p.notification("notifications/initialized"))
        except TimeoutError:
            await self.close()
            raise p.McpTimeout("the server took too long to start") from None
        except BaseException:
            await self.close()
            raise

    async def list_tools(self) -> tuple[McpToolInfo, ...]:
        """Every well-formed, uniquely named tool the server offers. Too many pages or tools is a refusal."""
        self._stale = False
        seen: dict[str, McpToolInfo] = {}
        cursor: str | None = None
        for _ in range(MAX_TOOL_PAGES):
            result = await self._request("tools/list", {"cursor": cursor} if cursor else {}, self._call_timeout)
            raw = result.get("tools") if isinstance(result, dict) else None
            if not isinstance(raw, list):
                raise ToolError("the server sent an invalid tool list")
            for entry in raw:
                info = clean_tool(entry)
                if info is not None and info.name not in seen:
                    seen[info.name] = info
                    if len(seen) > MAX_TOOLS_PER_SERVER:
                        raise ToolError("the server offers too many tools")
            cursor = result.get("nextCursor")
            if not isinstance(cursor, str) or not cursor:
                return tuple(seen.values())
            if len(cursor) > 4096:
                raise ToolError("the server sent an invalid tool list")
        raise ToolError("the server's tool list has too many pages")

    async def call_tool(self, name: str, arguments: Mapping[str, Any], timeout: float | None = None) -> p.CallResult:
        limit = self._call_timeout if not timeout or timeout <= 0 else min(timeout, self._call_timeout)
        async with self._slots:
            result = await self._request("tools/call", {"name": name, "arguments": dict(arguments)}, limit)
        return p.parse_call_result(result)

    async def close(self) -> None:
        """Stop the server and everything it started. Safe to call twice."""
        self._alive = False
        reader, self._reader = self._reader, None
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        self._fail_all(p.McpConnectionError("the server was stopped"))
        await self._proc.stop()

    # ---- requests -----------------------------------------------------------------------------
    async def _request(self, method: str, params: Mapping[str, Any], timeout: float | None) -> Any:
        if not self._alive:
            raise p.McpConnectionError(self._death)
        rid, self._next_id = self._next_id, self._next_id + 1
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            async with asyncio.timeout(timeout):
                await self._send_raw(p.request(rid, method, params))
                return await fut
        except TimeoutError:
            self._cancel_notice(rid)
            raise p.McpTimeout(f"the server did not answer {method} in time") from None
        except asyncio.CancelledError:
            self._cancel_notice(rid)
            raise
        finally:
            self._pending.pop(rid, None)
            if fut.done() and not fut.cancelled():
                fut.exception()  # mark retrieved

    async def _send_raw(self, data: bytes) -> None:
        if len(data) > MAX_MESSAGE_BYTES:
            raise ToolError("the request is too large to send")
        async with self._write_lock:
            try:
                self._proc.write(data)
                await self._proc.drain()
            except (OSError, RuntimeError) as exc:
                raise p.McpConnectionError("the server closed its input") from exc

    def _cancel_notice(self, rid: int) -> None:
        """Best effort: tell the server we no longer wait. A late answer is ignored anyway."""
        if self._alive:
            with contextlib.suppress(OSError, RuntimeError):
                self._proc.write(p.notification("notifications/cancelled", {"requestId": rid}))

    def _fail_all(self, exc: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(exc)

    # ---- reading ------------------------------------------------------------------------------
    async def _read_loop(self) -> None:
        assert self._stdout is not None
        reason = "the server exited"
        try:
            while True:
                try:
                    line = await self._stdout.readline()
                except ValueError:  # asyncio.LimitOverrunError surfaces as ValueError from readline
                    reason = "the server sent a message that was too large"
                    break
                if not line:
                    break
                if len(line.rstrip(b"\r\n")) > MAX_MESSAGE_BYTES:
                    reason = "the server sent a message that was too large"
                    break
                if not line.strip():
                    continue
                msg = p.decode(line)
                if msg is None:
                    self._bad_lines += 1
                    if self._bad_lines >= p.MAX_BAD_LINES:
                        reason = "the server sent too many invalid messages"
                        break
                    continue
                if not await self._dispatch(msg):
                    reason = "the server stopped reading our answers"
                    break
        except OSError:
            reason = "the connection to the server broke"
        self._alive = False
        self._death = reason
        log.debug("mcp server %s connection ended: %s (invalid lines: %d)", self._name, reason, self._bad_lines)
        self._fail_all(p.McpConnectionError(reason))
        await self._proc.stop()

    async def _dispatch(self, msg: dict[str, Any]) -> bool:
        """Handle one message; False means the server must be cut off."""
        method = msg.get("method")
        if isinstance(method, str):
            rid = p.valid_id(msg.get("id"))
            if rid is None:
                if method == "notifications/tools/list_changed":
                    self._stale = True
                return True  # any other notification, or a request with an unusable id, is ignored
            reply = p.result_reply(rid, {}) if method == "ping" else p.error_reply(
                rid, p.METHOD_NOT_FOUND, "method not supported")
            try:
                async with asyncio.timeout(REPLY_TIMEOUT_S):
                    await self._send_raw(reply)
            except (TimeoutError, ToolError):
                return False
            return True
        if "id" in msg:
            self._on_response(msg)
        return True

    def _on_response(self, msg: dict[str, Any]) -> None:
        rid = msg.get("id")
        fut = self._pending.get(rid) if isinstance(rid, int) and not isinstance(rid, bool) else None
        if fut is None or fut.done():
            return  # not ours (or late): ignored
        error = msg.get("error")
        if error is not None:
            text = error.get("message") if isinstance(error, dict) else None
            fut.set_exception(ToolError(f"the server reported an error: {str(text)[:200] if text else 'unknown'}"))
        elif "result" in msg:
            fut.set_result(msg["result"])
        else:
            fut.set_exception(ToolError("the server sent an invalid answer"))
