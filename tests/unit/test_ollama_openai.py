"""Ollama (streaming, diagnosis, local-only rules) and the OpenAI adapter's parameters."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from lilly.domain.caps import Cap
from lilly.domain.errors import ProviderError
from lilly.domain.ports import CompletionRequest, Message
from lilly.domain.settings import ModelSpec, default_settings, is_private_url, parse_settings, settings_to_dict
from lilly.providers.factory import build_provider
from lilly.providers.http import create_local_client
from lilly.providers.ollama import OllamaProvider, probe
from tests.helpers import MemoryKeyStore

REQ = CompletionRequest((Message("user", "hi"),), 50, deadline_s=5.0)


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def ndjson(*objs: object) -> bytes:
    return ("\n".join(json.dumps(o) for o in objs) + "\n").encode()


# ---- streaming ----------------------------------------------------------------------------------
async def test_the_answer_is_assembled_from_a_stream_and_asks_for_one() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=ndjson(
            {"message": {"content": "Hel"}, "done": False}, {"message": {"content": "lo"}, "done": False},
            {"message": {"content": ""}, "done": True, "done_reason": "stop", "prompt_eval_count": 7, "eval_count": 2}))

    done = await OllamaProvider(client(handler), "llama3.2").complete(REQ)
    assert (done.text, done.input_tokens, done.output_tokens, done.finish_reason) == ("Hello", 7, 2, "stop")
    assert seen[0]["stream"] is True and seen[0]["model"] == "llama3.2"


async def test_json_mode_is_passed_on() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=ndjson({"message": {"content": "{}"}, "done": True}))

    await OllamaProvider(client(handler), "m").complete(CompletionRequest((Message("user", "x"),), 5, json_mode=True))
    assert seen[0]["format"] == "json"


@pytest.mark.parametrize("body", [
    b"",                                                                    # closed before anything
    ndjson({"message": {"content": "partial"}, "done": False}),            # closed before `done`
    b"this is not json\n",
    ndjson({"error": "model failed to load"}),
    ndjson(["a list"]),
])
async def test_a_stream_that_ends_early_or_is_malformed_is_a_retryable_failure(body: bytes) -> None:
    c = client(lambda r: httpx.Response(200, content=body))
    with pytest.raises(ProviderError) as info:
        await OllamaProvider(c, "m").complete(REQ)
    assert info.value.retryable


async def test_a_missing_model_is_a_short_lived_failure_not_a_bad_key() -> None:
    c = client(lambda r: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(ProviderError) as info:
        await OllamaProvider(c, "nope").complete(REQ)
    assert info.value.retryable and info.value.status == 404


async def test_a_server_that_is_not_running_is_a_retryable_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderError) as info:
        await OllamaProvider(client(handler), "m").complete(REQ)
    assert info.value.retryable


async def test_an_oversized_stream_is_cut_off() -> None:
    line = json.dumps({"message": {"content": "x" * 100_000}, "done": False}) + "\n"
    c = client(lambda r: httpx.Response(200, content=(line * 30).encode()))
    with pytest.raises(ProviderError) as info:
        await OllamaProvider(c, "m").complete(REQ)
    assert not info.value.retryable


# ---- the check that explains problems ------------------------------------------------------------
def tags(*names: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.9.1"})
        return httpx.Response(200, json={"models": [{"name": n} for n in names]})

    return handler


async def test_probe_reports_a_ready_model_and_matches_the_default_tag() -> None:
    st = await probe(client(tags("llama3.2:latest", "qwen3:8b")), None, "llama3.2")
    assert st.reachable and st.model_ready and st.version == "0.9.1" and st.models == ("llama3.2:latest", "qwen3:8b")


async def test_probe_says_how_to_install_a_missing_model() -> None:
    st = await probe(client(tags("qwen3:8b")), None, "llama3.2")
    assert st.reachable and st.model_ready is False and "ollama pull llama3.2" in st.message


async def test_probe_without_a_model_lists_what_is_installed() -> None:
    st = await probe(client(tags("a", "b")))
    assert st.model_ready is None and "2 model(s)" in st.message


async def test_probe_says_to_start_ollama_when_nothing_listens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    st = await probe(client(handler), "http://127.0.0.1:1")
    assert not st.reachable and "ollama serve" in st.message and "127.0.0.1:1" in st.message


async def test_probe_says_when_something_else_answers() -> None:
    for resp in (httpx.Response(200, text="<html>router login</html>"), httpx.Response(502), httpx.Response(200, json=[1])):
        st = await probe(client(lambda r, resp=resp: resp), None, "m")
        assert not st.reachable and "does not look like Ollama" in st.message


async def test_probe_tolerates_odd_model_lists() -> None:
    c = client(lambda r: httpx.Response(200, json={"version": "1", "models": [1, {"name": 5}, {"name": "ok"}]})
               if r.url.path == "/api/tags" else httpx.Response(200, json={"version": "1"}))
    assert (await probe(c, None, "ok")).models == ("ok",)


async def test_the_local_client_ignores_proxy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:3128")
    c = create_local_client()
    try:
        assert c.trust_env is False and c.timeout.read == 180.0
    finally:
        await c.aclose()


# ---- local models stay local ---------------------------------------------------------------------
@pytest.mark.parametrize("url, private", [
    ("http://127.0.0.1:11434", True), ("http://localhost:11434", True), ("http://[::1]:11434", True),
    ("http://192.168.1.20:11434", True), ("http://10.0.0.5", True), ("http://100.101.102.103:11434", True),
    ("http://169.254.169.254", False), ("https://api.example.com", False), ("http://8.8.8.8", False),
    ("http://0.0.0.0:11434", False), ("http://[::]:11434", False), ("http://[fd00::1]:11434", True),
    ("http://[2002:808:808::1]/", False), ("http://[2001::1]/", False), ("http://[::ffff:8.8.8.8]/", False),
    ("http://[::ffff:127.0.0.1]/", True), ("http://[64:ff9b::8.8.8.8]/", False),
    ("http://127.0.0.1@evil.com/", False), ("http://localhost.evil.com/", False), ("http://127.0.0.1.nip.io/", False),
    ("http://2130706433/", False), ("http://0x7f.0.0.1/", False), ("http://evil.com#@127.0.0.1", False),
    ("http://my-box.example:11434", False), ("not a url", False), ("http://", False),
])
def test_only_this_computer_or_a_private_network_counts_as_local(url: str, private: bool) -> None:
    assert is_private_url(url) is private


def _with(model: dict[str, object]) -> dict[str, object]:
    d = settings_to_dict(default_settings())
    d["models"] = [model]
    return d


def test_a_local_model_cannot_point_at_the_internet() -> None:
    ok, problems = parse_settings(_with({"name": "box", "provider": "ollama", "model_id": "m", "local": True,
                                         "max_label": "PERSONAL", "base_url": "http://192.168.1.9:11434"}))
    assert ok is not None and not problems
    bad, problems = parse_settings(_with({"name": "box", "provider": "ollama", "model_id": "m", "local": True,
                                          "max_label": "PERSONAL", "base_url": "https://evil.example.com"}))
    assert bad is None and "private network" in problems[0]


def test_only_ollama_can_be_marked_local() -> None:
    bad, problems = parse_settings(_with({"name": "x", "provider": "mistral", "model_id": "m", "local": True}))
    assert bad is None and "only an Ollama model" in problems[0]


# ---- OpenAI --------------------------------------------------------------------------------------
async def _body(model_id: str) -> tuple[dict[str, object], dict[str, str]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    spec = ModelSpec("openai", "openai", model_id, caps=Cap.JSON, key_ref="openai")
    provider = build_provider(spec, client(handler), MemoryKeyStore({"openai": "sk-test"}))
    await provider.complete(CompletionRequest((Message("user", "x"),), 100, json_mode=True, temperature=0.2))
    return json.loads(seen[0].content), dict(seen[0].headers) | {"url": str(seen[0].url)}


async def test_openai_chat_models_get_the_new_token_parameter_and_a_temperature() -> None:
    body, headers = await _body("gpt-4o-mini")
    assert headers["url"] == "https://api.openai.com/v1/chat/completions" and headers["authorization"] == "Bearer sk-test"
    assert body["max_completion_tokens"] == 100 and "max_tokens" not in body and body["temperature"] == 0.2
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("model_id", ["gpt-5", "gpt-5-mini", "o3", "o4-mini"])
async def test_openai_reasoning_models_get_no_temperature_and_room_to_think(model_id: str) -> None:
    body, _ = await _body(model_id)
    assert "temperature" not in body and body["max_completion_tokens"] == 400


async def test_other_vendors_keep_max_tokens() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    spec = ModelSpec("m", "mistral", "mistral-small-latest", key_ref="mistral")
    await build_provider(spec, client(handler), MemoryKeyStore({"mistral": "k"})).complete(REQ)
    assert seen[0]["max_tokens"] == 50 and seen[0]["temperature"] == REQ.temperature


async def test_openai_without_a_key_fails_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be made")

    spec = ModelSpec("openai", "openai", "gpt-4o-mini", key_ref="openai")
    with pytest.raises(ProviderError) as info:
        await build_provider(spec, client(handler), MemoryKeyStore()).complete(REQ)
    assert info.value.status == 401


def test_openai_is_a_known_provider_that_starts_switched_off() -> None:
    spec = next(m for m in default_settings().models if m.provider == "openai")
    assert spec.enabled is False and not spec.local and spec.key_ref == "openai"


async def test_a_stream_without_newlines_is_cut_off_at_the_size_limit_not_read_to_the_end() -> None:
    sent = 0

    async def endless() -> AsyncIterator[bytes]:
        nonlocal sent
        for _ in range(500):
            sent += 1
            yield b"x" * 100_000          # one never-ending line: 50 MB if it were read in full

    c = client(lambda r: httpx.Response(200, content=endless()))
    with pytest.raises(ProviderError) as info:
        await OllamaProvider(c, "m").complete(REQ)
    assert not info.value.retryable and sent < 50      # stopped near the 2 MB cap


async def test_a_final_line_without_a_trailing_newline_still_completes() -> None:
    body = json.dumps({"message": {"content": "hi"}, "done": True, "done_reason": "stop"}).encode()   # no "\n"
    c = client(lambda r: httpx.Response(200, content=body))
    assert (await OllamaProvider(c, "m").complete(REQ)).text == "hi"


async def test_lines_split_across_chunks_are_reassembled() -> None:
    first = json.dumps({"message": {"content": "ab"}, "done": False}).encode()
    last = json.dumps({"message": {"content": "c"}, "done": True}).encode()

    async def chunks() -> AsyncIterator[bytes]:
        raw = first + b"\n" + last + b"\n"
        for i in range(0, len(raw), 7):
            yield raw[i:i + 7]

    c = client(lambda r: httpx.Response(200, content=chunks()))
    assert (await OllamaProvider(c, "m").complete(REQ)).text == "abc"
