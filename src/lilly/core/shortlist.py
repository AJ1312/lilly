"""Which tools the planner is shown. A long tool list costs prompt space and invites wrong picks."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from lilly.domain.decisions import Option
from lilly.domain.plan import FINAL_TOOL
from lilly.domain.tools_registry import ToolSpec

SHOW_ALL_UP_TO = 25
DEFAULT_K = 10
CONTROL_TOOLS = frozenset({"agent.plan", "agent.ask", "agent.delegate", "result.read"})


def tool_options(specs: Mapping[str, ToolSpec]) -> tuple[Option, ...]:
    """The closed list a TOOLS question is asked about: each tool's name, with its description and arguments."""
    return tuple(Option(name, f"{spec.doc} {spec.args}") for name, spec in specs.items())


def shortlist(specs: Mapping[str, ToolSpec], ranking: Sequence[str] = (), k: int = DEFAULT_K) -> list[str]:
    """Tool names to show, best first. `ranking` is the decision pipeline's advice (empty when it made none).

    A small catalog, or no advice, shows everything: advice never hides tools from a catalog that is cheap
    to show. Otherwise the top `k` by ranking, padded in catalog order when the advice named fewer, and
    always the final-answer tool and control tools, which are always included.
    """
    names = list(specs)
    always = [n for n in (FINAL_TOOL, *sorted(CONTROL_TOOLS)) if n in specs]
    ranked = [n for n in dict.fromkeys(ranking) if n in specs and n not in always]
    if len(names) <= SHOW_ALL_UP_TO or not ranked:
        return names
    rest = [n for n in names if n not in ranked and n not in always]
    chosen = (ranked + rest)[:k]
    return chosen + always
