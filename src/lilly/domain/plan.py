"""Plan validation and the preflight that predicts a verdict for every step before anything runs."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from lilly.domain.labels import Risk, TaskCtx, ToolCall, Verdict
from lilly.domain.policy import PathScope, decide
from lilly.domain.tools_registry import ToolSpec

MAX_STEPS = 12
FINAL_TOOL = "llm.work"
_ID = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
REF = re.compile(r"\$([a-z][a-z0-9_]{0,15})\.output")


def references(value: Any) -> set[str]:
    """Step ids mentioned as `$id.output` anywhere inside an argument value."""
    if isinstance(value, str):
        return set(REF.findall(value))
    if isinstance(value, list):
        return set().union(*(references(v) for v in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(references(v) for v in value.values())) if value else set()
    return set()


def validate_plan(plan: dict[str, Any], known_tools: dict[str, Risk], max_steps: int = MAX_STEPS) -> list[str]:
    """Problems with a plan; empty means valid. Risk always comes from the registry, never from the plan.

    A plan either answers directly (no steps, with an answer) or lists steps that run in order,
    may use earlier results as `$id.output`, and end with llm.work to compose the reply."""
    steps = plan.get("steps")
    if not isinstance(steps, list):
        return ["steps must be a list"]
    if not steps:
        return [] if str(plan.get("answer") or "").strip() else ["plan has no steps and no answer"]
    errs: list[str] = []
    if len(steps) > max_steps:
        errs.append(f"too many steps ({len(steps)} > {max_steps})")
    seen: set[str] = set()
    for i, s in enumerate(steps):
        if not isinstance(s, dict):
            errs.append(f"step {i + 1}: not an object")
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or not _ID.fullmatch(sid):
            errs.append(f"step {i + 1}: id must be lowercase letters, digits or underscore, like s1")
            continue
        if sid in seen:
            errs.append(f"{sid}: duplicate id")
        tool = s.get("tool")
        if tool not in known_tools:
            errs.append(f"{sid}: {tool!r} is not an available tool")
        elif known_tools[tool] is Risk.R3:
            errs.append(f"{sid}: {tool!r} is forbidden")
        if not isinstance(s.get("args", {}), dict):
            errs.append(f"{sid}: args must be an object")
        else:
            for ref in sorted(references(s.get("args", {})) - seen):
                errs.append(f"{sid}: uses ${ref}.output, which is not an earlier step")
        seen.add(sid)
    last = steps[-1]
    if isinstance(last, dict) and last.get("tool") != FINAL_TOOL:
        errs.append(f"the last step must be {FINAL_TOOL}, which writes the reply")
    return errs


@dataclass(frozen=True, slots=True)
class StepVerdict:
    step_id: str
    tool: str
    verdict: Verdict
    reason: str


def call_paths(spec: ToolSpec, args: dict[str, Any]) -> tuple[str, ...]:
    out: list[str] = []
    for a in spec.path_args:
        v = args.get(a)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out += [x for x in v if isinstance(x, str)]
    return tuple(out)


def tool_call(tool: str, spec: ToolSpec, args: dict[str, Any]) -> ToolCall:
    return ToolCall(tool, spec.risk, spec.egress, call_paths(spec, args), spec.reads_label, spec.confirm)


def preflight(plan: dict[str, Any], tools: dict[str, ToolSpec], ctx: TaskCtx, scope: PathScope,
              max_steps: int = MAX_STEPS) -> tuple[list[str], list[StepVerdict]]:
    """The critique layer. Walk the plan in order, carrying label and taint forward, and predict each
    step's verdict. Arguments that depend on earlier results are only known at run time, so the policy
    is checked again on the real arguments; this is the user's preview, not the enforcement."""
    errs = validate_plan(plan, {k: v.risk for k, v in tools.items()}, max_steps)
    if errs:
        return errs, []
    out: list[StepVerdict] = []
    c = ctx
    for st in plan["steps"]:
        spec = tools[st["tool"]]
        args = st.get("args", {})
        literal = {k: v for k, v in args.items() if not references(v)}
        verdict, why = decide(tool_call(st["tool"], spec, literal), c, scope)
        out.append(StepVerdict(st["id"], st["tool"], verdict, why))
        c = c.absorb(spec.reads_label, spec.untrusted)
    return [], out
