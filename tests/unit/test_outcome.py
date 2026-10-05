"""Plain-English error text and the argument helpers shared by the runner, the executor and the scheduler."""
from __future__ import annotations

import pytest

from lilly.domain.errors import ConflictError, LillyError, NoModelAvailable, PolicyDenied, ProviderError, ToolError
from lilly.engine.outcome import StepFailed, clip, describe_error, is_clipped, resolve_refs


def test_errors_are_described_without_leaking_internals() -> None:
    assert describe_error(NoModelAvailable("all busy")) == "No model is available right now: all busy"
    assert "API key" in describe_error(ProviderError(False, status=403))
    assert describe_error(ToolError("it timed out")) == "it timed out"
    assert describe_error(PolicyDenied()) == PolicyDenied.public
    assert describe_error(ConflictError("moved")) == "moved"
    assert describe_error(LillyError()) == LillyError.public
    assert describe_error(KeyError("secret-token")) == "Something went wrong inside Lilly. The details are in the log."


def test_references_are_replaced_inside_text_lists_and_objects() -> None:
    out = {"s1": "ONE", "s2": "TWO"}
    value = {"a": "x $s1.output", "b": ["$s2.output", 3, {"c": "$s1.output$s2.output"}], "n": 5}
    assert resolve_refs(value, out) == {"a": "x ONE", "b": ["TWO", 3, {"c": "ONETWO"}], "n": 5}
    with pytest.raises(StepFailed, match="step s9"):
        resolve_refs(["$s9.output"], out)


def test_long_arguments_are_shortened_for_display_only() -> None:
    shown = clip({"t": "x" * 700, "l": list(range(30)), "k": 4})
    assert shown["t"].endswith("[700 characters]") and shown["k"] == 4
    assert shown["l"][:20] == list(range(20)) and shown["l"][20:] == ["… 10 more items"]


def test_anything_shortened_is_marked_and_detected() -> None:
    assert not is_clipped(clip({"a": ["x"] * 20, "b": "y" * 600, "c": {"d": 1}}))
    assert is_clipped(clip({"a": "y" * 601}))
    assert is_clipped(clip({"a": {"b": [{"c": list(range(21))}]}}))
    assert is_clipped(clip(list(range(500))))
