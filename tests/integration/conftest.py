"""Fixtures for the API tests: a real Runtime and web app, with the model provider faked at the HTTP layer."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from lilly.app.paths import init_paths
from lilly.app.runtime import Runtime
from lilly.ui.app import create_app
from lilly.ui.security import Auth
from tests.helpers import MemoryKeyStore


@dataclass
class FakeProvider:
    """Stands in for the model vendor's HTTP API. Replies are consumed in order."""

    replies: list[str] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if "chat/completions" not in request.url.path:
            return httpx.Response(404)
        body = json.loads(request.content)
        self.requests.append(body)
        if not self.replies:
            return httpx.Response(500, json={"error": "no scripted reply"})
        content = self.replies.pop(0)
        if body.get("stream"):          # the writing step streams: answer as server-sent events, in two pieces
            half = len(content) // 2
            events = [{"choices": [{"delta": {"content": part}, "finish_reason": None}]} for part in (content[:half], content[half:])]
            events.append({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 5}})
            sse = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
            return httpx.Response(200, content=sse.encode())
        return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 5}})


@dataclass
class Api:
    http: httpx.AsyncClient
    runtime: Runtime
    auth: Auth
    provider: FakeProvider
    shared: Path
    csrf: str = ""

    async def sign_in(self) -> None:
        r = await self.http.post("/api/login", json={"token": self.auth.token})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf"]

    def headers(self) -> dict[str, str]:
        return {"X-Lilly-CSRF": self.csrf}

    async def get(self, path: str, **kw: Any) -> httpx.Response:
        return await self.http.get(path, **kw)

    async def send(self, method: str, path: str, body: Any = None) -> httpx.Response:
        return await self.http.request(method, path, json=body, headers=self.headers())

    async def finished(self, task_id: str, timeout: float = 10.0) -> dict[str, Any]:
        async with asyncio.timeout(timeout):
            while True:
                data = (await self.get(f"/api/tasks/{task_id}")).json()
                if data["task"]["state"] in ("DONE", "FAILED", "CANCELLED", "EXPIRED"):
                    return dict(data)
                await asyncio.sleep(0.02)

    async def approval(self, timeout: float = 5.0) -> dict[str, Any]:
        async with asyncio.timeout(timeout):
            while not (rows := (await self.get("/api/approvals?status=pending")).json()["approvals"]):
                await asyncio.sleep(0.02)
        return dict(rows[0])


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[Api]:
    provider = FakeProvider()
    client = httpx.AsyncClient(transport=httpx.MockTransport(provider.handle))
    paths = init_paths(tmp_path / "lilly-home")
    runtime = await Runtime.create(paths, client=client, keys=MemoryKeyStore({"mistral": "test-key"}))
    from dataclasses import replace
    runtime.settings = replace(runtime.settings, engine=replace(runtime.settings.engine, mode="plan"))
    runtime.orchestrator.configure(runtime.settings)
    auth = Auth(paths.token, paths.secret)
    shared = tmp_path / "shared"
    shared.mkdir()
    app = create_app(runtime, auth, web_dir=tmp_path / "no-web")
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787")
    yield Api(http, runtime, auth, provider, shared)
    await http.aclose()
    await runtime.close()
    await client.aclose()
