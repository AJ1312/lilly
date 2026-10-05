"""Chat bridges, pure rules: settings bounds, one-time pairing codes, rate limits, message limits."""
from __future__ import annotations

import pytest

from lilly.domain.bridges import (
    BridgeSettings,
    Pairing,
    RateLimiter,
    bridge_to_dict,
    clean_inbound,
    parse_bridge,
)
from tests.helpers import Clock


def test_defaults_are_off_and_cautious() -> None:
    b = BridgeSettings()
    assert (b.enabled, b.agent_id, b.private_replies, b.per_minute, b.max_chars) == (False, None, False, 6, 2000)
    parsed, errs = parse_bridge(bridge_to_dict(b))
    assert errs == [] and parsed == b


@pytest.mark.parametrize("raw,fragment", [
    ("nope", "must be an object"),
    ({"enabled": "yes"}, "enabled must be true or false"),
    ({"per_minute": 0}, "per_minute must be a whole number from 1 to 30"),
    ({"max_chars": 99999}, "max_chars must be a whole number from 100 to 4000"),
    ({"agent_id": 5}, "agent_id must be text"),
    ({"surprise": 1}, "unknown setting"),
    ({"private_replies": 1}, "private_replies must be true or false"),
])
def test_bad_settings_are_rejected_with_a_reason(raw: object, fragment: str) -> None:
    parsed, errs = parse_bridge(raw)
    assert parsed is None and any(fragment in e for e in errs)


def test_a_pairing_code_works_once_and_only_in_time() -> None:
    clock = Clock()
    p = Pairing(clock, ttl_s=60)
    code = p.new()
    assert len(code) == 8 and code.isalnum() and code == code.upper()
    assert p.redeem("wrong123", 1) is False
    assert p.redeem(code.lower(), 1) is True          # case does not matter when typing on a phone
    assert p.redeem(code, 1) is False              # used up
    second = p.new()
    clock.advance(61)
    assert p.redeem(second, 1) is False            # expired


def test_a_new_code_replaces_the_old_one() -> None:
    p = Pairing(Clock())
    first, second = p.new(), p.new()
    assert first != second and p.redeem(first, 1) is False and p.redeem(second, 1) is True


def test_guessing_is_limited_per_sender_so_a_stranger_cannot_burn_the_owners_code() -> None:
    p = Pairing(Clock(), max_wrong=3)
    code = p.new()
    for _ in range(3):
        assert p.redeem("AAAAAAAA", 666) is False
    assert p.redeem(code, 666) is False            # this sender is locked out, even with the right code
    assert p.active() is not None
    assert p.redeem(code, 1) is True               # the owner is not affected


def test_a_flood_of_wrong_guesses_from_many_senders_still_burns_the_code() -> None:
    p = Pairing(Clock(), max_wrong=3, max_wrong_total=10)
    code = p.new()
    for sender in range(10):
        assert p.redeem("AAAAAAAA", sender) is False
    assert p.redeem(code, 99) is False and p.active() is None


def test_the_table_of_senders_is_bounded_and_a_new_code_clears_it() -> None:
    p = Pairing(Clock(), max_wrong=1, max_wrong_total=10_000, max_senders=4)
    code = p.new()
    for sender in range(50):
        p.redeem("AAAAAAAA", sender)
    assert p.redeem(code, 0) is True                # sender 0 was forgotten, so it is not locked out
    p.redeem("AAAAAAAA", 7)
    again = p.new()
    assert p.redeem(again, 7) is True               # a new code starts everyone afresh


def test_active_reports_the_code_deadline_only_while_it_is_usable() -> None:
    clock = Clock()
    p = Pairing(clock, ttl_s=60)
    assert p.active() is None
    p.new()
    assert p.active() == clock() + 60
    clock.advance(61)
    assert p.active() is None


def test_each_sender_has_their_own_rate_limit() -> None:
    clock = Clock()
    limit = RateLimiter(clock, per_minute=2)
    assert limit.allow(1) and limit.allow(1) and not limit.allow(1)
    assert limit.allow(2)
    clock.advance(61)
    assert limit.allow(1)


def test_the_rate_limiter_forgets_idle_senders() -> None:
    clock = Clock()
    limit = RateLimiter(clock, per_minute=1, max_senders=3)
    for sender in range(10):
        limit.allow(sender)
    assert len(limit._seen) <= 3


@pytest.mark.parametrize("text,expected", [
    ("  hello   there ", "hello ther"),   # whitespace collapsed first, then cut to 10
    ("a\u0000b", "ab"),
    ("x" * 50, "x" * 10),
])
def test_inbound_text_is_cleaned_and_cut(text: str, expected: str) -> None:
    assert clean_inbound(text, 10) == expected


def test_empty_text_is_nothing() -> None:
    assert clean_inbound("   \n ", 100) == ""
