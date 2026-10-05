"""One local model call at a time, and one local model in memory.

A local model uses most of a laptop's memory while it is loaded, and two answering at once make each other slow. So
calls to the same Ollama server take turns, and when a call names a different model than the last, the last one is
unloaded first. Waiting for a turn counts against the call's own deadline."""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import httpx

UNLOAD_TIMEOUT_S = 10.0


class LocalGate:
    def __init__(self) -> None:
        self._turn = asyncio.Lock()
        self._loaded: dict[str, str] = {}      # server address -> the model last used on it

    @contextlib.asynccontextmanager
    async def use(self, client: httpx.AsyncClient, base_url: str, model: str) -> AsyncIterator[None]:
        async with self._turn:
            previous = self._loaded.get(base_url)
            if previous is not None and previous != model:
                await self._unload(client, base_url, previous)
            self._loaded[base_url] = model
            yield

    @staticmethod
    async def _unload(client: httpx.AsyncClient, base_url: str, model: str) -> None:
        """Ask the server to drop a model now. Best effort: if it cannot, the server's own timer will."""
        with contextlib.suppress(httpx.HTTPError, TimeoutError):
            async with asyncio.timeout(UNLOAD_TIMEOUT_S):
                await client.post(f"{base_url}/api/generate", json={"model": model, "keep_alive": 0})
