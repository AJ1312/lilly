"""Local models are polite: one call at a time, one model in memory, and they leave memory when idle."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from lilly.domain.ports import CompletionRequest, Message
from lilly.providers.local_gate import LocalGate
from lilly.providers.ollama import OllamaProvider

pytestmark = pytest.mark.asyncio
REQ = CompletionRequest((Message("user", "hi"),), 50, deadline_s=5.0)


class Server:
    """A fake Ollama that records every request and how many answers were being written at once."""

    def __init__(self, delay: float = 0.0) -> None:
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.delay, self.busy, self.peak = delay, 0, 0

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    async def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append((request.url.path, body))
        if request.url.path == "/api/chat":
            self.busy += 1
            self.peak = max(self.peak, self.busy)
            try:
                await asyncio.sleep(self.delay)
            finally:
                self.busy -= 1
        line = json.dumps({"message": {"content": "ok"}, "done": True, "done_reason": "stop"}) + "\n"
        return httpx.Response(200, content=line.encode())


def provider(server: Server, model: str, gate: LocalGate, keep: Callable[[], int] = lambda: 300) -> OllamaProvider:
    return OllamaProvider(server.client(), model, None, gate, keep)


async def test_the_model_is_asked_to_stay_loaded_for_the_chosen_time_and_it_can_change_live() -> None:
    server, seconds = Server(), [300]
    p = provider(server, "m", LocalGate(), lambda: seconds[0])
    await p.complete(REQ)
    seconds[0] = 0
    await p.complete(REQ)
    assert [b["keep_alive"] for path, b in server.requests if path == "/api/chat"] == ["300s", "0s"]


async def test_calls_to_one_server_take_turns() -> None:
    server, gate = Server(delay=0.05), LocalGate()
    await asyncio.gather(*(provider(server, "m", gate).complete(REQ) for _ in range(4)))
    assert server.peak == 1


async def test_switching_models_unloads_the_old_one_first() -> None:
    server, gate = Server(), LocalGate()
    await provider(server, "small", gate).complete(REQ)
    await provider(server, "small", gate).complete(REQ)         # same model: nothing to unload
    await provider(server, "big", gate).complete(REQ)
    unloads = [b for path, b in server.requests if path == "/api/generate"]
    assert unloads == [{"model": "small", "keep_alive": 0}]
    order = [p for p, _ in server.requests]
    assert order.index("/api/generate") < len(order) - 1 and order[-1] == "/api/chat"


async def test_a_server_that_cannot_unload_does_not_block_the_next_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/generate":
            raise httpx.ConnectError("down")
        return httpx.Response(200, content=(json.dumps({"message": {"content": "ok"}, "done": True}) + "\n").encode())

    gate = LocalGate()
    c = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await OllamaProvider(c, "a", None, gate).complete(REQ)
    assert (await OllamaProvider(c, "b", None, gate).complete(REQ)).text == "ok"
