"""The decision layer's vocabulary: what is asked, what may be answered, and how it is configured.

Cheap deciders (rules, a small local model, later an add-on) give advice on narrow questions before the
language model is asked. Safety is built into the shapes below: an Answer or Outcome can only name one of the
options that code offered, or nothing. There is deliberately no field that could say "allow" or "approve",
so nothing in this layer can widen what an agent may do. Policy and approvals never see it.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, Protocol, TypeGuard, runtime_checkable

from lilly.domain.reasoning import redact


class Kind(StrEnum):
    """The only questions a decider can be asked. PLAN, REPLY and ROUTE are Laya assist: off unless switched on."""

    TOOLS = "tools"                  # rank the tools to show the planner
    LOOP = "loop"                    # is this run going round in circles
    INSTRUCTIONS = "instructions"    # does this text read as instructions aimed at the agent
    PICK = "pick"                    # choose one item from a closed list built by code
    PLAN = "plan"                    # does a step that changes something serve what the user asked
    REPLY = "reply"                  # does a finished reply follow what the user asked
    ROUTE = "route"                  # can this request be answered without any tool (saves the tool list's tokens)


# Option ids the callers build for the two yes/no questions.
LOOPING, PROGRESSING = "loop", "progress"
FLAGGED, CLEAN = "yes", "no"
FITS, OFF = "fits", "off"
FOLLOWS, DRIFTS = "follows", "drifts"
DIRECT, NEEDS_TOOLS = "direct", "needs_tools"


@dataclass(frozen=True, slots=True)
class Option:
    """One thing a decider may choose. `id` is the only thing an answer can carry back; `label` is text to
    read or match (a tool's description, an app's display name)."""

    id: str
    label: str = ""


LOOP_OPTIONS = (Option(LOOPING, "the run is repeating itself"), Option(PROGRESSING, "the run is making progress"))
INSTRUCTION_OPTIONS = (Option(FLAGGED, "reads as instructions to the agent"), Option(CLEAN, "ordinary content"))
PLAN_OPTIONS = (Option(FITS, "the step serves the request and respects the instructions"),
                Option(OFF, "the step does not match the request or the instructions"))
REPLY_OPTIONS = (Option(FOLLOWS, "the reply follows the request and the instructions"),
                 Option(DRIFTS, "the reply drifts from the request or the instructions"))
ROUTE_OPTIONS = (Option(DIRECT, "can be answered from general knowledge alone, with nothing to look up or change"),
                 Option(NEEDS_TOOLS, "needs a tool: looking something up, using files or the web, or changing something"))


# ---- what Laya assist is shown ------------------------------------------------------------------------------
# Every part is cut to a fixed size, so the text a decider sees (and a language-free classifier must read) is
# bounded however long the request, the instructions, the arguments or the reply are.
GOAL_CHARS = 600
INSTRUCTION_CHARS = 600
STEP_CHARS = 1200
REPLY_HEAD_CHARS = 900
REPLY_TAIL_CHARS = 600


@dataclass(frozen=True, slots=True)
class Brief:
    """What the user asked for, and the agent's standing instructions: the yardstick a step or a reply is held to."""

    goal: str
    instructions: str = ""


def _head(brief: Brief) -> str:
    instructions = brief.instructions.strip()[:INSTRUCTION_CHARS] or "none"
    return f"Request: {brief.goal.strip()[:GOAL_CHARS]}\nStanding instructions: {instructions}"


def route_state(brief: Brief) -> str:
    """The text for the ROUTE question: just the brief."""
    return _head(brief)


def plan_state(brief: Brief, tool: str, args: Mapping[str, Any]) -> str:
    """The text for the PLAN question: the brief, then the step as its tool and a short redacted argument summary."""
    summary = redact(json.dumps(args, sort_keys=True, separators=(",", ":"), default=str))
    return f"{_head(brief)}\nStep: {f'{tool} {summary}'[:STEP_CHARS]}"


def reply_state(brief: Brief, reply: str) -> str:
    """The text for the REPLY question: the brief, then the reply (all of it when short, else its start and end)."""
    text = reply.strip()
    if len(text) <= REPLY_HEAD_CHARS + REPLY_TAIL_CHARS:
        return f"{_head(brief)}\nReply: {text}"
    return f"{_head(brief)}\nReply start: {text[:REPLY_HEAD_CHARS]}\nReply end: {text[-REPLY_TAIL_CHARS:]}"


@dataclass(frozen=True, slots=True)
class StepSig:
    """What a finished step looked like, for loop detection: the tool and its arguments in canonical form."""

    tool: str
    args: str


