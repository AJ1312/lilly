"""A small Chrome DevTools Protocol client: JSON messages over one WebSocket, matched by id, with events."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

from lilly.domain.errors import ToolError

log = logging.getLogger("lilly.browser")

MAX_MESSAGE = 8 * 1024 * 1024     # one protocol message; a page snapshot is far smaller
CALL_TIMEOUT_S = 20.0
Handler = Callable[[dict[str, Any], str | None], Coroutine[Any, Any, None]]


class Cdp:
    """One connection to the browser. Every call has a time limit; a lost connection fails every waiting call."""

    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws
        self._next = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._handlers: dict[str, Handler] = {}
        self._running: set[asyncio.Task[None]] = set()
        self._reader = asyncio.create_task(self._read(), name="lilly-cdp-reader")

    @classmethod
    async def connect(cls, url: str) -> Cdp:
        try:
            ws = await websockets.connect(url, max_size=MAX_MESSAGE, open_timeout=10, ping_interval=None,
                                          proxy=None)
        except (OSError, TimeoutError, websockets.WebSocketException) as exc:
            raise ToolError("could not connect to the browser") from exc
        return cls(ws)

    def on(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    @property
    def closed(self) -> bool:
        return self._reader.done()

    async def call(self, method: str, params: dict[str, Any] | None = None, session: str | None = None,
                   timeout: float = CALL_TIMEOUT_S) -> dict[str, Any]:
        if self.closed:
            raise ToolError("the browser is not running")
        self._next += 1
        ident = self._next
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[ident] = future
        message: dict[str, Any] = {"id": ident, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        try:
            await self._ws.send(json.dumps(message))
            async with asyncio.timeout(timeout):
                return await future
        except TimeoutError:
            raise ToolError("the browser did not answer in time") from None
        except websockets.WebSocketException as exc:
            raise ToolError("the browser connection was lost") from exc
        finally:
            self._pending.pop(ident, None)

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if isinstance(msg.get("id"), int):
                    future = self._pending.get(msg["id"])
                    if future is not None and not future.done():
                        if "error" in msg:
                            future.set_exception(ToolError("the browser refused that: "
                                                           + str(msg["error"].get("message", ""))[:200]))
                        else:
                            future.set_result(msg.get("result", {}))
                elif isinstance(msg.get("method"), str) and (handler := self._handlers.get(msg["method"])):
                    task = asyncio.create_task(handler(msg.get("params", {}), msg.get("sessionId")))
                    self._running.add(task)
                    task.add_done_callback(self._finished)
        except websockets.WebSocketException:
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ToolError("the browser connection was lost"))

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._running.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.warning("a browser event handler failed: %s", type(task.exception()).__name__)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._ws.close()
        self._reader.cancel()
        for task in list(self._running):
            task.cancel()
        await asyncio.gather(self._reader, *self._running, return_exceptions=True)
