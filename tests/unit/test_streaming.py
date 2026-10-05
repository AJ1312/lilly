"""Streaming replies: providers report the text so far, and the executor publishes it at a bounded rate."""
from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from lilly.domain.errors import ProviderError
from lilly.domain.ports import CompletionRequest, Message
from lilly.engine.stream import TextStream
from lilly.providers.base import post_sse
from lilly.providers.ollama import OllamaProvider
from lilly.providers.openai_compat import OpenAICompatProvider
from tests.helpers import MemoryKeyStore


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def sse(*objs: object, done: bool = True) -> bytes:
    body = "".join(f"data: {json.dumps(o)}\n\n" for o in objs)
    return (body + ("data: [DONE]\n\n" if done else "")).encode()


def delta(text: str, finish: str | None = None, usage: dict[str, int] | None = None) -> dict[str, object]:
    return {"choices": [{"delta": {"content": text}, "finish_reason": finish}], **({"usage": usage} if usage else {})}


def request(seen: list[str]) -> CompletionRequest:
    return CompletionRequest((Message("user", "hi"),), 50, deadline_s=5.0, on_text=seen.append)


async def test_ollama_reports_the_text_so_far_after_each_piece() -> None:
    lines = [{"message": {"content": "Hel"}, "done": False}, {"message": {"content": "lo"}, "done": False},
             {"message": {"content": ""}, "done": True, "done_reason": "stop", "prompt_eval_count": 3, "eval_count": 2}]
    c = client(lambda r: httpx.Response(200, content=("\n".join(json.dumps(x) for x in lines) + "\n").encode()))
    seen: list[str] = []
    done = await OllamaProvider(c, "m").complete(request(seen))
    assert done.text == "Hello" and seen == ["Hel", "Hello"]


async def test_openai_style_streaming_collects_text_usage_and_finish_reason() -> None:
    bodies: list[dict[str, object]] = []

    def handler(r: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(r.content))
        return httpx.Response(200, content=sse(delta("Hel"), delta("lo", "stop"),
                                               {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}}))

    keys = MemoryKeyStore({"openai": "sk-test"})
    p = OpenAICompatProvider("openai", client(handler), keys, "openai", "gpt-4o-mini", "https://x.test/v1",
                             stream_usage=True)
    seen: list[str] = []
    done = await p.complete(request(seen))
    assert (done.text, done.input_tokens, done.output_tokens, done.finish_reason) == ("Hello", 4, 2, "stop")
    assert seen == ["Hel", "Hello"]
    assert bodies[0]["stream"] is True and bodies[0]["stream_options"] == {"include_usage": True}


async def test_a_provider_that_does_not_take_stream_options_is_not_sent_them() -> None:
    bodies: list[dict[str, object]] = []

    def handler(r: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(r.content))
        return httpx.Response(200, content=sse(delta("ok", "stop")))

    keys = MemoryKeyStore({"mistral": "k"})
    p = OpenAICompatProvider("mistral", client(handler), keys, "mistral", "m", "https://x.test/v1")
    await p.complete(request([]))
    assert "stream_options" not in bodies[0] and bodies[0]["stream"] is True


async def test_without_a_listener_the_ordinary_non_streaming_call_is_used() -> None:
    bodies: list[dict[str, object]] = []

    def handler(r: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(r.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]})

    keys = MemoryKeyStore({"mistral": "k"})
    p = OpenAICompatProvider("mistral", client(handler), keys, "mistral", "m", "https://x.test/v1")
    done = await p.complete(CompletionRequest((Message("user", "x"),), 5))
    assert done.text == "hi" and "stream" not in bodies[0]


@pytest.mark.parametrize("body", [b"data: not json\n\n", b"", sse(delta("cut"), done=False)])
async def test_a_broken_or_cut_off_stream_is_a_retryable_failure(body: bytes) -> None:
    keys = MemoryKeyStore({"mistral": "k"})
    p = OpenAICompatProvider("mistral", client(lambda r: httpx.Response(200, content=body)), keys, "mistral", "m",
                             "https://x.test/v1")
    with pytest.raises(ProviderError) as info:
        await p.complete(request([]))
    assert info.value.retryable


async def test_an_error_status_is_mapped_while_streaming() -> None:
    keys = MemoryKeyStore({"mistral": "k"})
    p = OpenAICompatProvider("mistral", client(lambda r: httpx.Response(429, headers={"retry-after": "7"})), keys,
                             "mistral", "m", "https://x.test/v1")
    with pytest.raises(ProviderError) as info:
        await p.complete(request([]))
    assert info.value.retry_after == 7.0


async def test_an_oversized_event_stream_is_cut_off() -> None:
    c = client(lambda r: httpx.Response(200, content=b"data: " + b"x" * 5000))
    with pytest.raises(ProviderError):
        await post_sse(c, "https://x.test", headers={}, body={}, deadline_s=5.0, on_event=lambda e: None, max_bytes=1000)


class StubBus:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def publish(self, message: dict[str, object]) -> None:
        self.messages.append(message)


def test_published_text_is_throttled_and_carries_the_whole_text_so_far() -> None:
    bus, now = StubBus(), [0.0]
    stream = TextStream(bus, "t1", "s1", lambda: now[0], min_interval_s=0.2)  # type: ignore[arg-type]
    stream("a")
    now[0] = 0.05
    stream("ab")                      # too soon: dropped
    now[0] = 0.3
    stream("abc")
    assert [m["text"] for m in bus.messages] == ["a", "abc"]
    assert bus.messages[0] == {"type": "text", "task_id": "t1", "step_id": "s1", "text": "a"}


def test_very_long_text_is_cut_to_its_tail_for_display() -> None:
    bus = StubBus()
    TextStream(bus, "t", "s", lambda: 0.0, max_chars=10)("0123456789abcdef")  # type: ignore[arg-type]
    shown = str(bus.messages[0]["text"])
    assert len(shown) == 10 and shown.endswith("abcdef") and shown.startswith("…")
