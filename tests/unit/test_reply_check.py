"""The reply checker on its own: bounded, quiet, and gone when closed."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from lilly.domain.decisions import (
    DRIFTS,
    Answer,
    Brief,
    DecisionRecord,
    DecisionSettings,
    Kind,
    Request,
    with_assist,
)
from lilly.engine.decisions import DecisionPipeline
from lilly.engine.replycheck import EVENT, MAX_PENDING, ReplyChecker
from tests.helpers import Clock


@dataclass
class Laya:
    name: str = "laya"
    release: asyncio.Event = field(default_factory=asyncio.Event)
    asked: int = 0

    async def decide(self, request: Request) -> Answer | None:
        self.asked += 1
        await self.release.wait()
        return Answer("laya", DRIFTS, 0.9)


class Sink:
    async def record(self, record: DecisionRecord) -> int | None:
        return 1


def checker(laya: Laya, on: bool = True) -> ReplyChecker:
    settings = with_assist(DecisionSettings(), Kind.REPLY, on, act=True)
    return ReplyChecker(DecisionPipeline(lambda: settings, lambda: {"laya": laya}, Sink(), Clock()))


async def test_a_check_records_what_laya_said_as_a_note_on_the_task() -> None:
    laya, notes = Laya(), []

    async def record(kind: str, payload: dict[str, Any]) -> None:
        notes.append((kind, payload))

    c = checker(laya)
    c.start("t1", Brief("g", "i"), "the reply", record)
    laya.release.set()
    await asyncio.sleep(0.05)
    assert notes == [(EVENT, {"choice": DRIFTS, "confidence": 0.9, "decider": "laya"})]


async def test_no_more_than_the_limit_are_waiting_at_once_and_the_rest_are_skipped() -> None:
    laya = Laya()

    async def record(kind: str, payload: dict[str, Any]) -> None:
        raise AssertionError("nothing should be recorded")

    c = checker(laya)
    for i in range(MAX_PENDING + 10):
        c.start(f"t{i}", Brief("g"), "r", record)
    await asyncio.sleep(0.05)
    assert laya.asked == MAX_PENDING
    await c.aclose()


async def test_a_question_that_is_switched_off_starts_nothing() -> None:
    laya = Laya()
    c = checker(laya, on=False)
    c.start("t", Brief("g"), "r", lambda kind, payload: asyncio.sleep(0))
    await asyncio.sleep(0.02)
    assert laya.asked == 0


async def test_a_note_that_cannot_be_recorded_is_dropped_quietly() -> None:
    laya = Laya()

    async def record(kind: str, payload: dict[str, Any]) -> None:
        raise OSError("the disk is full")

    c = checker(laya)
    c.start("t", Brief("g"), "r", record)
    laya.release.set()
    await asyncio.sleep(0.05)
    await c.aclose()         # nothing left over, nothing raised


async def test_closing_cancels_what_is_waiting_and_closing_twice_is_fine() -> None:
    laya = Laya()
    c = checker(laya)
    c.start("t", Brief("g"), "r", lambda kind, payload: asyncio.sleep(0))
    await asyncio.sleep(0.02)
    await c.aclose()
    await c.aclose()
    assert laya.asked == 1 and not c._tasks
