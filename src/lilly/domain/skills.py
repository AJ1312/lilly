"""Skills are hash-pinned data templates. Includes the built-ins."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from lilly.domain.errors import ValidationFailed
from lilly.domain.labels import Risk
from lilly.domain.plan import validate_plan
from lilly.domain.tools_registry import ToolSpec


@dataclass(frozen=True, slots=True)
class Skill:
    """A reusable plan template. Skills are data, hash-pinned, and re-checked against the
    tool registry every time; a skill can never raise a step's risk. Running one needs no planning call."""
    name: str
    version: int
    summary: str
    params: tuple[str, ...]
    steps: tuple[dict[str, Any], ...]
    max_risk: Risk


_PH = re.compile(r"\{(\w+)\}")


def _subst(v: Any, params: dict[str, str]) -> Any:
    if isinstance(v, str):
        def one(m: re.Match[str]) -> str:
            if m.group(1) not in params:
                raise ValidationFailed(f"unknown placeholder {{{m.group(1)}}}")
            return params[m.group(1)]
        return _PH.sub(one, v)          # single pass: substituted values are never re-expanded
    if isinstance(v, list):
        return [_subst(x, params) for x in v]
    if isinstance(v, dict):
        return {k: _subst(x, params) for k, x in v.items()}
    return v


def instantiate(sk: Skill, params: dict[str, str]) -> dict[str, Any]:
    missing, extra = set(sk.params) - set(params), set(params) - set(sk.params)
    if missing or extra:
        raise ValidationFailed(f"{sk.name}: missing {sorted(missing)}, unexpected {sorted(extra)}")
    if not all(isinstance(v, str) for v in params.values()):
        raise ValidationFailed(f"{sk.name}: parameters must be text")
    steps = json.loads(json.dumps(sk.steps))
    return {"skill": f"{sk.name}@{sk.version}", "steps": _subst(steps, params)}


def check_skill(sk: Skill, tools: dict[str, ToolSpec]) -> list[str]:
    try:
        plan = instantiate(sk, {p: "x" for p in sk.params})
    except ValueError as e:
        return [str(e)]
    errs = validate_plan(plan, {k: v.risk for k, v in tools.items()})
    if not errs:
        top = max(tools[st["tool"]].risk for st in plan["steps"])
        if top > sk.max_risk:
            errs.append(f"{sk.name}: uses risk {top.name}, declared {sk.max_risk.name}")
    return errs


def _llm(sid: str, task: str, src: str, expect: str) -> dict[str, Any]:
    return {"id": sid, "tool": "llm.work", "args": {"task": task, "input": src}, "expect": expect}


BUILTIN_SKILLS: dict[str, Skill] = {sk.name: sk for sk in (
    Skill("research", 1, "Search the web, read the best sources and write a cited summary.", ("topic",), (
        {"id": "s1", "tool": "web.search", "args": {"query": "{topic}"}, "expect": "a list of result links"},
        {"id": "s2", "tool": "web.fetch", "args": {"urls": "$s1.output"}, "expect": "page text for the top sources"},
        _llm("s3", "Write a short summary of {topic}. Cite every claim with its source URL and say what is uncertain.",
             "$s2.output", "a cited summary"),
    ), Risk.R0),
    Skill("summarize-docs", 1, "Read a file and summarise it.", ("path",), (
        {"id": "s1", "tool": "fs.read", "args": {"path": "{path}"}, "expect": "the file's text"},
        _llm("s2", "Summarise the key points, decisions and open questions.", "$s1.output", "a summary"),
    ), Risk.R0),
    Skill("data-profile", 1, "Profile a CSV or XLSX file: rows, types, blanks, duplicates and odd values.",
          ("path",), (
        {"id": "s1", "tool": "data.profile", "args": {"path": "{path}"}, "expect": "column statistics"},
        _llm("s2", "Explain the data quality problems found and what to check first.", "$s1.output",
             "a data quality note"),
    ), Risk.R0),
    Skill("file-organizer", 1, "Propose a tidy folder structure, then apply the moves only after you approve.",
          ("folder",), (
        {"id": "s1", "tool": "fs.list", "args": {"path": "{folder}"}, "expect": "the folder listing"},
        _llm("s2", "Propose a tidier structure as a JSON list of moves, each {\"from\": name, \"to\": "
                   "new/relative/path}, using only names from the listing. Never delete anything. Output only the JSON.",
             "$s1.output", "a JSON list of moves"),
        {"id": "s3", "tool": "fs.apply_moves", "args": {"root": "{folder}", "moves": "$s2.output"},
         "expect": "every move applied inside the folder"},
        _llm("s4", "Tell the user briefly what was moved and how to undo it.", "$s3.output", "a short report"),
    ), Risk.R1),
    Skill("resource-hogs", 1, "Find the programs using the most memory and CPU and say which are safe to close.",
          (), (
        {"id": "s1", "tool": "computer.processes", "args": {"limit": 15, "sort": "memory"},
         "expect": "the heaviest programs"},
        {"id": "s2", "tool": "system.stats", "args": {}, "expect": "disk, memory and CPU"},
        _llm("s3", "Explain what is using resources, which programs are normally safe to close and which are not. "
                   "Suggest only; do not act.", "$s1.output $s2.output", "a short report"),
    ), Risk.R0),
    Skill("run-and-explain", 1, "Run one command in a shared folder (you approve it first) and explain the result.",
          ("folder", "command"), (
        {"id": "s1", "tool": "computer.run", "args": {"command": "{command}", "cwd": "{folder}"},
         "expect": "the command's output"},
        _llm("s2", "Explain what the command did, whether it worked, and what to do next.", "$s1.output",
             "a plain explanation"),
    ), Risk.R2),
    Skill("system-health", 1, "Check disk, memory and heavy processes, and suggest cleanups without doing them.",
          (), (
        {"id": "s1", "tool": "system.stats", "args": {}, "expect": "disk, memory and top processes"},
        _llm("s2", "Point out anything unusual and suggest cleanups. Suggest only; do not act.", "$s1.output",
             "a short report"),
    ), Risk.R0),
)}
