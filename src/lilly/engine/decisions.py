"""The decision pipeline: ask each configured decider in turn, trust none of them, and log everything.

An answer is used only when it names an option the caller offered, with enough confidence, in time. Anything
else (no answer, an error, a timeout, a stranger id) moves on to the next decider; when none is left the
outcome is "no decision" and the caller applies its own safe fallback. Nothing here touches policy.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from lilly.domain.clock import Clock
from lilly.domain.decisions import (
    Answer,
    ChainStep,
    Context,
    Decider,
    DecisionRecord,
    DecisionSettings,
    DecisionSink,
    Kind,
    Option,
    Outcome,
    Request,
    Warmable,
    summarise,
    valid_confidence,
)
from lilly.domain.errors import WriterBusy
from lilly.store import decisions
from lilly.store.db import Database

log = logging.getLogger("lilly.decide")
MAX_TASKS_TRACKED = 512
MAX_REASON = 200


@dataclass(slots=True)
class _Spent:
    asked: int = 0
    tokens: int = 0


def _problem(answer: object, ids: frozenset[str], minimum: float) -> str | None:
    """Why an answer cannot be used, or None when it can."""
    if not isinstance(answer, Answer):
        return "gave a malformed answer"
    if not isinstance(answer.choice, str) or answer.choice not in ids \
            or not all(isinstance(i, str) and i in ids for i in answer.ranking):
        return "answered outside the offered options"
    if not valid_confidence(answer.confidence):
        return "gave an invalid confidence"
    if answer.confidence < minimum:
        return f"was not sure enough ({answer.confidence:.2f} < {minimum:.2f})"
    return None


class DecisionPipeline:
    def __init__(self, config: Callable[[], DecisionSettings], deciders: Callable[[], Mapping[str, Decider]],
                 sink: DecisionSink, clock: Clock) -> None:
        self._config, self._deciders, self._sink, self._clock = config, deciders, sink, clock
        self._spent: OrderedDict[str, _Spent] = OrderedDict()

    def _spent_by(self, task_id: str | None) -> _Spent:
        key = task_id or ""
        spent = self._spent.setdefault(key, _Spent())
        self._spent.move_to_end(key)
        while len(self._spent) > MAX_TASKS_TRACKED:
            self._spent.popitem(last=False)
        return spent

    def active(self, kind: Kind) -> bool:
        """Whether this question would be asked at all right now (switched on, with at least one decider)."""
        cfg = self._config()
        mine = cfg.for_kind(kind)
        return cfg.enabled and mine.enabled and bool(mine.chain)

    def prepare(self, kind: Kind) -> None:
        """Let the deciders of this question that are slow to get ready start now, so that they are ready when
        the question comes. Returns at once and never raises; a question that would not be asked prepares nothing."""
        if not self.active(kind):
            return
        available = self._deciders()
        for step in self._config().for_kind(kind).chain:
            decider = available.get(step.decider)
            if isinstance(decider, Warmable):
                try:
                    decider.warm()
                except Exception as exc:
                    log.warning("decider %s could not get ready: %s", step.decider, type(exc).__name__)

    async def decide(self, kind: Kind, task_id: str | None, options: tuple[Option, ...],
                     context: Context) -> Outcome:
        """Never raises. `choice` is None for "no decision", and also in shadow mode, where the answer is
        only logged."""
        cfg = self._config()
        mine = cfg.for_kind(kind)
        if not cfg.enabled or not mine.enabled or not options:
            return Outcome(kind, reason="decisions are switched off for this question")
        spent = self._spent_by(task_id)
        notes: list[str] = []
        found: tuple[str, Answer] | None = None
        if spent.asked >= cfg.max_per_task:
            notes.append("this task has used its decision allowance")
        else:
            spent.asked += 1
            found = await self._ask(kind, task_id, options, context, mine.chain, cfg, spent, notes)
        return await self._finish(kind, task_id, options, context, mine.shadow, found, notes)

    async def _ask(self, kind: Kind, task_id: str | None, options: tuple[Option, ...], context: Context,
                   chain: tuple[ChainStep, ...], cfg: DecisionSettings, spent: _Spent,
                   notes: list[str]) -> tuple[str, Answer] | None:
        ids = frozenset(o.id for o in options)
        available = self._deciders()      # looked up now, so a model or add-on enabled a moment ago counts
        for step in chain:
            decider = available.get(step.decider)
            if decider is None:
                log.info("decider %s is not installed; skipped", step.decider)
                notes.append(f"{step.decider} is not installed")
                continue
            request = Request(kind, task_id, options, context,
                              max(0, cfg.max_model_tokens_per_task - spent.tokens), step.timeout_s)
            try:
                async with asyncio.timeout(step.timeout_s):
                    answer = await decider.decide(request)
            except TimeoutError:
                notes.append(f"{step.decider} ran out of time")
                continue
            except Exception as exc:
                log.warning("decider %s failed: %s", step.decider, type(exc).__name__)
                notes.append(f"{step.decider} failed")
                continue
            if answer is None:
                notes.append(f"{step.decider} had no answer")
                continue
            if isinstance(answer, Answer) and isinstance(answer.tokens_used, int):
                spent.tokens += max(0, answer.tokens_used)
            if (why := _problem(answer, ids, step.min_confidence)) is not None:
                notes.append(f"{step.decider} {why}")
                continue
            return step.decider, answer
        return None

    async def _finish(self, kind: Kind, task_id: str | None, options: tuple[Option, ...], context: Context,
                      shadow: bool, found: tuple[str, Answer] | None, notes: list[str]) -> Outcome:
        name, answer = found if found else (None, None)
        choice = answer.choice if answer else None
        reason = "; ".join(([f"{name} answered"] if name else []) + notes)[:MAX_REASON] or "no decider was configured"
        record = DecisionRecord(self._clock(), kind, task_id, name, choice, answer.confidence if answer else None,
                                shadow, len(options), summarise(context.text), reason)
        try:
            log_id = await self._sink.record(record)
        except Exception as exc:
            log.warning("decision not logged: %s", type(exc).__name__)
            log_id = None
        if answer is None or choice is None:
            return Outcome(kind, reason=reason, log_id=log_id)
        if shadow:   # the caller must not act on it; the log keeps what it would have said
            return Outcome(kind, reason=f"shadow, would have chosen {choice}; {reason}", log_id=log_id, would=choice)
        return Outcome(kind, choice, tuple(dict.fromkeys((choice, *answer.ranking))), name, answer.confidence,
                       reason, log_id)


class DatabaseSink:
    """Keeps decision records in the database through the single writer."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, record: DecisionRecord) -> int | None:
        try:
            return await self._db.write(lambda con: decisions.insert(con, record))
        except WriterBusy:
            log.warning("decision not logged: database busy")
            return None