def step_sig(tool: str, args: Mapping[str, Any]) -> StepSig:
    """Same tool with the same arguments, however the keys were ordered, gives the same signature."""
    return StepSig(tool, json.dumps(args, sort_keys=True, separators=(",", ":"), default=str))


@dataclass(frozen=True, slots=True)
class Context:
    """What a decider may look at besides the options: the text in question and the recent steps."""

    text: str = ""
    steps: tuple[StepSig, ...] = ()


@dataclass(frozen=True, slots=True)
class Request:
    """One question for one decider. `tokens_left` is what remains of the task's small-model budget and
    `timeout_s` is how long this decider has; an out-of-process decider should pass it on to its worker."""

    kind: Kind
    task_id: str | None
    options: tuple[Option, ...]
    context: Context
    tokens_left: int
    timeout_s: float


@dataclass(frozen=True, slots=True)
class Answer:
    """A decider's advice. `choice` must be the id of an offered option, or the answer is ignored.
    `ranking` orders option ids best first (used by the TOOLS question). `tokens_used` is what a model spent."""

    decider: str
    choice: str | None             # None: the decider had nothing valid to say (its cost still counts)
    confidence: float
    ranking: tuple[str, ...] = ()
    tokens_used: int = 0


@dataclass(frozen=True, slots=True)
class Outcome:
    """What the pipeline hands back. `choice` None means no decision: the caller uses its own safe fallback.
    `decider` is who answered. `log_id` identifies the logged row so the caller can record what happened next."""

    kind: Kind
    choice: str | None = None
    ranking: tuple[str, ...] = ()
    decider: str | None = None
    confidence: float | None = None
    reason: str = ""
    log_id: int | None = None
    would: str | None = None       # watch-only runs: what the decider chose, which nothing may act on


class Decider(Protocol):
    """A cheap decider. It may be slow or fail: the pipeline bounds its time and never trusts its answer."""

    name: str

    async def decide(self, request: Request) -> Answer | None:
        """Answer, or None to abstain. Must not raise for ordinary input."""
        ...


# ---- the log ----------------------------------------------------------------
OUTCOMES = ("accepted", "corrected", "unknown")
SUMMARY_CHARS = 300
_SPACE = re.compile(r"\s+")


def summarise(text: str) -> str:
    """A short redacted stand-in for user text. Full text is never logged."""
    return redact(_SPACE.sub(" ", text).strip())[:SUMMARY_CHARS]


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """One logged decision, including shadow runs and no-decision results."""

    ts: float
    kind: Kind
    task_id: str | None
    decider: str | None
    choice: str | None
    confidence: float | None
    shadow: bool
    options: int
    summary: str
    reason: str
    outcome: str = "unknown"


@runtime_checkable
class Warmable(Protocol):
    """A decider that is slow to get ready and can start getting ready ahead of its first question."""

    def warm(self) -> None:
        """Begin getting ready and return at once. Safe to call again and again."""
        ...


class DecisionSink(Protocol):
    async def record(self, record: DecisionRecord) -> int | None:
        """Keep the record and return its id, or None when it could not be kept. Must not raise."""
        ...


# ---- configuration ----------------------------------------------------------
DECIDERS = frozenset({"search", "loop", "rules", "match", "small_model", "laya"})
# Which deciders make sense for which question. Laya cannot rank tools.
KIND_DECIDERS: Mapping[Kind, frozenset[str]] = {
    Kind.TOOLS: frozenset({"search", "small_model"}),
    Kind.LOOP: frozenset({"loop", "small_model", "laya"}),
    Kind.INSTRUCTIONS: frozenset({"rules", "small_model", "laya"}),
    Kind.PICK: frozenset({"match", "small_model", "laya"}),
    Kind.PLAN: frozenset({"laya", "small_model"}),
    Kind.REPLY: frozenset({"laya", "small_model"}),
    Kind.ROUTE: frozenset({"laya", "small_model"}),
}
DEFAULT_MIN_CONFIDENCE: Mapping[str, float] = {"search": 0.3, "loop": 0.7, "rules": 0.8, "match": 0.85,
                                               "small_model": 0.7, "laya": 0.7}
DEFAULT_TIMEOUT_S: Mapping[str, float] = {"search": 1.0, "loop": 0.5, "rules": 0.5, "match": 0.5,
                                          "small_model": 8.0, "laya": 3.0}
DEFAULT_CHAIN: Mapping[Kind, tuple[str, ...]] = {Kind.TOOLS: ("search",), Kind.LOOP: ("loop",),
                                                 Kind.INSTRUCTIONS: ("rules",), Kind.PICK: ("match",),
                                                 Kind.PLAN: (), Kind.REPLY: (), Kind.ROUTE: ()}   # assist is never asked unless switched on
