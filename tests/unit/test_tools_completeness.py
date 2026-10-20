"""Completeness test for tool registry and action classification."""

from __future__ import annotations

from lilly.domain.labels import Risk
from lilly.domain.tools_registry import DEFAULT_TOOLS
from lilly.engine.agent_loop import (
    _ACTION_OBSERVATION_TOOLS,
    _ACTION_TOOLS,
    _ACTION_TOOLS_WITH_FRESH_STATE,
)

# Known mutating tools that modify state on the system, browser, files, or persistent stores
EXPECTED_MUTATING_TOOLS = {
    # File mutations
    "fs.write",
    "fs.edit",
    "fs.apply_moves",
    "fs.trash",
    # Persistent stores
    "notes.write",
    "memory.write",
    # Sandbox / shell execution
    "devbox.run",
    "computer.run",
    "computer.stop_process",
    # Computer control / interaction
    "computer.click",
    "computer.type",
    "computer.press",
    "computer.move",
    "computer.scroll",
    "computer.drag",
    "computer.open_app",
    "computer.open_url",
    "computer.notify",
    # Browser state mutations
    "browser.click",
    "browser.type",
    "browser.select",
    "browser.submit",
    "browser.press",
    "browser.scroll",
    "browser.back",
    "browser.close",
}


def test_every_mutating_tool_is_classified_as_action_tool() -> None:
    """Every mutating tool must be classified in _ACTION_TOOLS so action verification works."""
    for tool_name in EXPECTED_MUTATING_TOOLS:
        assert tool_name in _ACTION_TOOLS, f"Mutating tool {tool_name!r} missing from _ACTION_TOOLS"


def test_all_high_risk_tools_in_registry_are_classified() -> None:
    """Any tool registered with Risk >= R1 must be in _ACTION_TOOLS unless explicitly read-only."""
    for name, spec in DEFAULT_TOOLS.items():
        if spec.risk >= Risk.R1:
            assert name in _ACTION_TOOLS, (
                f"Tool {name!r} has {spec.risk.name} but is not in _ACTION_TOOLS. "
                "Classify whether it is mutating or update the test contract."
            )


def test_action_tools_with_fresh_state_are_subset_of_action_tools() -> None:
    """Tools that return fresh state must be recognized action tools."""
    assert _ACTION_TOOLS_WITH_FRESH_STATE.issubset(_ACTION_TOOLS)


def test_observation_tools_are_registered_and_cover_domains() -> None:
    """Observation tools must exist in DEFAULT_TOOLS and cover file, computer, and browser domains."""
    for name in _ACTION_OBSERVATION_TOOLS:
        assert name in DEFAULT_TOOLS, f"Observation tool {name!r} not in DEFAULT_TOOLS"

    # Must cover files, browser, and desktop domains
    assert any(name.startswith("fs.") for name in _ACTION_OBSERVATION_TOOLS)
    assert any(name.startswith("browser.") for name in _ACTION_OBSERVATION_TOOLS)
    assert any(name.startswith("computer.") for name in _ACTION_OBSERVATION_TOOLS)
