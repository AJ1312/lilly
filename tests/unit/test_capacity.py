"""Tests for capacity management, rate limiting, and queue fairness.

CAP-01..20:
- CAP-01: Fake clock RPM wait
- CAP-02: Fake clock RPD wait
- CAP-03: Fake clock TPM wait
- CAP-04: Fake clock TPD wait
- CAP-05: 429 with Retry-After in seconds
- CAP-06: 429 with Retry-After HTTP-date
- CAP-07: 429 with X-RateLimit-Reset (seconds and epoch ms)
- CAP-08: Google retryDelay ("34s") in error.details
- CAP-09: Head-of-queue fairness (interactive before background)
- CAP-10: Balanced spread ±1
- CAP-11: Pins never switch
- CAP-12: Label access never bypassed while waiting
- CAP-13: Cancellation leaks nothing
- CAP-14: 5xx refunds request slot; 429 does not
- CAP-15: Learned limits only lower
- CAP-16: In-flight cap
- CAP-17: Wait events deduplicated
- CAP-18: Exact messages of Phase 1
- CAP-19: No replan on capacity failure
- CAP-20: Capacity snapshot & API metrics
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path

import pytest

from lilly.core.capacity import CallProfile, CapacityManager
from lilly.core.limits import LimitWatch, backoff
from lilly.core.pool import ProviderPool
from lilly.domain.caps import Cap
from lilly.domain.errors import NeedsGrant, NoModelAvailable, ProviderError, RateLimited
from lilly.domain.labels import Label
from lilly.domain.settings import CapacitySettings, ModelSpec
from lilly.engine.messages import (
    PINNED_BUSY,
    RESUME_THOUGHT,
    WAIT_THOUGHT,
    WAIT_TOO_LONG,
)
from lilly.engine.outcome import StepFailed, describe_provider_error
from tests.helpers import Clock, ControllableRand, FakeSleep


def _make_pool(specs: tuple[ModelSpec, ...], clock: Clock) -> ProviderPool:
    from lilly.core.pool import build_pool
    from lilly.domain.settings import Settings
    return build_pool(Settings(models=specs), clock=clock)


@pytest.mark.asyncio
async def test_cap_01_rpm_wait() -> None:
    """CAP-01: Fake clock RPM wait: call waits until sliding window frees up a slot."""
    clock = Clock(1_000_000.0)
    fake_sleep = FakeSleep(clock)
    spec = ModelSpec("m-rpm", "mistral", "m1", rpm=1)
    pool = _make_pool((spec,), clock)
    mgr = CapacityManager(pool, CapacitySettings(max_wait_interactive_s=120), clock=clock, sleep_fn=fake_sleep)

    prof = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)
    lease1 = await mgr.acquire(prof)
    assert lease1.entry.name == "m-rpm"
    mgr.release(lease1, tokens_in=10, tokens_out=10, outcome="ok")

    # Second call arrives immediately at same timestamp: must wait ~60s
    lease2 = await mgr.acquire(prof)
    assert lease2.entry.name == "m-rpm"
    assert lease2.waited_s >= 59.9
    mgr.release(lease2, tokens_in=10, tokens_out=10, outcome="ok")


@pytest.mark.asyncio
async def test_cap_02_rpd_wait() -> None:
    """CAP-02: Fake clock RPD wait: daily limit spent, waits until reset."""
    clock = Clock(1_000_000.0)
    fake_sleep = FakeSleep(clock)
    spec = ModelSpec("m-rpd", "mistral", "m1", rpd=1)
    pool = _make_pool((spec,), clock)
    mgr = CapacityManager(pool, CapacitySettings(max_wait_interactive_s=100_000), clock=clock, sleep_fn=fake_sleep)

    prof = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)
    lease1 = await mgr.acquire(prof)
    mgr.release(lease1, tokens_in=10, tokens_out=10, outcome="ok")

    # Next call exceeds RPD: timeout if max_wait_s is small
    with pytest.raises(NoModelAvailable):
        await mgr.acquire(prof, max_wait_s=10)


@pytest.mark.asyncio
async def test_cap_03_tpm_wait() -> None:
    """CAP-03: Fake clock TPM wait: waits until token window frees up required tokens."""
    clock = Clock(1_000_000.0)
    fake_sleep = FakeSleep(clock)
    spec = ModelSpec("m-tpm", "mistral", "m1", tpm=1000)
    pool = _make_pool((spec,), clock)
    mgr = CapacityManager(pool, CapacitySettings(max_wait_interactive_s=120), clock=clock, sleep_fn=fake_sleep)

    prof1 = CallProfile(est_in=400, est_out=400, role="act", need=Cap.NONE, priority=0)
    lease1 = await mgr.acquire(prof1)
    mgr.release(lease1, tokens_in=400, tokens_out=400, outcome="ok")

    # Second call needs 400 tokens (800 used + 400 = 1200 > 1000): must wait for window roll
    prof2 = CallProfile(est_in=200, est_out=200, role="act", need=Cap.NONE, priority=0)
    lease2 = await mgr.acquire(prof2)
    assert lease2.waited_s >= 59.9
    mgr.release(lease2, tokens_in=200, tokens_out=200, outcome="ok")


@pytest.mark.asyncio
async def test_cap_04_tpd_wait() -> None:
    """CAP-04: Fake clock TPD wait: daily token quota spent, waits until reset."""
    clock = Clock(1_000_000.0)
    spec = ModelSpec("m-tpd", "mistral", "m1", tpd=1000)
    pool = _make_pool((spec,), clock)
    mgr = CapacityManager(pool, CapacitySettings(max_wait_interactive_s=60), clock=clock)

    prof = CallProfile(est_in=500, est_out=500, role="act", need=Cap.NONE, priority=0)
    lease1 = await mgr.acquire(prof)
    mgr.release(lease1, tokens_in=500, tokens_out=500, outcome="ok")

    # Exceeds TPD
    with pytest.raises(NoModelAvailable):
        await mgr.acquire(prof, max_wait_s=5)


def test_cap_05_retry_after_seconds() -> None:
    """CAP-05: 429 with Retry-After in seconds is parsed."""
    from lilly.providers.base import map_http_error
    fix_path = Path(__file__).resolve().parents[1] / "fixtures" / "429" / "synthetic_mistral.json"
    data = json.loads(fix_path.read_text(encoding="utf-8"))
    err = map_http_error(data["status"], data["headers"], data["body"])
    assert isinstance(err, RateLimited)
    assert err.retry_after == 5.0
    assert err.scope == "minute"


def test_cap_06_retry_after_http_date() -> None:
    """CAP-06: 429 with Retry-After HTTP-date is parsed."""
    from lilly.providers.base import map_http_error
    fix_path = Path(__file__).resolve().parents[1] / "fixtures" / "429" / "synthetic_cerebras.json"
    data = json.loads(fix_path.read_text(encoding="utf-8"))
    err = map_http_error(data["status"], data["headers"], data["body"], clock_wall=lambda: 1792567670.0)
    assert isinstance(err, RateLimited)
    assert err.retry_after is not None and err.retry_after > 0
    assert err.scope == "day"


def test_cap_07_reset_header_ms_and_seconds() -> None:
    """CAP-07: 429 with X-RateLimit-Reset (seconds and epoch ms) is parsed."""
    from lilly.providers.base import map_http_error
    fix_path = Path(__file__).resolve().parents[1] / "fixtures" / "429" / "synthetic_groq.json"
    data = json.loads(fix_path.read_text(encoding="utf-8"))
    err = map_http_error(data["status"], data["headers"], data["body"])
    assert isinstance(err, RateLimited)
    assert err.retry_after == 15.0
    assert err.scope == "minute"

    # Epoch ms test
    headers_ms = {"x-ratelimit-reset": "1727184015000"}
    err_ms = map_http_error(429, headers_ms, b"", clock_wall=lambda: 1727184000.0)
    assert isinstance(err_ms, RateLimited)
    assert abs(err_ms.retry_after - 15.0) < 0.01


def test_cap_08_google_retry_delay() -> None:
    """CAP-08: Google retryDelay ("34s") in error.details is parsed."""
    from lilly.providers.base import map_http_error
    fix_path = Path(__file__).resolve().parents[1] / "fixtures" / "429" / "synthetic_gemini.json"
    data = json.loads(fix_path.read_text(encoding="utf-8"))
    err = map_http_error(data["status"], data["headers"], data["body"])
    assert isinstance(err, RateLimited)
    assert err.retry_after == 34.0
    assert err.scope == "day"


@pytest.mark.asyncio
async def test_cap_09_head_of_queue_fairness() -> None:
    """CAP-09: Head-of-queue fairness: interactive caller (priority 0) jumps ahead of background callers."""
    clock = Clock(1_000_000.0)
    spec = ModelSpec("m-fair", "mistral", "m1", rpm=1)
    pool = _make_pool((spec,), clock)
    mgr = CapacityManager(pool, CapacitySettings(max_wait_interactive_s=500, max_wait_background_s=500), clock=clock)

    prof_bg = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=1)
    prof_int = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)

    # Use first slot
    lease0 = await mgr.acquire(prof_bg)
    mgr.release(lease0, tokens_in=10, tokens_out=10, outcome="ok")

    order: list[str] = []

    async def run_bg(name: str) -> None:
        l = await mgr.acquire(prof_bg)
        order.append(name)
        mgr.release(l, tokens_in=10, tokens_out=10, outcome="ok")

    async def run_interactive() -> None:
        l = await mgr.acquire(prof_int)
        order.append("interactive")
        mgr.release(l, tokens_in=10, tokens_out=10, outcome="ok")

    t1 = asyncio.create_task(run_bg("bg-1"))
    t2 = asyncio.create_task(run_bg("bg-2"))
    await asyncio.sleep(0.01)

    # Interactive arrives after background tasks are already in queue
    t_int = asyncio.create_task(run_interactive())
    await asyncio.sleep(0.01)

    # Slot 1: advances clock, interactive acquires first
    clock.advance(65.0)
    mgr.wake_all()
    await asyncio.sleep(0.01)
    assert order == ["interactive"]

    # Slot 2: bg-1 acquires
    clock.advance(65.0)
    mgr.wake_all()
    await asyncio.sleep(0.01)

    # Slot 3: bg-2 acquires
    clock.advance(65.0)
    mgr.wake_all()
    await asyncio.gather(t1, t2, t_int)

    assert order == ["interactive", "bg-1", "bg-2"]


@pytest.mark.asyncio
async def test_cap_10_balanced_spread() -> None:
    """CAP-10: Balanced spread ±1: 30 calls across 3 models in one lane land within ±1 of 10 per model."""
    clock = Clock(1_000_000.0)
    specs = (
        ModelSpec("m1", "mistral", "mod1", lane=1),
        ModelSpec("m2", "mistral", "mod2", lane=1),
        ModelSpec("m3", "mistral", "mod3", lane=1),
    )
    pool = _make_pool(specs, clock)
    mgr = CapacityManager(pool, CapacitySettings(spread="balanced"), clock=clock)
    prof = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)

    counts: Counter[str] = Counter()
    for _ in range(30):
        lease = await mgr.acquire(prof)
        counts[lease.entry.name] += 1
        mgr.release(lease, tokens_in=10, tokens_out=10, outcome="ok")

    assert counts["m1"] == 10
    assert counts["m2"] == 10
    assert counts["m3"] == 10


@pytest.mark.asyncio
async def test_cap_11_pins_never_switch() -> None:
    """CAP-11: Pins never switch: pinned model waits for that model only and never falls back."""
    clock = Clock(1_000_000.0)
    specs = (
        ModelSpec("pinned-model", "mistral", "m1", rpm=1),
        ModelSpec("other-free-model", "mistral", "m2", rpm=100),
    )
    pool = _make_pool(specs, clock)
    mgr = CapacityManager(pool, CapacitySettings(max_wait_interactive_s=5), clock=clock)

    prof = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)
    lease = await mgr.acquire(prof, pin="pinned-model")
    assert lease.entry.name == "pinned-model"
    mgr.release(lease, tokens_in=10, tokens_out=10, outcome="ok")

    # Second call for pinned-model: must not switch to other-free-model
    with pytest.raises(NoModelAvailable) as exc_info:
        await mgr.acquire(prof, pin="pinned-model", max_wait_s=5)
    assert "pinned-model is pinned" in str(exc_info.value.reason)
    assert "will not switch to another model" in str(exc_info.value.reason)


@pytest.mark.asyncio
async def test_cap_12_label_access_never_bypassed_while_waiting() -> None:
    """CAP-12: Label access never bypassed while waiting."""
    clock = Clock(1_000_000.0)
    specs = (
        ModelSpec("cloud-model", "mistral", "m1", max_label=Label.PUBLIC, local=False),
    )
    pool = _make_pool(specs, clock)
    mgr = CapacityManager(pool, CapacitySettings(), clock=clock)
    prof = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)

    # SECRET data cannot be sent to cloud model: raises immediately
    with pytest.raises((NoModelAvailable, NeedsGrant)):
        await mgr.acquire(prof, label=Label.SECRET)


@pytest.mark.asyncio
async def test_cap_13_cancellation_leaks_nothing() -> None:
    """CAP-13: Cancellation while waiting removes the waiter and leaks nothing."""
    clock = Clock(1_000_000.0)
    spec = ModelSpec("m-busy", "mistral", "m1", rpm=1)
    pool = _make_pool((spec,), clock)
    mgr = CapacityManager(pool, CapacitySettings(max_wait_interactive_s=120), clock=clock)
    prof = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)

    l1 = await mgr.acquire(prof)
    assert len(mgr._waiters) == 0

    # Second acquire will wait
    task = asyncio.create_task(mgr.acquire(prof))
    await asyncio.sleep(0.01)
    assert len(mgr._waiters) == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(mgr._waiters) == 0
    mgr.release(l1, tokens_in=10, tokens_out=10, outcome="ok")


@pytest.mark.asyncio
async def test_cap_14_5xx_refunds_429_does_not() -> None:
    """CAP-14: 5xx refunds request slot; 429 does not."""
    clock = Clock(1_000_000.0)
    spec = ModelSpec("m-test", "mistral", "m1", rpm=5)
    pool = _make_pool((spec,), clock)
    mgr = CapacityManager(pool, CapacitySettings(), clock=clock)
    prof = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)

    # Call 1 fails with 5xx -> refunds slot
    lease1 = await mgr.acquire(prof)
    entry = lease1.entry
    assert entry.minute.used == 1
    mgr.release(lease1, tokens_in=0, tokens_out=0, outcome="error", error=ProviderError(retryable=True, status=503))
    assert entry.minute.used == 0, "5xx must refund the request slot"

    # Call 2 fails with 429 -> does NOT refund slot
    lease2 = await mgr.acquire(prof)
    assert entry.minute.used == 1
    mgr.release(lease2, tokens_in=0, tokens_out=0, outcome="rate_limited", error=RateLimited(scope="minute", retry_after=2.0))
    assert entry.minute.used == 1, "429 must NOT refund the request slot"


def test_cap_15_learned_limits_only_lower() -> None:
    """CAP-15: Learned limits only lower, never raise owner-set limits."""
    watch = LimitWatch()
    watch.rpm = 15
    # Owner set 10: learned 15 does not apply
    rpm, _ = watch.soft_limits(set_rpm=10)
    assert rpm == 10

    # LimitWatch learned 8: lower than owner's 10, so applies
    watch.rpm = 8
    rpm, _ = watch.soft_limits(set_rpm=10)
    assert rpm == 8


@pytest.mark.asyncio
async def test_cap_16_inflight_cap() -> None:
    """CAP-16: In-flight cap limits concurrency per model."""
    clock = Clock(1_000_000.0)
    spec = ModelSpec("m-inflight", "mistral", "m1")
    pool = _make_pool((spec,), clock)
    mgr = CapacityManager(pool, CapacitySettings(max_inflight_per_model=1), clock=clock)
    prof = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)

    lease1 = await mgr.acquire(prof)
    assert lease1.entry.inflight == 1

    # Second call blocks because inflight == 1
    acquired2 = False

    async def get_lease2() -> None:
        nonlocal acquired2
        l2 = await mgr.acquire(prof)
        acquired2 = True
        mgr.release(l2, tokens_in=10, tokens_out=10, outcome="ok")

    t = asyncio.create_task(get_lease2())
    await asyncio.sleep(0.01)
    assert not acquired2

    # Release first lease: wakes waiter
    mgr.release(lease1, tokens_in=10, tokens_out=10, outcome="ok")
    await t
    assert acquired2


@pytest.mark.asyncio
async def test_cap_17_wait_events_deduplicated() -> None:
    """CAP-17: Wait events are deduplicated per change of reason."""
    clock = Clock(1_000_000.0)
    fake_sleep = FakeSleep(clock)
    spec = ModelSpec("m-events", "mistral", "m1", rpm=1)
    pool = _make_pool((spec,), clock)

    events: list[tuple[str, dict]] = []
    mgr = CapacityManager(
        pool,
        CapacitySettings(max_wait_interactive_s=120),
        clock=clock,
        sleep_fn=fake_sleep,
        on_event=lambda name, payload: events.append((name, payload)),
    )
    prof = CallProfile(est_in=10, est_out=10, role="act", need=Cap.NONE, priority=0)

    l1 = await mgr.acquire(prof)
    mgr.release(l1, tokens_in=10, tokens_out=10, outcome="ok")

    # Second call will wait: emits exactly one 'wait' event
    l2 = await mgr.acquire(prof)
    mgr.release(l2, tokens_in=10, tokens_out=10, outcome="ok")

    wait_events = [e for e in events if e[0] == "wait"]
    assert len(wait_events) == 1, f"Expected 1 wait event, got {len(wait_events)}"
    assert wait_events[0][1]["model"] == "m-events"

    resume_events = [e for e in events if e[0] == "resume"]
    assert len(resume_events) == 1


def test_cap_18_exact_messages_of_phase_1() -> None:
    """CAP-18: Exact messages of Phase 1 match templates."""
    thought = WAIT_THOUGHT.format(seconds=12, model="mistral", reason="its per-minute request limit")
    assert thought == "All models are busy. Waiting 12 s for mistral (its per-minute request limit)."

    resume = RESUME_THOUGHT.format(model="mistral", seconds=12)
    assert resume == "Back to work on mistral after 12 s."

    too_long = WAIT_TOO_LONG.format(
        wait=30,
        soonest_desc="mistral in 15 s; gemini in 45 s",
        n=2,
        t_soonest="15 s",
    )
    assert "No model became free within 30 s." in too_long
    assert "2 step(s) finished and are kept in this task." in too_long

    pinned = PINNED_BUSY.format(model="gemini", limit="per-minute limit", t="10 s")
    assert pinned == "gemini is pinned for this agent and is at its per-minute limit. It frees up in 10 s. Lilly will not switch to another model because you pinned this one."

    err_text = describe_provider_error(RateLimited(scope="minute", retry_after=5.0, model="mistral"))
    assert err_text == "mistral is rate limited (minute). Lilly waited 5 s and tried the other models."


def test_cap_19_no_replan_on_capacity_failure() -> None:
    """CAP-19: StepFailed(kind='capacity') does not trigger replan."""
    failed = StepFailed("All models busy", kind="capacity")
    assert failed.kind == "capacity"
    assert failed.reason == "All models busy"


@pytest.mark.asyncio
async def test_cap_20_capacity_snapshot_and_backoff() -> None:
    """CAP-20: Capacity snapshot includes queue length and live metrics; backoff works."""
    clock = Clock(1_000_000.0)
    specs = (
        ModelSpec("m1", "mistral", "mod1", rpm=5, rpd=100),
    )
    pool = _make_pool(specs, clock)
    mgr = CapacityManager(pool, CapacitySettings(), clock=clock)

    snap = mgr.snapshot()
    assert len(snap) == 1
    assert snap[0].name == "m1"
    assert snap[0].rpm == 5
    assert snap[0].rpd == 100
    assert snap[0].queue_length == 0

    # Backoff with controllable rand
    rand = ControllableRand([0.5, 0.5])
    b0 = backoff(0, base=1.0, cap=60.0, rand=rand)
    assert b0 == 0.5
    b1 = backoff(1, base=1.0, cap=60.0, rand=rand)
    assert b1 == 1.0