TIMEOUT_BOUNDS = (0.05, 30.0)
MAX_CHAIN = 4
CAP_BOUNDS = {"max_per_task": (1, 10_000), "max_model_tokens_per_task": (0, 100_000), "min_free_mb": (0, 128_000)}


@dataclass(frozen=True, slots=True)
class ChainStep:
    decider: str
    min_confidence: float
    timeout_s: float


def _step(name: str) -> ChainStep:
    return ChainStep(name, DEFAULT_MIN_CONFIDENCE[name], DEFAULT_TIMEOUT_S[name])


@dataclass(frozen=True, slots=True)
class KindSettings:
    enabled: bool = True
    shadow: bool = False                  # run and log, but tell the caller "no decision"
    chain: tuple[ChainStep, ...] = ()
    min_samples: int = 0
    min_precision: float = 0.8


ASSIST_KINDS = (Kind.PLAN, Kind.REPLY, Kind.ROUTE)


def _default_kinds() -> dict[str, KindSettings]:
    return {k.value: KindSettings(shadow=k in ASSIST_KINDS, chain=tuple(_step(n) for n in DEFAULT_CHAIN[k]))
            for k in Kind}


@dataclass(frozen=True, slots=True)
class DecisionSettings:
    """Defaults are cautious: rules only, no model, nothing that can act."""

    enabled: bool = True                  # master switch: off means every question gets "no decision"
    max_per_task: int = 200               # questions one task may ask
    max_model_tokens_per_task: int = 2000  # small-model tokens one task may spend
    kinds: Mapping[str, KindSettings] = field(default_factory=_default_kinds)
    min_free_mb: int = 1000               # minimum free memory required for Laya to load

    def for_kind(self, kind: Kind) -> KindSettings:
        return self.kinds.get(kind.value, KindSettings(enabled=False))


LAYA_KINDS = (Kind.LOOP, Kind.INSTRUCTIONS, Kind.PICK)


def laya_kinds(d: DecisionSettings) -> tuple[str, ...]:
    """The questions Laya is currently asked, by name."""
    return tuple(k.value for k in LAYA_KINDS if any(s.decider == "laya" for s in d.for_kind(k).chain))


def with_laya(d: DecisionSettings, on: bool) -> DecisionSettings:
    """The settings with Laya added after the other deciders of the questions it can answer, or removed."""
    kinds = dict(d.kinds)
    for kind in LAYA_KINDS:
        mine = kinds[kind.value]
        rest = tuple(s for s in mine.chain if s.decider != "laya")
        chain = (*rest, _step("laya")) if on and len(rest) < MAX_CHAIN else rest
        kinds[kind.value] = replace(mine, chain=chain)
    switched = replace(d, kinds=kinds)
    if not on:       # assist needs Laya: without it, nothing is left asking
        for assist in ASSIST_KINDS:
            switched = with_assist(switched, assist, False, act=False)
    elif not switched.for_kind(Kind.ROUTE).chain:    # saving tokens starts as watch-only, so it is judged before it acts
        switched = with_assist(switched, Kind.ROUTE, True, act=False)
    return switched


def with_assist(d: DecisionSettings, kind: Kind, on: bool, act: bool) -> DecisionSettings:
    """The settings with one Laya assist question switched on (answered by Laya alone) or off (not asked at all).
    Switching on is watch-only, so the answers are logged and nothing acts on them, unless `act` is set."""
    if kind not in ASSIST_KINDS:
        raise ValueError(f"{kind.value} is not a Laya assist question")
    mine = d.for_kind(kind)
    changed = replace(mine, enabled=True, shadow=not act, chain=(_step("laya"),)) if on else replace(mine, chain=())
    return replace(d, kinds={**d.kinds, kind.value: changed})


def _number(raw: object, lo: float, hi: float) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not lo <= raw <= hi:
        return None
    return float(raw)


def _per_decider(raw: object, chain: tuple[str, ...], label: str, bounds: tuple[float, float],
                 defaults: Mapping[str, float], errs: list[str]) -> dict[str, float]:
    given = raw if isinstance(raw, dict) else {}
    if not isinstance(raw, dict):
        errs.append(f"{label} must be an object of decider name to number")
    out = dict(defaults)
    for name, value in given.items():
        if name not in chain:
            errs.append(f"{label}: {name!r} is not in the chain")
        elif (n := _number(value, *bounds)) is None:
            errs.append(f"{label}.{name} must be a number from {bounds[0]:g} to {bounds[1]:g}")
        else:
            out[name] = n
    return out


