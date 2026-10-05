"""The self-test: the real decider and worker, asked three questions whose answers are known."""
from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator

import pytest

from lilly.decide import laya_selftest as st
from lilly.decide.laya_decider import LayaDecider
from lilly.domain.decisions import CLEAN, FLAGGED, LOOPING
from tests.unit.test_laya_decider import decider


@pytest.fixture
async def laya() -> AsyncIterator[LayaDecider]:
    d = decider()
    yield d
    await d.aclose()


async def test_ready_loads_the_model_and_waits_for_it_without_sleeping_in_the_caller(laya: LayaDecider) -> None:
    assert laya.state == "off"
    assert await laya.ready() is True and laya.state == "ready"
    assert await laya.ready() is True          # asking again costs nothing


async def test_ready_says_false_for_a_worker_that_cannot_start() -> None:
    d = decider(command=[sys.executable, "-c", "raise SystemExit(1)"])
    try:
        assert await d.ready() is False and d.state == "off"
    finally:
        await d.aclose()


async def test_ready_is_false_for_a_model_that_has_been_given_up_on() -> None:
    d = decider()
    d._slow = 99
    assert await d.ready() is False and d.state == "off"


async def test_three_known_questions_are_asked_and_each_result_is_reported(laya: LayaDecider) -> None:
    report = await st.self_test(laya)
    assert report.ok and report.loaded and report.error is None and report.load_ms >= 0
    assert [(r.name, r.expected, r.got, r.ok) for r in report.results] == [
        ("An instruction aimed at an agent", FLAGGED, FLAGGED, True),
        ("Ordinary prose", CLEAN, CLEAN, True),
        ("A step list that repeats", LOOPING, LOOPING, True)]
    assert all(r.confidence is not None and r.confidence > 0 and r.ms >= 0 for r in report.results)


async def test_a_wrong_answer_fails_the_test_and_says_which(laya: LayaDecider, monkeypatch: pytest.MonkeyPatch) -> None:
    flipped = (st.CASES[0], st.Case(st.CASES[1].name, st.CASES[1].kind, st.CASES[1].options, st.CASES[1].context, FLAGGED),
               st.CASES[2])
    monkeypatch.setattr(st, "CASES", flipped)
    report = await st.self_test(laya)
    assert not report.ok and report.loaded
    assert [r.ok for r in report.results] == [True, False, True]
    assert report.error is not None and "1 of 3" in report.error and "watch only" in report.error.lower()


async def test_a_worker_that_will_not_start_fails_with_plain_help() -> None:
    d = decider(command=["/definitely/not/a/program"])
    try:
        report = await st.self_test(d)
    finally:
        await d.aclose()
    assert not report.ok and not report.loaded and report.results == ()
    assert report.error is not None and "lilly laya install" in report.error


async def test_the_whole_test_is_bounded_and_reports_what_it_managed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(st, "TEST_TIMEOUT_S", 0.3)
    d = decider(command=[sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        started = asyncio.get_running_loop().time()
        report = await st.self_test(d)
        assert asyncio.get_running_loop().time() - started < 3
    finally:
        await d.aclose()
    assert not report.ok and report.error is not None and "too long" in report.error


def test_the_limits_are_the_load_limit_plus_a_few_seconds() -> None:
    from lilly.decide.laya_decider import START_TIMEOUT_S

    assert START_TIMEOUT_S < st.TEST_TIMEOUT_S <= START_TIMEOUT_S + 20
    assert 3 * st.QUESTION_TIMEOUT_S <= st.TEST_TIMEOUT_S - START_TIMEOUT_S
