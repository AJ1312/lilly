"""Rate limits, quotas, circuit breaker, and how the pool routes around them."""
from __future__ import annotations

from datetime import datetime, timezone

from lilly.core.limits import CircuitBreaker, DailyQuota, SlidingWindowLimiter
from lilly.core.pool import ProviderPool, build_pool
from lilly.domain.caps import Cap
from lilly.domain.grants import GrantStore
from lilly.domain.labels import Label, Mode
from lilly.domain.settings import ModelSpec, Settings
from tests.helpers import Clock


def test_sliding_window_expires_and_reports_retry_time() -> None:
    clock = Clock(100.0)
    lim = SlidingWindowLimiter(2, 60.0, clock)
    for _ in range(2):
        assert lim.would_allow()
        lim.commit()
    assert not lim.would_allow()
    assert 0 < lim.retry_after() <= 60.0
    clock.advance(61)
    assert lim.would_allow() and lim.used == 0
    lim.commit()
    assert lim.used == 1


def test_daily_quota_resets_at_local_midnight() -> None:
    now = [datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)]
    q = DailyQuota(1, "UTC", lambda: now[0])
    assert q.would_allow()
    q.commit()
    assert not q.would_allow()
    now[0] = datetime(2026, 1, 2, 0, 1, tzinfo=timezone.utc)
    assert q.would_allow() and q.used == 0


def test_breaker_opens_after_failures_then_recovers() -> None:
    clock = Clock(0.0)
    b = CircuitBreaker(2, 30.0, clock)
    b.failure()
    b.failure()
    assert b.state == "open" and not b.ready()
    clock.advance(31)
    assert b.ready() and b.begin()
    b.success()
    assert b.state == "closed"


def pool(*specs: ModelSpec) -> ProviderPool:
    return build_pool(Settings(models=specs))


def test_pool_uses_list_order_and_skips_disabled() -> None:
    p = pool(ModelSpec("a", "mistral", "m", enabled=False), ModelSpec("b", "mistral", "m"), ModelSpec("c", "mistral", "m"))
    assert p.route().entry.name == "b"  # type: ignore[union-attr]


def test_pool_falls_through_when_a_model_is_over_its_limit() -> None:
    p = pool(ModelSpec("a", "mistral", "m", rpm=1), ModelSpec("b", "mistral", "m"))
    assert p.route().entry.name == "a"  # type: ignore[union-attr]
    assert p.route().entry.name == "b"  # type: ignore[union-attr]


def test_pool_needs_capability() -> None:
    p = pool(ModelSpec("a", "mistral", "m"), ModelSpec("b", "mistral", "m", caps=Cap.JSON))
    assert p.route(Cap.JSON).entry.name == "b"  # type: ignore[union-attr]


def test_pin_is_never_replaced_silently() -> None:
    p = pool(ModelSpec("a", "mistral", "m", enabled=False), ModelSpec("b", "mistral", "m"))
    r = p.route(pin="a")
    assert r.entry is None and "unavailable" in r.reason


def test_private_data_needs_a_grant_on_remote_models_but_not_local_ones() -> None:
    remote = ModelSpec("remote", "mistral", "m")
    local = ModelSpec("local", "ollama", "m", local=True, max_label=Label.PERSONAL, trains=False)
    only_remote = pool(remote).route(label=Label.PERSONAL, mode=Mode.ASK)
    assert only_remote.entry is None and only_remote.grantable == ("remote",)
    assert pool(remote, local).route(label=Label.PERSONAL).entry.name == "local"  # type: ignore[union-attr]


def test_grant_unlocks_a_remote_model_once() -> None:
    grants = GrantStore()
    grants.grant("remote", Label.PERSONAL, 60, task_id="t1", once=True)
    p = pool(ModelSpec("remote", "mistral", "m"))
    assert p.route(label=Label.PERSONAL, grants=grants, task_id="t1").entry is not None
    assert p.route(label=Label.PERSONAL, grants=grants, task_id="t1").entry is None


def test_secret_never_goes_to_a_remote_model() -> None:
    grants = GrantStore()
    grants.grant("remote", Label.SECRET, 60, task_id="t1")
    r = pool(ModelSpec("remote", "mistral", "m")).route(label=Label.SECRET, grants=grants, task_id="t1")
    assert r.entry is None and not r.grantable


def test_locked_agents_stay_within_the_standing_ceiling() -> None:
    r = pool(ModelSpec("remote", "mistral", "m")).route(label=Label.PERSONAL, mode=Mode.LOCKED)
    assert r.entry is None and not r.grantable


def test_rebuilding_the_pool_keeps_counters_unless_their_own_limit_changed() -> None:
    first = pool(ModelSpec("a", "mistral", "m", rpm=5, rpd=10))
    entry = first.entries[0]
    for _ in range(3):
        assert first.route().entry is entry
    entry.breaker.failure()
    unrelated = build_pool(Settings(models=(ModelSpec("a", "mistral", "m", rpm=5, rpd=10, enabled=False, trains=False),)), first)
    kept = unrelated.entries[0]
    assert kept.spec.enabled is False
    assert kept.daily is not None and kept.daily.used == 3
    assert kept.minute is not None and kept.minute.used == 3
    assert kept.breaker is entry.breaker
    raised = build_pool(Settings(models=(ModelSpec("a", "mistral", "m", rpm=5, rpd=20),)), unrelated).entries[0]
    assert raised.daily is not None and raised.daily.used == 0 and raised.daily.limit == 20
    assert raised.minute is not None and raised.minute.used == 3
    swapped = build_pool(Settings(models=(ModelSpec("a", "mistral", "other", rpm=5, rpd=20),)), unrelated).entries[0]
    assert swapped.daily is not None and swapped.daily.used == 0 and swapped.breaker.state == "closed"


def test_quick_models_are_tried_first_for_small_jobs_and_the_rest_keep_their_order() -> None:
    p = pool(ModelSpec("big", "mistral", "m"), ModelSpec("small", "mistral", "m", quick=True), ModelSpec("mid", "mistral", "m"))
    assert p.route().entry.name == "big"                       # planning and everything else: the normal order
    assert p.route(quick=True).entry.name == "small"
    assert p.route(quick=True, skip=frozenset({"small"})).entry.name == "big"       # a quick model that is down costs nothing
    assert p.route(quick=True, pin="mid").entry.name == "mid"                       # a pinned model is never replaced


def test_the_quick_setting_round_trips_and_a_bad_value_is_refused() -> None:
    from lilly.domain.settings import default_settings, parse_settings, settings_to_dict
    raw = settings_to_dict(default_settings())
    raw["models"] = [{"name": "a", "provider": "mistral", "model_id": "m", "quick": True}]
    parsed, errs = parse_settings(raw)
    assert errs == [] and parsed is not None and parsed.models[0].quick is True
    assert settings_to_dict(parsed)["models"][0]["quick"] is True
    raw["models"][0]["quick"] = "yes"
    assert parse_settings(raw)[0] is None


def test_tokens_used_are_counted_per_model_and_survive_a_settings_change() -> None:
    p = pool(ModelSpec("a", "mistral", "m"))
    p.entries[0].record_use(100, 20)
    p.entries[0].record_use(50, 5)
    assert [(r["calls"], r["tokens_in"], r["tokens_out"]) for r in p.snapshot()] == [(2, 150, 25)]
    from dataclasses import replace

    from lilly.core.pool import build_pool
    from lilly.domain.settings import default_settings
    changed = build_pool(replace(default_settings(), models=(ModelSpec("a", "mistral", "m", trains=False),)), p)
    assert changed.entries[0].tokens == [2, 150, 25]