def _kind(kind: Kind, raw: object, errs: list[str]) -> KindSettings:
    where = f"decisions.{kind.value}"
    if not isinstance(raw, dict):
        errs.append(f"{where} must be an object")
        return KindSettings()
    for key in raw.keys() - {"enabled", "shadow", "chain", "min_confidence", "timeout_s", "min_samples", "min_precision"}:
        errs.append(f"{where}: unknown setting {key!r}")
    flags = {}
    for key, default in (("enabled", True), ("shadow", kind in ASSIST_KINDS)):
        flags[key] = raw.get(key, default)
        if not isinstance(flags[key], bool):
            errs.append(f"{where}.{key} must be true or false")
    min_samples = raw.get("min_samples", 0)
    if not isinstance(min_samples, int) or min_samples < 0 or min_samples > 100_000:
        errs.append(f"{where}.min_samples must be a positive number")
        min_samples = 0
    min_precision = raw.get("min_precision", 0.8)
    if not isinstance(min_precision, (int, float)) or min_precision < 0.0 or min_precision > 1.0:
        errs.append(f"{where}.min_precision must be between 0.0 and 1.0")
        min_precision = 0.8
    names = raw.get("chain", DEFAULT_CHAIN[kind])
    if not isinstance(names, list | tuple) or not all(isinstance(n, str) for n in names):
        errs.append(f"{where}.chain must be a list of decider names")
        return KindSettings()
    chain = tuple(names)
    if len(chain) > MAX_CHAIN or len(set(chain)) != len(chain):
        errs.append(f"{where}.chain must have at most {MAX_CHAIN} different deciders")
    for name in chain:
        if name not in DECIDERS:
            errs.append(f"{where}.chain: unknown decider {name!r}")
        elif name not in KIND_DECIDERS[kind]:
            errs.append(f"{where}.chain: {name!r} cannot answer this question")
    mins = _per_decider(raw.get("min_confidence", {}), chain, f"{where}.min_confidence", (0.0, 1.0),
                        DEFAULT_MIN_CONFIDENCE, errs)
    times = _per_decider(raw.get("timeout_s", {}), chain, f"{where}.timeout_s", TIMEOUT_BOUNDS,
                         DEFAULT_TIMEOUT_S, errs)
    steps = tuple(ChainStep(n, mins[n], times[n]) for n in chain if n in DECIDERS)
    return KindSettings(bool(flags["enabled"]), bool(flags["shadow"]), steps, min_samples=min_samples, min_precision=float(min_precision))


def parse_decisions(raw: object) -> tuple[DecisionSettings | None, list[str]]:
    """Validate the decision settings. Returns (settings, []) or (None, problems); the caller then keeps the
    defaults, exactly as it does for the rest of the settings."""
    if not isinstance(raw, dict):
        return None, ["decisions must be an object"]
    errs: list[str] = []
    known = {k.value for k in Kind} | {"enabled", *CAP_BOUNDS}
    errs += [f"decisions: unknown setting {key!r}" for key in sorted(raw.keys() - known)]
    if not isinstance(raw.get("enabled", True), bool):
        errs.append("decisions.enabled must be true or false")
    caps: dict[str, int] = {}
    for key, (lo, hi) in CAP_BOUNDS.items():
        value = raw.get(key, getattr(DecisionSettings(), key))
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            errs.append(f"decisions.{key} must be a whole number from {lo} to {hi}")
        else:
            caps[key] = value
    kinds = {k.value: _kind(k, raw.get(k.value, {}), errs) for k in Kind}
    if errs:
        return None, errs
    return DecisionSettings(bool(raw.get("enabled", True)), kinds=kinds, **caps), []


def decisions_to_dict(d: DecisionSettings) -> dict[str, Any]:
    out: dict[str, Any] = {"enabled": d.enabled, "max_per_task": d.max_per_task,
                           "max_model_tokens_per_task": d.max_model_tokens_per_task,
                           "min_free_mb": d.min_free_mb}
    for name, k in d.kinds.items():
        out[name] = {"enabled": k.enabled, "shadow": k.shadow, "chain": [s.decider for s in k.chain],
                     "min_confidence": {s.decider: s.min_confidence for s in k.chain},
                     "timeout_s": {s.decider: s.timeout_s for s in k.chain},
                     "min_samples": k.min_samples, "min_precision": k.min_precision}
    return out


def valid_confidence(value: object) -> TypeGuard[float]:
    """A real number from 0 to 1. NaN, infinity, booleans and text all fail."""
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value) \
        and 0.0 <= value <= 1.0
