"""Regression tests proving unexecuted tasks cannot be marked DONE, and verifying intent, discovery, and outcome evaluations for desktop applications."""

from __future__ import annotations

import pytest

from lilly.core.shortlist import discover
from lilly.decide.system1 import DecisionType, System1Engine, System1Request, ToolFamily
from lilly.domain.tasks import TaskOutcome
from lilly.domain.tools_registry import DEFAULT_TOOLS
from lilly.engine.agent_loop import AgentLoop
from lilly.engine.intent import Intent, classify_intent


def test_classify_intent_for_desktop_actions() -> None:
    """Desktop app launching, searching, and interactions must classify as ACTION."""
    assert classify_intent("open spotify on my lap search for harry") is Intent.ACTION
    assert classify_intent("open textedit and type hello") is Intent.ACTION
    assert classify_intent("search for python in spotify") is Intent.ACTION
    assert classify_intent("launch music and play track") is Intent.ACTION
    assert classify_intent("search the web for weather") is Intent.WEB_RETRIEVE


@pytest.mark.asyncio
async def test_system1_tool_family_for_desktop_requests() -> None:
    """System 1 must route desktop app requests to ToolFamily.COMPUTER."""
    engine = System1Engine()
    req = System1Request(
        decision_type=DecisionType.TOOL_FAMILY_SELECTION,
        task_id="test_task_001",
        user_request="open spotify on my lap search for harry",
    )

    decision = await engine.decide(req)
    assert hasattr(decision, "primary_family")
    assert decision.primary_family == ToolFamily.COMPUTER


def test_discover_desktop_app_tools() -> None:
    """Querying for desktop apps or in-app search must return computer control tools."""
    matches = discover(DEFAULT_TOOLS, "Spotify")
    assert "computer.open_app" in matches

    desktop_matches = discover(DEFAULT_TOOLS, "open spotify on my lap search for harry")
    assert "computer.open_app" in desktop_matches
    assert any(m.startswith("computer.") for m in desktop_matches)


def test_evaluate_outcome_refusal_is_blocked() -> None:
    """Admitting lack of direct access or refusing to control apps must be evaluated as BLOCKED, not SUCCESS."""
    loop = object.__new__(AgentLoop)
    loop._goal = "open spotify on my lap search for harry"

    refusal_text = (
        "It seems I don’t have direct access to Spotify or music apps on your computer. "
        "However, I can guide you on how to open Spotify and search for 'Harry' manually if you'd like!"
    )
    outcome, reason, verified = loop._evaluate_outcome(
        refusal_text,
        intent=Intent.ACTION,
        action_performed=False,
        action_verified=False,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert outcome == TaskOutcome.BLOCKED
    assert verified is False
    assert "lack of access" in (reason or "").lower() or "blocked" in (reason or "").lower()


def test_evaluate_outcome_unexecuted_action_is_partial_not_success() -> None:
    """When the user requests an action but no tool action was performed, outcome must be PARTIAL or BLOCKED."""
    loop = object.__new__(AgentLoop)
    loop._goal = "open spotify on my lap search for harry"

    outcome, reason, verified = loop._evaluate_outcome(
        "Here are instructions on how to use Spotify.",
        intent=Intent.ACTION,
        action_performed=False,
        action_verified=False,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert outcome in (TaskOutcome.PARTIAL, TaskOutcome.BLOCKED)
    assert outcome != TaskOutcome.SUCCESS
    assert verified is False


def test_evaluate_outcome_verified_action_is_success() -> None:
    """When an action was performed and verified via fresh frame, outcome is SUCCESS."""
    loop = object.__new__(AgentLoop)
    loop._goal = "open spotify on my lap search for harry"

    outcome, reason, verified = loop._evaluate_outcome(
        "Opened Spotify and searched for Harry.",
        intent=Intent.ACTION,
        action_performed=True,
        action_verified=True,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert outcome == TaskOutcome.SUCCESS
    assert verified is True


def test_evaluate_outcome_navigate_branches() -> None:
    """Navigation intent evaluations for success and failure."""
    loop = object.__new__(AgentLoop)
    loop._goal = "open safari"

    success_outcome, _, v1 = loop._evaluate_outcome(
        "Opened Safari",
        intent=Intent.NAVIGATE,
        action_performed=True,
        action_verified=False,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert success_outcome == TaskOutcome.SUCCESS
    assert v1 is True

    fail_outcome, _, v2 = loop._evaluate_outcome(
        "Could not reach destination",
        intent=Intent.NAVIGATE,
        action_performed=False,
        action_verified=False,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert fail_outcome == TaskOutcome.PARTIAL
    assert v2 is False


def test_evaluate_outcome_goal_asked_action_fallback() -> None:
    """If goal asked for action but intent was answered/retrieved without execution, outcome is PARTIAL."""
    loop = object.__new__(AgentLoop)
    loop._goal = "play some music on spotify"

    outcome, reason, verified = loop._evaluate_outcome(
        "Spotify is a music streaming app.",
        intent=Intent.ANSWER,
        action_performed=False,
        action_verified=False,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert outcome == TaskOutcome.PARTIAL
    assert not verified
    assert "requested action was not executed" in (reason or "")

    # Clarification needed
    q_outcome, _, _ = loop._evaluate_outcome(
        "Would you like me to open Spotify or Apple Music?",
        intent=Intent.ANSWER,
        action_performed=False,
        action_verified=False,
        had_blocked=False,
        had_declined=False,
        had_failed_step=False,
    )
    assert q_outcome == TaskOutcome.NEEDS_USER


@pytest.mark.asyncio
async def test_runner_unexecuted_action_sets_task_failed() -> None:
    """Runner must set final task state to FAILED (never DONE) when action is BLOCKED or PARTIAL."""
    from unittest.mock import AsyncMock, MagicMock

    from lilly.domain.tasks import TaskState
    from lilly.engine.runner import TaskRunner

    runner = object.__new__(TaskRunner)
    runner._task = MagicMock()
    runner._task.id = "task_test_123"
    runner._spec = MagicMock()
    runner._spec.intent = Intent.ACTION
    runner._spec.goal = "open spotify on my lap search for harry"
    runner._rec = MagicMock()
    runner._rec.ctx = MagicMock()
    runner._rec.ctx.label = None
    runner._rec.state_now = TaskState.RUNNING
    runner._rec.state = AsyncMock()
    runner._rec.thought = AsyncMock()
    runner._rec.event = AsyncMock()
    runner._rec.started = 0.0
    runner._rec.models = []
    runner._d = MagicMock()
    runner._d.db = MagicMock()
    runner._d.grounding_settings = MagicMock(return_value=MagicMock(protected_globs=()))
    runner._finish = AsyncMock()
    runner._replies = None

    # When outcome is BLOCKED
    await runner._answer("Cannot access Spotify", outcome=TaskOutcome.BLOCKED, outcome_reason="access blocked")
    runner._finish.assert_called_with(
        TaskState.FAILED,
        answer="Cannot access Spotify",
        error="access blocked",
        outcome=TaskOutcome.BLOCKED,
        outcome_reason="access blocked",
    )

    # When outcome is PARTIAL
    runner._finish.reset_mock()
    await runner._answer("Here is how you can do it", outcome=TaskOutcome.PARTIAL, outcome_reason="not executed")
    runner._finish.assert_called_with(
        TaskState.FAILED,
        answer="Here is how you can do it",
        error="not executed",
        outcome=TaskOutcome.PARTIAL,
        outcome_reason="not executed",
    )

