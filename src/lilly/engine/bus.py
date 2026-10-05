"""In-process event bus feeding the live event stream (SSE)."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from typing import Any

Message = dict[str, Any]


class EventBus:
    """Fan-out of small JSON-able messages to any number of subscribers.

    A subscriber that falls behind is dropped rather than allowed to hold memory: its stream ends and
    the client reconnects and reloads, which is safe because every message is also in the database.
    """

    def __init__(self, queue_size: int = 256) -> None:
        self._queue_size = queue_size
        self._subs: set[asyncio.Queue[Message | None]] = set()

    def publish(self, message: Message) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                self._subs.discard(q)
                with contextlib.suppress(asyncio.QueueFull):
                    q.get_nowait()
                    q.put_nowait(None)  # tell the subscriber to end its stream

    async def subscribe(self) -> AsyncGenerator[Message, None]:
        q: asyncio.Queue[Message | None] = asyncio.Queue(self._queue_size)
        self._subs.add(q)
        try:
            while (message := await q.get()) is not None:
                yield message
        finally:
            self._subs.discard(q)

    def close(self) -> None:
        """End every subscriber's stream (daemon shutdown)."""
        for q in list(self._subs):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(None)
        self._subs.clear()
