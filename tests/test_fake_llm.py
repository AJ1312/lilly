"""Tests for the FakeLLMServer (FAKE-01 and FAKE-02)."""
from __future__ import annotations

import httpx

from tests.fake_llm import FakeLLMServer, ScriptedReply


def test_fake_01_replies_in_order_and_records_requests() -> None:
    """FAKE-01: The fake server returns exactly the scripted replies in order and records requests."""
    server = FakeLLMServer()
    server.enqueue("first reply")
    server.enqueue("second reply")
    server.enqueue(ScriptedReply(tool_calls=[{"name": "fs__read", "arguments": {"path": "/tmp/test.txt"}}]))
    server.start()

    try:
        with httpx.Client(base_url=server.base_url) as client:
            # First request
            r1 = client.post(
                "/v1/chat/completions",
                json={"model": "test-model", "messages": [{"role": "user", "content": "ping 1"}]},
            )
            assert r1.status_code == 200
            data1 = r1.json()
            assert data1["choices"][0]["message"]["content"] == "first reply"

            # Second request
            r2 = client.post(
                "/v1/chat/completions",
                json={"model": "test-model", "messages": [{"role": "user", "content": "ping 2"}]},
            )
            assert r2.status_code == 200
            data2 = r2.json()
            assert data2["choices"][0]["message"]["content"] == "second reply"

            # Third request: tool call
            r3 = client.post(
                "/v1/chat/completions",
                json={
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "ping 3"}],
                    "tools": [{"type": "function", "function": {"name": "fs__read"}}],
                },
            )
            assert r3.status_code == 200
            data3 = r3.json()
            call = data3["choices"][0]["message"]["tool_calls"][0]
            assert call["function"]["name"] == "fs__read"
            assert "/tmp/test.txt" in call["function"]["arguments"]

        # Check recorded requests
        assert len(server.requests) == 3
        assert server.requests[0].messages == [{"role": "user", "content": "ping 1"}]
        assert server.requests[1].messages == [{"role": "user", "content": "ping 2"}]
        assert server.requests[2].tools == [{"type": "function", "function": {"name": "fs__read"}}]
    finally:
        server.close()


def test_fake_02_scripted_429_headers_intact() -> None:
    """FAKE-02: Scripted 429 headers and retry details arrive intact."""
    server = FakeLLMServer()
    server.enqueue(ScriptedReply(status_code=429, retry_after="15"))
    server.enqueue(ScriptedReply(status_code=429, retry_delay="34s"))
    server.start()

    try:
        with httpx.Client(base_url=server.base_url) as client:
            # OpenAI dialect 429 with Retry-After header
            r1 = client.post(
                "/v1/chat/completions",
                json={"model": "test-model", "messages": [{"role": "user", "content": "ping"}]},
            )
            assert r1.status_code == 429
            assert r1.headers.get("Retry-After") == "15"

            # Gemini dialect 429 with Google-style retryDelay
            r2 = client.post(
                "/v1beta/models/gemini-1.5-flash:generateContent",
                json={"contents": [{"parts": [{"text": "ping"}]}]},
            )
            assert r2.status_code == 429
            body = r2.json()
            assert "error" in body
            details = body["error"].get("details", [])
            assert len(details) > 0
            assert details[0].get("retryDelay") == "34s"
    finally:
        server.close()
