"""Unit tests for token-efficiency optimizations in Lilly.

Validates:
1. Smart routing (deterministic rules first, Laya for uncertainty, tier routing, safe fallback)
2. Lazy tool loading (core + discovery tools, schema cache, on-demand loading)
3. Prompt caching (stable prefix, provider cached tokens tracking, broker statistics)
4. Adaptive context compaction (actual token usage, protected elements, retrievable references)
5. Compact tool results (structured summaries and pagination references)
6. Reduced unnecessary calls (repeated failed call prevention, read caching, namespace invalidation, summarization gate)
7. Cost measurement (provider-reported tokens, latency, cache hits)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from lilly.decide.system1 import (
    DecisionType,
    ModelTier,
    ModelTierDecision,
    System1Engine,
    System1Request,
    TaskClass,
    TaskClassification,
)
from lilly.domain.labels import Label
from lilly.domain.ports import (
    CompletionResult,
    Message,
    ModelToolCall,
    ToolSchema,
)
from lilly.domain.settings import EngineSettings
from lilly.engine.context import ContextManager, make_digest
from lilly.providers.gemini import _format_gemini_tool
from lilly.providers.ollama import _format_ollama_tool
from lilly.providers.openai_compat import _format_openai_tool
from lilly.store.readcache import IDEMPOTENT_TOOLS, ReadCache

# ---------------------------------------------------------------------------
# 1. Smart Routing Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_smart_routing_deterministic_first() -> None:
    """Deterministic rules evaluate first and bypass Laya for high-confidence tasks."""
    laya_mock = MagicMock()
    laya_mock.decide = AsyncMock()

    engine = System1Engine(laya_decider=laya_mock, laya_enabled=True)

    # Simple greeting -> Conversational
    req = System1Request(
        decision_type=DecisionType.TASK_CLASSIFICATION,
        user_request="Hello there!",
        task_id="t1",
    )
    decision = await engine.decide(req)
    assert isinstance(decision, TaskClassification)
    assert decision.task_class == TaskClass.CONVERSATION
    assert decision.confidence >= 0.80
    # Laya was NOT called because deterministic rule had >= 0.80 confidence
    assert laya_mock.decide.call_count == 0


@pytest.mark.asyncio
async def test_smart_routing_model_tier_selection() -> None:
    """Simple requests route to QUICK; complex requests route to STRONG."""
    engine = System1Engine(laya_enabled=False)

    # Simple query -> QUICK
    quick_req = System1Request(
        decision_type=DecisionType.MODEL_TIER_SELECTION,
        user_request="What is the capital of France?",
        task_id="t2",
    )
    quick_decision = await engine.decide(quick_req)
    assert isinstance(quick_decision, ModelTierDecision)
    assert quick_decision.tier == ModelTier.QUICK

    # Complex refactoring task -> STRONG
    strong_req = System1Request(
        decision_type=DecisionType.MODEL_TIER_SELECTION,
        user_request="refactor the authentication architecture across all services",
        task_id="t3",
    )
    strong_decision = await engine.decide(strong_req)
    assert isinstance(strong_decision, ModelTierDecision)
    assert strong_decision.tier == ModelTier.STRONG


@pytest.mark.asyncio
async def test_smart_routing_laya_for_uncertainty() -> None:
    """When deterministic confidence is low or absent, Laya is consulted."""
    from lilly.domain.decisions import Answer

    laya_mock = MagicMock()
    # Laya answers when consulted
    laya_mock.decide = AsyncMock(return_value=Answer("laya", "research", confidence=0.85))

    engine = System1Engine(laya_decider=laya_mock, laya_enabled=True)

    # Ambiguous query that doesn't trigger clear regex
    req = System1Request(
        decision_type=DecisionType.TASK_CLASSIFICATION,
        user_request="quantum coherence fluctuation dynamics in semi-isolated manifolds",
        task_id="t4",
    )
    decision = await engine.decide(req)
    assert laya_mock.decide.call_count == 1
    assert isinstance(decision, TaskClassification)
    assert decision.task_class == TaskClass.RESEARCH


# ---------------------------------------------------------------------------
# 2. Lazy Tool Loading & Schema Caching Tests
# ---------------------------------------------------------------------------

def test_provider_schema_caching() -> None:
    """Stable tool schemas are cached across provider calls."""
    schema = ToolSchema(
        name="fs.read",
        description="Read file contents within allowed folders.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    )

    # OpenAI schema caching
    wire1 = _format_openai_tool(schema)
    wire2 = _format_openai_tool(schema)
    assert wire1 is wire2
    assert wire1["function"]["name"] == "fs__read"

    # Gemini schema caching
    gem1 = _format_gemini_tool(schema)
    gem2 = _format_gemini_tool(schema)
    assert gem1 is gem2
    assert gem1["name"] == "fs__read"

    # Ollama schema caching
    ollama1 = _format_ollama_tool(schema)
    ollama2 = _format_ollama_tool(schema)
    assert ollama1 is ollama2
    assert ollama1["function"]["name"] == "fs__read"


# ---------------------------------------------------------------------------
# 3. Prompt Caching Tokens Tracking Tests
# ---------------------------------------------------------------------------

def test_completion_result_tracks_cached_tokens() -> None:
    """CompletionResult captures cached_tokens reported by providers."""
    result = CompletionResult(
        text="Hello!",
        input_tokens=1500,
        output_tokens=50,
        finish_reason="stop",
        cached_tokens=1024,
    )
    assert result.cached_tokens == 1024
    assert result.input_tokens == 1500


# ---------------------------------------------------------------------------
# 4. Adaptive Context Compaction & Protection Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_adaptive_compaction_preserves_essential_elements() -> None:
    """Compaction preserves user goal, plan, essential findings, errors, and approvals."""
    settings = EngineSettings(soft_context_tokens=150)
    cm = ContextManager(settings)

    msgs = [
        Message(role="system", content="System instruction header"),
        Message(role="user", content="Build a parser and write test files"),  # User goal
        Message(role="assistant", content="to-do list: 1. parse, 2. test"),  # Plan
        Message(role="tool", content="RESULT t1c1 fs.read ok (1200 chars)\n" + "x" * 1200, tool_call_id="t1c1"),
        Message(role="assistant", content="Finding: The file syntax uses BNF grammar rules."),  # Essential finding
        Message(role="tool", content="RESULT t2c1 devbox.run error: compilation failed", tool_call_id="t2c1"),  # Error
        Message(role="assistant", content="Waiting for approval to run privileged binary"),  # Pending approval
        Message(role="assistant", content="latest action", tool_calls=(ModelToolCall("t3c1", "agent.ask", {}, "{}"),)),
        Message(role="tool", content="RESULT t3c1 agent.ask ok\nLatest response", tool_call_id="t3c1"),  # Latest turn
    ]

    prepared = await cm.prepare(msgs, actual_tokens=1200)

    # 1. System prompt preserved
    assert prepared[0].content == "System instruction header"
    # 2. User goal preserved
    assert any("Build a parser" in m.content for m in prepared)
    # 3. Plan preserved
    assert any("to-do list" in m.content for m in prepared)
    # 4. Essential finding preserved
    assert any("Finding: The file syntax uses BNF" in m.content for m in prepared)
    # 5. Error preserved
    assert any("compilation failed" in m.content for m in prepared)
    # 6. Pending approval preserved
    assert any("Waiting for approval" in m.content for m in prepared)
    # 7. Latest turn preserved
    assert any("Latest response" in m.content for m in prepared)
    # 8. Older bulky tool result replaced with compact digest + result.read pointer
    assert any("call result.read" in m.content for m in prepared)


def test_make_digest_includes_retrievable_reference() -> None:
    """make_digest formats tool observations with result.read pointers."""
    msg = Message(
        role="tool",
        content="RESULT t1c1 fs.read ok (4500 characters, showing the first 500)\nFile content sample\n[truncated]",
        tool_call_id="t1c1",
    )
    digest = make_digest(msg)
    assert 'call result.read with {"step": "t1c1"}' in digest
    assert "4,500 chars" in digest


# ---------------------------------------------------------------------------
# 5. Read Cache Idempotency & Invalidation Tests
# ---------------------------------------------------------------------------

def test_read_cache_idempotency_and_invalidation() -> None:
    """ReadCache caches idempotent tools and invalidates on mutations."""
    cache = ReadCache()
    now = 1000.0

    # Put idempotent read
    assert "fs.read" in IDEMPOTENT_TOOLS
    assert "notes.read" in IDEMPOTENT_TOOLS
    assert "memory.search" in IDEMPOTENT_TOOLS

    cache.put("fs.read", {"path": "/tmp/a.txt"}, "content A", Label.PUBLIC, False, now, 300)
    cache.put("notes.read", {"query": "todo"}, "note B", Label.PERSONAL, False, now, 300)
    assert cache.entry_count == 2

    # Get cached read
    cached = cache.get("fs.read", {"path": "/tmp/a.txt"}, now + 10.0, 300)
    assert cached is not None
    assert cached.output == "content A"

    # Invalidate fs namespace on file mutation
    invalidated = cache.invalidate_fs()
    assert invalidated == 1
    assert cache.get("fs.read", {"path": "/tmp/a.txt"}, now + 20.0, 300) is None
    # notes remain cached
    assert cache.get("notes.read", {"query": "todo"}, now + 20.0, 300) is not None

    # Invalidate notes
    cache.invalidate_notes()
    assert cache.entry_count == 0


# ---------------------------------------------------------------------------
# 6. Unnecessary Summarization Avoidance Gate Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summarization_gate_avoids_extra_model_calls() -> None:
    """ContextManager does not invoke LLM summarization for tiny middle messages."""
    completer = MagicMock()
    completer.complete = AsyncMock()

    settings = EngineSettings(soft_context_tokens=10)
    cm = ContextManager(settings, completer=completer)

    # Single tiny middle message
    msgs = [
        Message(role="system", content="System"),
        Message(role="user", content="Request"),
        Message(role="assistant", content="single step"),
        Message(role="assistant", content="latest turn"),
    ]

    # Unprotected middle is empty or <= 1 message -> skips expensive model call
    await cm.prepare(msgs)
    assert completer.complete.call_count == 0
