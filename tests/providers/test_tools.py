"""Tests PROV-01 through PROV-10 and Phase 2 Gate for tool calling across providers."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from lilly.domain.ports import CompletionRequest, Message, ModelToolCall, ToolSchema
from lilly.domain.tools_registry import (
    DEFAULT_TOOLS,
    check_tool_name,
    unwire_name,
    wire_name,
)
from lilly.providers.action_protocol import (
    ActionProtocolAdapter,
    is_detected_protocol,
    mark_detected_protocol,
    parse_protocol_reply,
    reset_detected_protocol,
)
from lilly.providers.gemini import GeminiProvider, to_gemini_schema
from lilly.providers.ollama import OllamaProvider
from lilly.providers.openai_compat import OpenAICompatProvider
from tests.fake_llm import FakeLLMServer, ScriptedReply
from tests.helpers import MemoryKeyStore


@pytest.fixture
async def http_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        yield client


# ============================================================================
# PROV-01: Schema translation and subset conversion
# ============================================================================

def test_prov_01_gemini_schema_translation() -> None:
    raw_schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "description": "A test tool",
        "additionalProperties": False,
        "required": ["name", "count", "tags"],
        "properties": {
            "name": {
                "type": "string",
                "description": "User name",
                "minLength": 1,
            },
            "count": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
            },
            "ratio": {
                "type": "number",
            },
            "enabled": {
                "type": "boolean",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
            },
            "mode": {
                "type": "string",
                "enum": ["fast", "slow"],
            },
            "nested": {
                "type": "object",
                "properties": {
                    "inner": {"type": "string"},
                },
                "required": ["inner"],
                "additionalProperties": False,
            },
        },
    }

    gemini_schema = to_gemini_schema(raw_schema)

    # 1. Types uppercase
    assert gemini_schema["type"] == "OBJECT"
    assert gemini_schema["description"] == "A test tool"
    assert gemini_schema["required"] == ["name", "count", "tags"]

    props = gemini_schema["properties"]
    assert props["name"]["type"] == "STRING"
    assert props["name"]["description"] == "User name"
    assert "minLength" not in props["name"]

    assert props["count"]["type"] == "INTEGER"
    assert "minimum" not in props["count"]
    assert "maximum" not in props["count"]

    assert props["ratio"]["type"] == "NUMBER"
    assert props["enabled"]["type"] == "BOOLEAN"
    assert props["tags"]["type"] == "ARRAY"
    assert props["tags"]["items"]["type"] == "STRING"

    assert props["mode"]["type"] == "STRING"
    assert props["mode"]["enum"] == ["fast", "slow"]

    assert props["nested"]["type"] == "OBJECT"
    assert props["nested"]["properties"]["inner"]["type"] == "STRING"
    assert props["nested"]["required"] == ["inner"]
    assert "additionalProperties" not in props["nested"]

    # 2. Unsupported keywords dropped at root
    assert "$schema" not in gemini_schema
    assert "additionalProperties" not in gemini_schema


def test_prov_01_all_default_tools_have_convertible_schemas() -> None:
    for tool_name, spec in DEFAULT_TOOLS.items():
        assert spec.schema, f"Tool {tool_name} missing schema"
        gemini = to_gemini_schema(spec.schema)
        assert gemini["type"] == "OBJECT", f"Tool {tool_name} gemini schema root type must be OBJECT"


# ============================================================================
# PROV-02: Wire names and tool registration
# ============================================================================

def test_prov_02_wire_name_mapping() -> None:
    assert wire_name("fs.read") == "fs__read"
    assert wire_name("data.table_query") == "data__table_query"
    assert wire_name("agent.plan") == "agent__plan"

    assert unwire_name("fs__read") == "fs.read"
    assert unwire_name("data__table_query") == "data.table_query"
    assert unwire_name("agent__plan") == "agent.plan"


def test_prov_02_rejection_of_double_underscore_in_tool_names() -> None:
    # Valid names
    check_tool_name("fs.read")
    check_tool_name("simple_tool")

    # Double underscore rejected
    with pytest.raises(ValueError, match="cannot contain '__'"):
        check_tool_name("bad__tool")
    with pytest.raises(ValueError, match="cannot contain '__'"):
        check_tool_name("fs.read__custom")


# ============================================================================
# PROV-03: OpenAI dialect: parse arguments, tool_calls, and tool role
# ============================================================================

async def test_prov_03_openai_tool_calls_and_tool_role(http_client: httpx.AsyncClient) -> None:
    server = FakeLLMServer([
        ScriptedReply(tool_calls=[{"name": "fs__read", "arguments": {"path": "/workspace/doc.txt"}}]),
    ])
    server.start()
    try:
        keys = MemoryKeyStore({"test": "sk-secret"})
        provider = OpenAICompatProvider(
            name="test-openai",
            client=http_client,
            keys=keys,
            key_ref="test",
            model_id="test-model",
            base_url=f"{server.openai_url}",
        )

        tools = (ToolSchema(name="fs.read", description="Read file", parameters={"type": "object"}),)
        req = CompletionRequest(
            messages=(Message(role="user", content="Read /workspace/doc.txt"),),
            max_tokens=1000,
            tools=tools,
            tool_choice="auto",
        )

        res = await provider.complete(req)
        assert len(res.tool_calls) == 1
        tc = res.tool_calls[0]
        assert tc.name == "fs.read"
        assert tc.arguments == {"path": "/workspace/doc.txt"}
        assert tc.error is None
        assert tc.raw == '{"path": "/workspace/doc.txt"}'

        # Next turn: tool result and assistant previous tool call roundtrip
        server.enqueue(ScriptedReply(content="The file contains hello."))
        req2 = CompletionRequest(
            messages=(
                Message(role="user", content="Read /workspace/doc.txt"),
                Message(role="assistant", content="", tool_calls=(tc,)),
                Message(role="tool", content="hello", tool_call_id=tc.id),
            ),
            max_tokens=1000,
            tools=tools,
        )
        res2 = await provider.complete(req2)
        assert res2.text == "The file contains hello."
        assert len(res2.tool_calls) == 0

        # Check recorded request formatting
        recorded = server.requests[1]
        assert recorded.messages is not None
        assert len(recorded.messages) == 3
        # Assistant message has tool_calls with wire_name
        asst_msg = recorded.messages[1]
        assert asst_msg["role"] == "assistant"
        assert asst_msg["tool_calls"][0]["function"]["name"] == "fs__read"
        # Tool message has tool_call_id
        tool_msg = recorded.messages[2]
        assert tool_msg["role"] == "tool"
        assert tool_msg["content"] == "hello"
        assert tool_msg["tool_call_id"] == tc.id
    finally:
        server.close()


# ============================================================================
# PROV-04: OpenAI invalid JSON: error field preserved
# ============================================================================

async def test_prov_04_openai_invalid_json_arguments(http_client: httpx.AsyncClient) -> None:
    # 1. Broken JSON syntax
    server = FakeLLMServer([
        ScriptedReply(tool_calls=[{"name": "fs__read", "arguments": '{"path": "/truncated'}]),
        # 2. Valid JSON, but not an object
        ScriptedReply(tool_calls=[{"name": "fs__read", "arguments": "42"}]),
    ])
    server.start()
    try:
        keys = MemoryKeyStore({"test": "sk-secret"})
        provider = OpenAICompatProvider(
            name="test-openai",
            client=http_client,
            keys=keys,
            key_ref="test",
            model_id="test-model",
            base_url=f"{server.openai_url}",
        )

        req = CompletionRequest(
            messages=(Message(role="user", content="Read file"),),
            max_tokens=1000,
            tools=(ToolSchema(name="fs.read", description="Read file", parameters={}),),
        )

        res1 = await provider.complete(req)
        assert len(res1.tool_calls) == 1
        tc1 = res1.tool_calls[0]
        assert tc1.name == "fs.read"
        assert tc1.arguments is None
        assert tc1.raw == '{"path": "/truncated'
        assert tc1.error is not None
        assert "invalid JSON" in tc1.error

        res2 = await provider.complete(req)
        assert len(res2.tool_calls) == 1
        tc2 = res2.tool_calls[0]
        assert tc2.name == "fs.read"
        assert tc2.arguments is None
        assert tc2.raw == "42"
        assert tc2.error == "arguments must be a JSON object"
    finally:
        server.close()


# ============================================================================
# PROV-05: OpenAI streaming: delta accumulation across chunks
# ============================================================================

async def test_prov_05_openai_streaming_split_arguments(http_client: httpx.AsyncClient) -> None:
    # FakeLLMServer splits argument strings into two chunks during streaming
    server = FakeLLMServer([
        ScriptedReply(
            tool_calls=[
                {"name": "fs__read", "arguments": {"path": "/deep/nested/path/to/target/file.txt", "max_bytes": 1024}}
            ]
        ),
    ])
    server.start()
    try:
        keys = MemoryKeyStore({"test": "sk-secret"})
        provider = OpenAICompatProvider(
            name="test-openai",
            client=http_client,
            keys=keys,
            key_ref="test",
            model_id="test-model",
            base_url=f"{server.openai_url}",
        )

        streamed_text: list[str] = []
        req = CompletionRequest(
            messages=(Message(role="user", content="Read file"),),
            max_tokens=1000,
            tools=(ToolSchema(name="fs.read", description="Read file", parameters={}),),
            on_text=lambda t: streamed_text.append(t),
        )

        res = await provider.complete(req)
        assert len(res.tool_calls) == 1
        tc = res.tool_calls[0]
        assert tc.name == "fs.read"
        assert tc.arguments == {"path": "/deep/nested/path/to/target/file.txt", "max_bytes": 1024}
        assert tc.error is None
    finally:
        server.close()


# ============================================================================
# PROV-06: Gemini dialect: functionDeclarations, functionCall, functionResponse
# ============================================================================

async def test_prov_06_gemini_tool_calls_and_responses(http_client: httpx.AsyncClient) -> None:
    server = FakeLLMServer([
        ScriptedReply(tool_calls=[{"name": "fs__read", "arguments": {"path": "/home/user/notes.md"}}]),
    ])
    server.start()
    try:
        keys = MemoryKeyStore({"test": "gemini-api-key"})
        provider = GeminiProvider(
            client=http_client,
            keys=keys,
            key_ref="test",
            model_id="gemini-1.5-flash",
            base_url=f"{server.gemini_url}",
        )

        tools = (ToolSchema(name="fs.read", description="Read file", parameters={"type": "object"}),)
        req = CompletionRequest(
            messages=(Message(role="user", content="Read my notes"),),
            max_tokens=1000,
            tools=tools,
        )

        res = await provider.complete(req)
        assert len(res.tool_calls) == 1
        tc = res.tool_calls[0]
        assert tc.name == "fs.read"
        assert tc.arguments == {"path": "/home/user/notes.md"}
        assert tc.error is None

        # Verify outgoing tools had functionDeclarations
        rec1 = server.requests[0]
        assert rec1.body is not None
        assert "tools" in rec1.body
        func_decls = rec1.body["tools"][0]["functionDeclarations"]
        assert func_decls[0]["name"] == "fs__read"

        # Next turn: tool result
        server.enqueue(ScriptedReply(content="Your notes are empty."))
        req2 = CompletionRequest(
            messages=(
                Message(role="user", content="Read my notes"),
                Message(role="assistant", content="", tool_calls=(tc,)),
                Message(role="tool", content="notes content", tool_call_id="fs.read"),
            ),
            max_tokens=1000,
            tools=tools,
        )
        res2 = await provider.complete(req2)
        assert res2.text == "Your notes are empty."

        rec2 = server.requests[1]
        assert rec2.body is not None
        contents = rec2.body["contents"]
        # Assistant turn contains functionCall
        model_turn = contents[1]
        assert model_turn["role"] == "model"
        assert "functionCall" in model_turn["parts"][0]
        assert model_turn["parts"][0]["functionCall"]["name"] == "fs__read"

        # Tool turn contains functionResponse
        tool_turn = contents[2]
        assert tool_turn["role"] == "user"
        assert "functionResponse" in tool_turn["parts"][0]
        assert tool_turn["parts"][0]["functionResponse"]["name"] == "fs__read"
        assert tool_turn["parts"][0]["functionResponse"]["response"]["output"] == "notes content"
    finally:
        server.close()


# ============================================================================
# PROV-07: Gemini provider_state echoed cleanly
# ============================================================================

async def test_prov_07_gemini_provider_state_roundtrip(http_client: httpx.AsyncClient) -> None:
    state_payload = {"session_token": "gem_tok_987", "cache_id": "cache_456"}
    server = FakeLLMServer([
        ScriptedReply(content="First turn", provider_state=state_payload),
    ])
    server.start()
    try:
        keys = MemoryKeyStore({"test": "gemini-api-key"})
        provider = GeminiProvider(
            client=http_client,
            keys=keys,
            key_ref="test",
            model_id="gemini-1.5-flash",
            base_url=f"{server.gemini_url}",
        )

        req1 = CompletionRequest(messages=(Message(role="user", content="Hello"),), max_tokens=1000)
        res1 = await provider.complete(req1)
        assert res1.provider_state == state_payload

        # Echo provider_state back in next message
        server.enqueue(ScriptedReply(content="Second turn", provider_state=state_payload))
        req2 = CompletionRequest(
            messages=(
                Message(role="user", content="Hello"),
                Message(role="assistant", content="First turn", provider_state=res1.provider_state),
                Message(role="user", content="Follow up"),
            ),
            max_tokens=1000,
        )
        res2 = await provider.complete(req2)
        assert res2.provider_state == state_payload
    finally:
        server.close()


# ============================================================================
# PROV-08: Ollama dialect: tools sent to /api/chat, tool_calls parsed
# ============================================================================

async def test_prov_08_ollama_tool_calls_and_responses(http_client: httpx.AsyncClient) -> None:
    server = FakeLLMServer([
        ScriptedReply(tool_calls=[{"name": "fs__read", "arguments": {"path": "/workspace/ollama_test.py"}}]),
    ])
    server.start()
    try:
        provider = OllamaProvider(
            client=http_client,
            model_id="llama3.1",
            base_url=f"{server.ollama_url}",
        )

        tools = (ToolSchema(name="fs.read", description="Read file", parameters={"type": "object"}),)
        req = CompletionRequest(
            messages=(Message(role="user", content="Read file"),),
            max_tokens=1000,
            tools=tools,
        )

        res = await provider.complete(req)
        assert len(res.tool_calls) == 1
        tc = res.tool_calls[0]
        assert tc.name == "fs.read"
        assert tc.arguments == {"path": "/workspace/ollama_test.py"}
        assert tc.error is None

        # Verify outgoing request had tools formatted
        rec = server.requests[0]
        assert rec.body is not None
        assert "tools" in rec.body
        assert rec.body["tools"][0]["function"]["name"] == "fs__read"

        # Next turn: tool response
        server.enqueue(ScriptedReply(content="Finished reading."))
        req2 = CompletionRequest(
            messages=(
                Message(role="user", content="Read file"),
                Message(role="assistant", content="", tool_calls=(tc,)),
                Message(role="tool", content="print('hello')", tool_call_id=tc.id),
            ),
            max_tokens=1000,
            tools=tools,
        )
        res2 = await provider.complete(req2)
        assert res2.text == "Finished reading."
        assert len(res2.tool_calls) == 0

        # Check recorded message roles in Ollama
        rec2 = server.requests[1]
        assert rec2.body is not None
        msgs = rec2.body["messages"]
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "fs__read"
        assert msgs[2]["role"] == "tool"
        assert msgs[2]["content"] == "print('hello')"
    finally:
        server.close()


# ============================================================================
# PROV-09: Action protocol: fenced JSON, prose, final answer
# ============================================================================

def test_prov_09_action_protocol_parsing() -> None:
    # 1. Fenced JSON with prose
    fenced_text = """
