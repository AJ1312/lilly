"""Testing and discovering an Ollama model through the API, with the Ollama server faked at the HTTP layer."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from lilly.app.paths import init_paths
from lilly.app.runtime import Runtime
from lilly.domain.settings import settings_to_dict
from lilly.ui.app import create_app
from lilly.ui.security import Auth
from tests.helpers import MemoryKeyStore
from tests.integration.conftest import Api, FakeProvider

pytestmark = pytest.mark.asyncio


class FakeOllama:
    def __init__(self) -> None:
        self.up, self.installed, self.chats = True, ["llama3.2:latest"], 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        if not self.up:
            raise httpx.ConnectError("refused")
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.9.1"})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n} for n in self.installed]})
        if request.url.path == "/api/chat":
            self.chats += 1
            wanted = json.loads(request.content)["model"]
            if wanted not in self.installed and f"{wanted}:latest" not in self.installed:
                return httpx.Response(404, json={"error": "model not found"})
            line = json.dumps({"message": {"content": "ok"}, "done": True, "done_reason": "stop"}) + "\n"
            return httpx.Response(200, content=line.encode())
        return httpx.Response(404)


@pytest.fixture
async def ollama_api(tmp_path: Path) -> AsyncIterator[tuple[Api, FakeOllama]]:
    provider, ollama = FakeProvider(), FakeOllama()
    client = httpx.AsyncClient(transport=httpx.MockTransport(provider.handle))
    local = httpx.AsyncClient(transport=httpx.MockTransport(ollama.handle))
    paths = init_paths(tmp_path / "lilly-home")
    runtime = await Runtime.create(paths, client=client, local_client=local, keys=MemoryKeyStore())
    auth = Auth(paths.token, paths.secret)
    shared = tmp_path / "shared"
    shared.mkdir()
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime, auth, web_dir=tmp_path / "no-web")),
                             base_url="http://127.0.0.1:8787")
    api = Api(http, runtime, auth, provider, shared)
    await api.sign_in()
    current = settings_to_dict(runtime.settings)
    for m in current["models"]:
        m["enabled"] = m["name"] == "ollama-local"
    assert (await api.send("PUT", "/api/settings", current)).status_code == 200
    yield api, ollama
    await http.aclose()
    await runtime.close()
    await client.aclose()
    await local.aclose()


async def test_ollama_traffic_uses_the_local_client_only(ollama_api: tuple[Api, FakeOllama]) -> None:
    api, ollama = ollama_api
    assert (await api.send("POST", "/api/models/ollama-local/test")).json()["ok"] is True
    assert ollama.chats == 1 and not api.provider.requests          # nothing went through the internet client


async def test_discovery_lists_what_is_installed(ollama_api: tuple[Api, FakeOllama]) -> None:
    api, ollama = ollama_api
    ollama.installed = ["llama3.2:latest", "qwen3:8b"]
    got = (await api.get("/api/models/ollama-local/ollama")).json()
    assert got["reachable"] and got["model_ready"] and got["models"] == ["llama3.2:latest", "qwen3:8b"]
    assert (await api.get("/api/models/mistral-small/ollama")).status_code == 404       # not an Ollama model
    assert (await api.get("/api/models/nope/ollama")).status_code == 404


async def test_a_failed_test_says_what_to_do(ollama_api: tuple[Api, FakeOllama]) -> None:
    api, ollama = ollama_api
    ollama.installed = ["qwen3:8b"]
    missing = (await api.send("POST", "/api/models/ollama-local/test")).json()
    assert missing["ok"] is False and "ollama pull llama3.2" in missing["error"]
    ollama.up = False
    down = (await api.send("POST", "/api/models/ollama-local/test")).json()
    assert down["ok"] is False and "ollama serve" in down["error"]
    assert (await api.get("/api/models/ollama-local/ollama")).json()["reachable"] is False
