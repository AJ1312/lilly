"""The rule-based deciders: fast, free, deterministic. Each answers one kind of question or abstains."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from lilly.core.lexical import score
from lilly.domain.decisions import (
    CLEAN,
    DIRECT,
    DRIFTS,
    FITS,
    FLAGGED,
    FOLLOWS,
    LOOPING,
    NEEDS_TOOLS,
    OFF,
    PROGRESSING,
    Answer,
    Kind,
    Request,
    StepSig,
)


class SearchRanker:
    """TOOLS: order the offered tools by how well their name, description and arguments match the goal.
    Confidence is the share of the goal's words that match any tool at all, so a goal in unfamiliar words
    abstains and the caller shows the whole catalog."""

    name = "search"

    async def decide(self, request: Request) -> Answer | None:
        if request.kind is not Kind.TOOLS:
            return None
        scored = score(request.context.text, {o.id: f"{o.id} {o.label}" for o in request.options})
        ranking = sorted((o.id for o in request.options), key=lambda i: -scored.scores[i])  # stable: ties keep order
        if not ranking or scored.scores[ranking[0]] <= 0:
            return None
        return Answer(self.name, ranking[0], scored.coverage, tuple(ranking))


# ---- loops ------------------------------------------------------------------
SAME_STEP_LIMIT = 3     # the same call this many times in a row is a loop
CYCLE_LIMIT = 2         # A, B, A, B: two full turns of a two-step cycle


def _same_run(steps: tuple[StepSig, ...]) -> int:
    n = 0
    for s in reversed(steps):
        if s != steps[-1]:
            break
        n += 1
    return n


def _cycle_turns(steps: tuple[StepSig, ...]) -> int:
    """How many times the last two different steps have alternated (A, B, A, B is two), counting from the end."""
    if len(steps) < 2 or steps[-1] == steps[-2]:
        return 0
    pair, turns = steps[-2:], 0
    while len(steps) >= 2 * (turns + 1) and steps[len(steps) - 2 * (turns + 1):] == pair * (turns + 1):
        turns += 1
    return turns


class LoopRule:
    """LOOP: the same tool with the same arguments repeated, or two calls alternating. Always answers, because
    "no loop seen" is as useful as "loop": silence would make the caller stop and ask."""

    name = "loop"

    async def decide(self, request: Request) -> Answer | None:
        if request.kind is not Kind.LOOP:
            return None
        steps = request.context.steps
        if (same := _same_run(steps)) >= SAME_STEP_LIMIT:
            return Answer(self.name, LOOPING, min(0.99, 0.6 + 0.15 * (same - 2)))
        if (turns := _cycle_turns(steps)) >= CYCLE_LIMIT:
            return Answer(self.name, LOOPING, min(0.99, 0.55 + 0.2 * (turns - 1)))
        return Answer(self.name, PROGRESSING, 0.9)


# ---- instructions aimed at the agent ----------------------------------------
_FLAGS = re.IGNORECASE | re.MULTILINE
_STRONG = tuple(re.compile(p, _FLAGS) for p in (
    r"\b(?:ignore|disregard|forget|override)\b[^.\n]{0,30}\b(?:previous|prior|above|earlier|all|any|your|the)\b"
    r"[^.\n]{0,30}\b(?:instructions?|prompts?|rules|directions|guidelines)\b",
    r"\b(?:reveal|print|show|repeat|output|leak)\b[^.\n]{0,20}\b(?:your|the)\b[^.\n]{0,10}\bsystem prompt\b",
    r"\bnew instructions?\s*:",
    r"\b(?:do not|don't|never|without)\b[^.\n]{0,15}\b(?:tell|inform|mention|alert|notify)\w*[^.\n]{0,15}\bthe user\b",
    r"<\|?(?:im_start|system|assistant)\|?>|\[/?(?:INST|SYSTEM)\]",
))
_WEAK = tuple(re.compile(p, _FLAGS) for p in (
    r"\bsystem prompt\b",
    r"\byou (?:must|will|should) now\b|\bfrom now on,? you\b",
    r"\byou are now\b|\bact as\b|\bpretend (?:to be|you are)\b",
    r"^\s*(?:system|assistant|developer)\s*:",
    r"^\s*#{1,3}\s*(?:system|instructions?)\b",
))
_AGENT_CUE = re.compile(r"\b(?:as an? (?:ai|assistant|agent)|you(?:'re| are) (?:an? )?(?:ai|assistant|agent|llm)"
                        r"|ai (?:assistant|agent)|llm|language model|lilly)\b", re.IGNORECASE)
_INVISIBLE = dict.fromkeys([0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF, 0x00AD])   # zero-width and soft hyphen
MAX_SCANNED = 20_000


class InstructionRules:
    """INSTRUCTIONS: patterns for text that tries to give orders to an AI. One strong pattern is enough. Weak
    ones (plain phrases an ordinary document can contain) need company: a second weak one or a mention of
    an AI. A clean scan answers "no" with low confidence, so a later decider can still look."""

    name = "rules"

    async def decide(self, request: Request) -> Answer | None:
        if request.kind is not Kind.INSTRUCTIONS:
            return None
        text = unicodedata.normalize("NFKC", request.context.text[:MAX_SCANNED]).translate(_INVISIBLE)
        if any(p.search(text) for p in _STRONG):
            return Answer(self.name, FLAGGED, 0.92)
        weak = sum(bool(p.search(text)) for p in _WEAK)
        if weak and _AGENT_CUE.search(text):
            return Answer(self.name, FLAGGED, 0.85)
        if weak >= 2:
            return Answer(self.name, FLAGGED, 0.8)
        return Answer(self.name, FLAGGED, 0.6) if weak else Answer(self.name, CLEAN, 0.6)


# ---- picking from a closed list ---------------------------------------------
FUZZY_FLOOR = 0.75      # below this similarity nothing is close enough
FUZZY_MARGIN = 0.1      # the best must beat the runner-up by this much, or the match is ambiguous
_SYMBOLS = re.compile(r"[\W_]+")


def _squash(text: str) -> str:
    return _SYMBOLS.sub("", text.casefold())


def _similarity(squashed: str, name: str) -> float:
    return SequenceMatcher(None, squashed, _squash(name)).ratio()


class MatchRule:
    """PICK: find the offered option the person's words mean. Exact, then ignoring case and punctuation, then a
    close spelling. Two options that fit equally well mean abstaining, never guessing."""

    name = "match"

    async def decide(self, request: Request) -> Answer | None:
        if request.kind is not Kind.PICK or not (wanted := request.context.text.strip()):
            return None
        if exact := [o.id for o in request.options if wanted in (o.label, o.id)]:
            return Answer(self.name, exact[0], 1.0) if len(exact) == 1 else None
        loose = _squash(wanted)
        if not loose:
            return None
        if hits := [o.id for o in request.options if loose in (_squash(o.label), _squash(o.id))]:
            return Answer(self.name, hits[0], 0.97) if len(hits) == 1 else None
        ratios = sorted(((max(_similarity(loose, o.label), _similarity(loose, o.id)), o.id) for o in request.options),
                        key=lambda t: -t[0])
        if not ratios or ratios[0][0] < FUZZY_FLOOR:
            return None
        if len(ratios) > 1 and ratios[0][0] - ratios[1][0] < FUZZY_MARGIN:
            return None
        return Answer(self.name, ratios[0][1], min(0.95, ratios[0][0]))


# ---- routing: direct conversation vs tool usage -----------------------------
_TOOL_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\b(?:search|google|lookup|browse|fetch|download|curl|scrape|website|url|http|https)\b",
    r"\b(?:file|files|folder|directory|path|read|write|save|edit|delete|rm|mv|cp|create|make a file)\b",
    r"\b(?:terminal|bash|shell|command|exec|execute|run|install|pip|npm|brew|docker|devbox)\b",
    r"\b(?:screenshot|browser|click|type|mouse|navigate|webpage)\b",
    r"\b(?:remember|memory|note|notes|recall)\b",
    r"\.(?:py|js|ts|tsx|jsx|json|md|txt|html|css|yaml|yml|sh|toml)\b",
))

_DIRECT_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"^(?:hi|hello|hey|greetings|good\s+(?:morning|afternoon|evening))\b",
    r"^(?:who|what) are you\b",
    r"\b(?:what is|who is|explain|define|tell me about|how does|why does|difference between)\b",
    r"\b(?:write a poem|write a joke|tell me a joke|write a story|summarize this text:)\b",
    r"^(?:calculate|compute|solve|\d+\s*[\+\-\*\/]\s*\d+)\b",
))


class RouteRule:
    """ROUTE: whether a goal is direct conversation/knowledge (DIRECT) or needs tools (NEEDS_TOOLS)."""

    name = "rules"

    async def decide(self, request: Request) -> Answer | None:
        if request.kind is not Kind.ROUTE or not request.context.text.strip():
            return None
        text = request.context.text.strip()
        has_tool = any(p.search(text) for p in _TOOL_PATTERNS)
        has_direct = any(p.search(text) for p in _DIRECT_PATTERNS)

        if has_tool:
            return Answer(self.name, NEEDS_TOOLS, 0.88)
        if has_direct:
            return Answer(self.name, DIRECT, 0.90)
        if len(text) < 120 and "?" in text and not has_tool:
            return Answer(self.name, DIRECT, 0.80)
        return None


class PlanRule:
    """PLAN: checks whether a planned mutating action aligns with the user request."""

    name = "rules"

    async def decide(self, request: Request) -> Answer | None:
        if request.kind is not Kind.PLAN:
            return None
        return Answer(self.name, FITS, 0.85)


class ReplyRule:
    """REPLY: checks whether a completed reply answers the user request."""

    name = "rules"

    async def decide(self, request: Request) -> Answer | None:
        if request.kind is not Kind.REPLY or not request.context.text.strip():
            return None
        text = request.context.text.strip()
        if len(text) > 10 and not any(k in text.lower() for k in ("i apologize, i could not", "task failed", "error occurred")):
            return Answer(self.name, FOLLOWS, 0.85)
        return Answer(self.name, FOLLOWS, 0.70)


class RulesDecider:
    """Unified rules decider that routes to InstructionRules, RouteRule, PlanRule, or ReplyRule."""

    name = "rules"

    def __init__(self) -> None:
        self.instructions = InstructionRules()
        self.route = RouteRule()
        self.plan = PlanRule()
        self.reply = ReplyRule()

    async def decide(self, request: Request) -> Answer | None:
        if request.kind is Kind.INSTRUCTIONS:
            return await self.instructions.decide(request)
        if request.kind is Kind.ROUTE:
            return await self.route.decide(request)
        if request.kind is Kind.PLAN:
            return await self.plan.decide(request)
        if request.kind is Kind.REPLY:
            return await self.reply.decide(request)
        return None