Here is my analysis of your request.
```json
{
  "thought": "I need to check the files in the directory",
  "calls": [
    {"tool": "fs.list", "args": {"path": "/workspace"}}
  ]
}
```
Let me know if you need more.
"""
    thought, calls, valid = parse_protocol_reply(fenced_text)
    assert valid is True
    assert thought == "I need to check the files in the directory"
    assert len(calls) == 1
    assert calls[0].name == "fs.list"
    assert calls[0].arguments == {"path": "/workspace"}
    assert calls[0].error is None

    # 2. Leading/trailing prose without fences
    prose_text = """Sure thing!
{"thought": "Fetch url", "calls": [{"tool": "web.fetch", "args": {"url": "https://example.com"}}]}
Done.
"""
    thought, calls, valid = parse_protocol_reply(prose_text)
    assert valid is True
    assert thought == "Fetch url"
    assert len(calls) == 1
    assert calls[0].name == "web.fetch"
    assert calls[0].arguments == {"url": "https://example.com"}

    # 3. Final answer shape
    final_text = """```json
{"thought": "All steps done", "final": "The answer is 42"}
```"""
    answer, calls, valid = parse_protocol_reply(final_text)
    assert valid is True
    assert answer == "The answer is 42"
    assert len(calls) == 0


# ============================================================================
# PROV-10: Action protocol repair turn and session runtime detection
# ============================================================================

async def test_prov_10_action_protocol_repair_and_detection(http_client: httpx.AsyncClient) -> None:
    reset_detected_protocol()
    model_name = "test-protocol-model"
    assert is_detected_protocol(model_name) is False

    # First attempt: invalid prose, repair attempt: valid protocol JSON
    invalid_reply = "I cannot call tools directly, what should I do?"
    valid_repair_reply = json.dumps({
        "thought": "Now using protocol",
        "calls": [{"tool": "fs.read", "args": {"path": "/file.txt"}}],
    })

    server = FakeLLMServer([
        ScriptedReply(content=invalid_reply),
        ScriptedReply(content=valid_repair_reply),
    ])
    server.start()
    try:
        keys = MemoryKeyStore({"test": "sk-secret"})
        inner = OpenAICompatProvider(
            name="test-openai",
            client=http_client,
            keys=keys,
            key_ref="test",
            model_id=model_name,
            base_url=f"{server.openai_url}",
        )
        adapter = ActionProtocolAdapter(inner, model_name=model_name)

        tools = (ToolSchema(name="fs.read", description="Read file", parameters={"type": "object"}),)
        req = CompletionRequest(
            messages=(Message(role="user", content="Read file"),),
            max_tokens=1000,
            tools=tools,
        )

        res = await adapter.complete(req)
        # Verify repair turn happened
        assert len(server.requests) == 2
        # Second request was repair prompt
        repair_req_recorded = server.requests[1]
        assert repair_req_recorded.messages is not None
        assert any("That reply was not a single valid JSON object" in m.get("content", "")
                   for m in repair_req_recorded.messages)

        # Result parsed from repair
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].name == "fs.read"
        assert res.tool_calls[0].arguments == {"path": "/file.txt"}

        # Detection confirmed for this session
        assert is_detected_protocol(model_name) is True

        # Test session reset
        reset_detected_protocol()
        assert is_detected_protocol(model_name) is False

        # Test mark_detected_protocol directly
        mark_detected_protocol(model_name)
        assert is_detected_protocol(model_name) is True
    finally:
        server.close()
        reset_detected_protocol()


# ============================================================================
# Phase 2 Gate: Identical scripted conversation across all 4 modes
# ============================================================================

async def test_phase_2_gate_identical_conversation_across_all_dialects(http_client: httpx.AsyncClient) -> None:
    """Gate: The same scripted conversation (tool call -> result -> final) passes against the fake server

    in OpenAI, Gemini, Ollama, and Action Protocol modes, with identical ModelToolCall results.
    """
    target_path = "/workspace/test.txt"
    tool_name = "fs.read"
    secret_value = "SECRET=xyzzy123"
    final_answer = "The secret is xyzzy123."

    tools = (
        ToolSchema(
            name=tool_name,
            description="Read a text file.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
    )

    modes = ["openai", "gemini", "ollama", "protocol"]
    results_by_mode: dict[str, tuple[ModelToolCall, str]] = {}

    for mode in modes:
        server = FakeLLMServer()
        if mode == "openai":
            server.enqueue(ScriptedReply(tool_calls=[{"name": "fs__read", "arguments": {"path": target_path}}]))
            server.enqueue(ScriptedReply(content=final_answer))
        elif mode == "gemini":
            server.enqueue(ScriptedReply(tool_calls=[{"name": "fs__read", "arguments": {"path": target_path}}]))
            server.enqueue(ScriptedReply(content=final_answer))
        elif mode == "ollama":
            server.enqueue(ScriptedReply(tool_calls=[{"name": "fs__read", "arguments": {"path": target_path}}]))
            server.enqueue(ScriptedReply(content=final_answer))
        elif mode == "protocol":
            server.enqueue(ScriptedReply(content=json.dumps({
                "thought": "Need to read file",
                "calls": [{"tool": tool_name, "args": {"path": target_path}}],
            })))
            server.enqueue(ScriptedReply(content=json.dumps({
                "thought": "Done",
                "final": final_answer,
            })))

        server.start()
        try:
            keys = MemoryKeyStore({"key": "test-key"})
            provider: Any
            if mode == "openai":
                provider = OpenAICompatProvider(
                    name="openai", client=http_client, keys=keys, key_ref="key",
                    model_id="gpt-4o", base_url=server.openai_url,
                )
            elif mode == "gemini":
                provider = GeminiProvider(
                    client=http_client, keys=keys, key_ref="key",
                    model_id="gemini-1.5-pro", base_url=server.gemini_url,
                )
            elif mode == "ollama":
                provider = OllamaProvider(
                    client=http_client, model_id="qwen2.5", base_url=server.ollama_url,
                )
            elif mode == "protocol":
                inner = OpenAICompatProvider(
                    name="protocol-inner", client=http_client, keys=keys, key_ref="key",
                    model_id="base-model", base_url=server.openai_url,
                )
                provider = ActionProtocolAdapter(inner, model_name="base-model")

            # Turn 1: User asks, model calls tool
            req1 = CompletionRequest(
                messages=(Message(role="user", content=f"Read {target_path} and tell me the secret."),),
                max_tokens=1000,
                tools=tools,
            )
            res1 = await provider.complete(req1)
            assert len(res1.tool_calls) == 1, f"Mode {mode} failed to produce tool call"
            tc1 = res1.tool_calls[0]

            # Turn 2: Tool result provided, model returns final answer
            req2 = CompletionRequest(
                messages=(
                    Message(role="user", content=f"Read {target_path} and tell me the secret."),
                    Message(role="assistant", content=res1.text, tool_calls=(tc1,)),
                    Message(role="tool", content=secret_value, tool_call_id=tc1.id or tc1.name),
                ),
                max_tokens=1000,
                tools=tools,
            )
            res2 = await provider.complete(req2)
            assert len(res2.tool_calls) == 0, f"Mode {mode} should have finished with no tool calls"

            results_by_mode[mode] = (tc1, res2.text)
        finally:
            server.close()

    # Assert identical ModelToolCall structures across all 4 modes!
    first_tc, first_text = results_by_mode["openai"]
    for mode in modes:
        tc, text = results_by_mode[mode]
        assert tc.name == tool_name, f"Mode {mode} tool call name {tc.name} != {tool_name}"
        assert tc.arguments == {"path": target_path}, f"Mode {mode} arguments mismatch"
        assert tc.error is None, f"Mode {mode} had error: {tc.error}"
        assert final_answer in text, f"Mode {mode} final answer mismatch: {text}"
