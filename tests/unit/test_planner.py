"""The planner prompt: stable parts first."""
from __future__ import annotations


def test_the_prompt_starts_with_what_never_changes_so_a_provider_can_cache_it() -> None:
    from lilly.domain.tools_registry import DEFAULT_TOOLS
    from lilly.engine.planner import PlanInputs, build_prompt
    tools = {"web.search": DEFAULT_TOOLS["web.search"], "llm.work": DEFAULT_TOOLS["llm.work"]}
    one = build_prompt(PlanInputs("find cats", tools, [], "be brief", ("/a",)))
    two = build_prompt(PlanInputs("find dogs and then more", tools, [], "other agent", ("/b",)))
    shared = len(__import__("os").path.commonprefix([one, two]))
    assert shared > one.index("Today is") - 1 and one.index("Rules:") == 0 and one.index("Tools:") < one.index("Today is")
