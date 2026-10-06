"""Compatibility helpers for capability discovery and historical decision tests.

The normal AgentLoop exposes the complete policy-filtered catalog. This module is
not an authority for production visibility and cannot remove capabilities.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from lilly.domain.decisions import Option
from lilly.domain.plan import FINAL_TOOL
from lilly.domain.tools_registry import ToolSpec

SHOW_ALL_UP_TO = 25
DEFAULT_K = 10
CONTROL_TOOLS = frozenset({"agent.plan", "agent.ask", "agent.delegate", "agent.discover", "result.read"})


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


def discover(specs: Mapping[str, ToolSpec], query: str, *, namespace: str | None = None,
             limit: int = 12) -> list[str]:
    """Find capabilities in the already policy-filtered catalog."""
    terms = {part for part in query.lower().replace(".", " ").split() if part}
    prefix = namespace.strip().lower() if namespace else ""
    scored: list[tuple[int, str]] = []
    for name, spec in specs.items():
        if name in CONTROL_TOOLS or (prefix and not name.lower().startswith(prefix + ".")):
            continue
        haystack = " ".join((name, spec.doc, spec.module or "")).lower()
        score = sum(3 if term in name.lower() else 1 for term in terms if term in haystack)
        if score:
            scored.append((score, name))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [name for _, name in scored[:max(1, min(limit, 32))]]
