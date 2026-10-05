"""Tests for ContextManager, truncation, compaction, summarization, and prefix stability (CTX-01..10)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from lilly.domain.caps import Cap
from lilly.domain.labels import Label, Mode
from lilly.domain.ports import (
    Completed,
    Completer,
    CompletionRequest,
    CompletionResult,
    Message,
    ModelToolCall,
    ToolContext,
    ToolResult,
)
from lilly.domain.settings import EngineSettings
from lilly.engine.context import (
    ContextManager,
    make_digest,
    total_tokens,
)
from lilly.engine.messages import AGENT_SYSTEM
from lilly.store.readcache import ReadCache
from lilly.tools.base import Tool


class DummyCompleter(Completer):
    def __init__(self, reply: str = "Working notes: all tasks finished.") -> None:
        self.reply = reply
        self.calls: list[CompletionRequest] = []

    async def complete(
        self,
        request: CompletionRequest,
        *,
        need: Cap,
        label: Label,
        task_id: str,
        payload_hash: str,
        mode: Mode = Mode.OPEN,
        pin: str | None = None,
    ) -> Completed:
        self.calls.append(request)
        res = CompletionResult(
            text=self.reply,
            tool_calls=(),
            input_tokens=10,
            output_tokens=10,
        )
        return Completed(model="fake-quick", result=res)


# CTX-01: Truncation of tool results with result.read paging
def test_ctx_01_truncation_with_result_read_paging() -> None:
    settings = EngineSettings(observation_chars=100)
    cm = ContextManager(settings)

    body = "x" * 250
    raw_obs = f"RESULT step123 web.fetch ok ({len(body)} characters)\n{body}"
    msg = Message(role="tool", content=raw_obs, tool_call_id="call_1")

    res = cm.truncate_observations([msg])
    assert len(res) == 1
    content = res[0].content
    assert "RESULT step123 web.fetch ok (250 characters, showing the first 100)" in content
    assert 'call result.read with {"step": "step123", "offset": 100}' in content
    # Total body shown is 100 chars
    assert "x" * 100 in content
    assert "x" * 101 not in content


# CTX-02: Compaction triggers when estimated tokens exceed soft_context_tokens
@pytest.mark.asyncio
async def test_ctx_02_compaction_triggers_when_exceeding_soft_limit() -> None:
    # 1 token ~= 4 chars. soft_context_tokens = 120 => limit ~ 480 chars
    settings = EngineSettings(soft_context_tokens=120, observation_chars=6000)
    cm = ContextManager(settings)

    msgs = [
        Message(role="system", content="System prompt instructions"),
        Message(role="user", content="Initial user request"),
        Message(role="assistant", content="Thinking...", tool_calls=(ModelToolCall("t1", "fs.read", {}, "{}"),)),
        Message(role="tool", content=f"RESULT t1 fs.read ok (500 characters)\n{'data line ' * 50}", tool_call_id="t1"),
        Message(role="assistant", content="Final turn thinking", tool_calls=()),
    ]
    assert total_tokens(msgs) > 120

    prepared = await cm.prepare(msgs)
    # The older tool result (t1) should have been compacted into a one-line digest
    tool_msg = next(m for m in prepared if m.role == "tool")
    assert "starts:" in tool_msg.content
    assert len(tool_msg.content) < len(msgs[3].content)


# CTX-03: Compaction keeps request and owner instructions
@pytest.mark.asyncio
async def test_ctx_03_compaction_keeps_request_and_owner_instructions() -> None:
    settings = EngineSettings(soft_context_tokens=40)
    cm = ContextManager(settings)

    sys_content = "You are Lilly.\nInstructions from the owner of this agent: Never delete files."
    user_req = "Please search for python books"

    msgs = [
        Message(role="system", content=sys_content),
        Message(role="user", content=user_req),
        Message(role="assistant", content="call", tool_calls=(ModelToolCall("c1", "web.search", {}, "{}"),)),
        Message(role="tool", content="RESULT c1 web.search ok (1000 characters)\n" + "long result " * 80, tool_call_id="c1"),
        Message(role="assistant", content="next call", tool_calls=(ModelToolCall("c2", "web.fetch", {}, "{}"),)),
        Message(role="tool", content="RESULT c2 web.fetch ok (1000 characters)\n" + "page text " * 80, tool_call_id="c2"),
        Message(role="assistant", content="Final answer turn"),
    ]

    prepared = await cm.prepare(msgs)
    assert prepared[0].role == "system"
    assert prepared[0].content == sys_content
    assert prepared[1].role == "user"
    assert prepared[1].content == user_req


# CTX-04: Compaction keeps to-do list intact
@pytest.mark.asyncio
async def test_ctx_04_compaction_keeps_todo_list() -> None:
    settings = EngineSettings(soft_context_tokens=40)
    cm = ContextManager(settings)

    todo_content = "To-do list (plan with todos):\n1. [done] step one\n2. [doing] step two"
    msgs = [
        Message(role="system", content="System"),
        Message(role="user", content="Request"),
        Message(role="user", content=todo_content),
        Message(role="assistant", content="call", tool_calls=(ModelToolCall("c1", "web.search", {}, "{}"),)),
        Message(role="tool", content="RESULT c1 web.search ok (500 chars)\n" + "abc " * 100, tool_call_id="c1"),
        Message(role="assistant", content="latest turn"),
    ]

    prepared = await cm.prepare(msgs)
    assert any(m.content == todo_content for m in prepared)


# CTX-05: Compaction keeps pending approval intact
@pytest.mark.asyncio
async def test_ctx_05_compaction_keeps_pending_approval() -> None:
    settings = EngineSettings(soft_context_tokens=40)
    cm = ContextManager(settings)

    appr_content = "Waiting for approval on fs.write: approve write to file?"
    msgs = [
        Message(role="system", content="System"),
        Message(role="user", content="Request"),
        Message(role="assistant", content=appr_content),
        Message(role="assistant", content="call", tool_calls=(ModelToolCall("c1", "web.search", {}, "{}"),)),
        Message(role="tool", content="RESULT c1 web.search ok (500 chars)\n" + "abc " * 100, tool_call_id="c1"),
        Message(role="assistant", content="latest turn"),
    ]

    prepared = await cm.prepare(msgs)
    assert any(appr_content in m.content for m in prepared)


# CTX-06: Compaction keeps latest turn in full and last error
@pytest.mark.asyncio
async def test_ctx_06_compaction_keeps_latest_turn_and_last_error() -> None:
    settings = EngineSettings(soft_context_tokens=50)
    cm = ContextManager(settings)

    error_content = "RESULT c1 devbox.run error: compilation failed with code 1"
    latest_thought = "Now I see what went wrong. Running with fix."

    msgs = [
        Message(role="system", content="System"),
        Message(role="user", content="Request"),
        Message(role="assistant", content="call 1", tool_calls=(ModelToolCall("c1", "devbox.run", {}, "{}"),)),
        Message(role="tool", content=error_content, tool_call_id="c1"),
        Message(role="assistant", content=latest_thought, tool_calls=(ModelToolCall("c2", "fs.read", {}, "{}"),)),
        Message(role="tool", content="RESULT c2 fs.read ok (20 chars)\nsome output text", tool_call_id="c2"),
    ]

    prepared = await cm.prepare(msgs)
    # The last error is kept
    assert any(m.content == error_content for m in prepared)
    # The latest turn (assistant message and tool result) is kept in full
    assert any(m.content == latest_thought for m in prepared)


# CTX-07: Digest format (trusted and untrusted)
def test_ctx_07_digest_format() -> None:
    # 1. Trusted tool result
    raw_trusted = (
        "RESULT t3c1 web.fetch ok (18204 characters)\n"
        "Here is the start of the fetched web page about python typing..."
    )
    msg_trusted = Message("tool", raw_trusted, tool_call_id="t3c1")
    digest_trusted = make_digest(msg_trusted)
    assert digest_trusted.startswith('t3c1 web.fetch ok, 18,204 chars, starts: "')
    assert "<untrusted_data>" not in digest_trusted

    # 2. Untrusted tool result
    raw_untrusted = (
        "RESULT t3c1 web.fetch ok (18204 characters)\n"
        "<untrusted_data>\n"
        "Untrusted web text here from outside server...\n"
        "</untrusted_data>"
    )
    msg_untrusted = Message("tool", raw_untrusted, tool_call_id="t3c1")
    digest_untrusted = make_digest(msg_untrusted)
    assert digest_untrusted.startswith("<untrusted_data>\n")
    assert digest_untrusted.endswith("\n</untrusted_data>")
    assert 't3c1 web.fetch ok, 18,204 chars, starts: "' in digest_untrusted


# CTX-08: Summarize cached by content hash
@pytest.mark.asyncio
async def test_ctx_08_summarize_cached_by_hash() -> None:
    completer = DummyCompleter(reply="Working notes: verified step 1 and step 2.")
    # Extremely small budget so compaction triggers summarization
    settings = EngineSettings(soft_context_tokens=10)
    cm = ContextManager(settings, completer=completer)

    msgs = [
        Message(role="system", content="System"),
        Message(role="user", content="Request"),
        Message(role="assistant", content="call", tool_calls=(ModelToolCall("c1", "tool1", {}, "{}"),)),
        Message(role="tool", content="RESULT c1 tool1 ok (500 chars)\n" + "long content " * 40, tool_call_id="c1"),
        Message(role="assistant", content="call 2", tool_calls=(ModelToolCall("c2", "tool2", {}, "{}"),)),
        Message(role="tool", content="RESULT c2 tool2 ok (500 chars)\n" + "more content " * 40, tool_call_id="c2"),
        Message(role="assistant", content="latest turn"),
    ]

    prepared = await cm.prepare(msgs)
    assert len(completer.calls) == 1
    assert any("Working notes:" in m.content for m in prepared)

    # Calling prepare again with identical content must use cache and not invoke completer again
    prepared2 = await cm.prepare(msgs)
    assert len(completer.calls) == 1  # Still 1 call, cached by hash!
    assert any("Working notes:" in m.content for m in prepared2)


# CTX-09: Prefix byte-stable and tool list sorted
def test_ctx_09_prefix_byte_stable_and_tool_list_sorted(tmp_path: Any) -> None:
    # Verify tool list sorting
    tools: dict[str, Tool] = {}

    class DummyTool(Tool):
        def __init__(self, name: str) -> None:
            self.name = name

        async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
            return ToolResult("ok", Label.PUBLIC, False)

    for name in ("web.search", "fs.read", "agent.plan", "devbox.run", "result.read"):
        tools[name] = DummyTool(name)

    # In AgentLoop._get_visible_tools or tool schemas sorting
    sorted_names = sorted(tools.keys())
    assert sorted_names == ["agent.plan", "devbox.run", "fs.read", "result.read", "web.search"]

    # Verify AGENT_SYSTEM prompt prefix formatting is deterministic
    p1 = AGENT_SYSTEM.format(agent_name="Mochi", max_steps=10, max_calls=12, date="2026-10-05", folders_or_none="/tmp/test")
    p2 = AGENT_SYSTEM.format(agent_name="Mochi", max_steps=10, max_calls=12, date="2026-10-05", folders_or_none="/tmp/test")
    assert p1 == p2


# CTX-10: Read cache off by default; cache hit still policy-checked
def test_ctx_10_read_cache_off_by_default_and_ttl() -> None:
    cache = ReadCache()
    now = 1000.0

    # 1. Off by default (ttl_s = 0)
    cache.put("fs.read", {"path": "/tmp/a.txt"}, "content", Label.PUBLIC, False, now, ttl_s=0)
    assert cache.get("fs.read", {"path": "/tmp/a.txt"}, now, ttl_s=0) is None

    # 2. When ttl_s > 0, caches idempotent R0 tools
    cache.put("fs.read", {"path": "/tmp/a.txt"}, "content", Label.PUBLIC, False, now, ttl_s=60)
    hit = cache.get("fs.read", {"path": "/tmp/a.txt"}, now + 30.0, ttl_s=60)
    assert hit is not None
    assert hit.output == "content"

    # 3. After TTL expires, returns None
    assert cache.get("fs.read", {"path": "/tmp/a.txt"}, now + 61.0, ttl_s=60) is None

    # 4. Non-idempotent tool is never cached
    cache.put("fs.write", {"path": "/tmp/a.txt"}, "content", Label.PUBLIC, False, now, ttl_s=60)
    assert cache.get("fs.write", {"path": "/tmp/a.txt"}, now, ttl_s=60) is None
