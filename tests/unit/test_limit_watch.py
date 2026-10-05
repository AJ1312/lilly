"""Lilly learns a provider's limits from its rejections, suggests them, and never spends a call finding out twice."""
from __future__ import annotations

import pytest

from lilly.core.limits import CircuitBreaker, LimitWatch
from lilly.core.pool import _lower


class Clk:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def calls(w: LimitWatch, clk: Clk, n: int, gap: float = 1.0) -> None:
    for _ in range(n):
        w.began()
        clk.t += gap


def test_a_minute_rejection_teaches_a_per_minute_limit_a_little_under_what_worked() -> None:
    clk = Clk()
    w = LimitWatch(clk)
    calls(w, clk, 11)          # ten went through, the eleventh was refused
    w.rejected(20.0)
    assert w.rpm == 9 and w.rpd is None


def test_a_long_wait_means_the_daily_limit() -> None:
    clk = Clk()
    w = LimitWatch(clk)
    calls(w, clk, 101, gap=30.0)
    w.rejected(3 * 3600)
    assert w.rpd == 90 and w.rpm is None


def test_the_lowest_observation_is_kept_and_a_first_call_that_is_refused_teaches_nothing() -> None:
    clk = Clk()
    w = LimitWatch(clk)
    calls(w, clk, 1)
    w.rejected(None)
    assert w.rpm is None
    clk.t += 120
    calls(w, clk, 21)
    w.rejected(None)
    clk.t += 120
    calls(w, clk, 6)
    w.rejected(None)
    assert w.rpm == 4


def test_old_calls_do_not_count_and_memory_is_bounded() -> None:
    clk = Clk()
    w = LimitWatch(clk)
    calls(w, clk, LimitWatch.MAX_CALLS + 50, gap=0.001)
    assert len(w._calls) == LimitWatch.MAX_CALLS
    clk.t += 3600
    w.rejected(10.0)
    assert w.rpm is None        # nothing worked within the last minute


@pytest.mark.parametrize(("learned", "owner", "shown"), [(9, None, 9), (9, 30, 9), (9, 9, None), (9, 5, None), (None, None, None)])
def test_a_suggestion_is_shown_only_while_the_owner_has_not_set_a_limit_as_low(learned: int | None, owner: int | None, shown: int | None) -> None:
    assert _lower(learned, owner) == shown


def test_a_tripped_breaker_blocks_calls_until_the_wait_is_over_then_lets_one_probe_through() -> None:
    clk = Clk()
    b = CircuitBreaker(clock=clk)
    b.trip(30.0)
    assert not b.ready() and b.state == "open"
    clk.t += 31
    assert b.ready() and b.begin() and b.state == "half-open"
    b.success()
    assert b.state == "closed"


def test_without_a_stated_wait_the_pause_is_short_and_grows_only_while_refusals_continue() -> None:
    w = LimitWatch(Clk())
    assert [w.wait_after_refusal(None) for _ in range(6)] == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0]
    w.worked()
    assert w.wait_after_refusal(None) == 5.0
    assert w.wait_after_refusal(30.0) == 30.0        # what the provider says always wins
